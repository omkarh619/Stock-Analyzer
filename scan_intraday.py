#!/usr/bin/env python3
"""
Stock Analyzer — Intraday Signal Monitor
Polls live market data every 5 minutes and alerts when a signal forms.
Trigger it when you want to monitor. Press Ctrl+C to stop.
"""

import os
import sys
import json
import time as _time_module
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import numpy as np

PROJECT_DIR = Path(r"D:\OpenCode\Stock\Stock Analyzer")
CONFIG_FILE = PROJECT_DIR / "config.yaml"
SIGNALS_DIR = PROJECT_DIR / "signals"
LOG_DIR = PROJECT_DIR / "logs"

for d in [SIGNALS_DIR, LOG_DIR]:
    d.mkdir(parents=True, exist_ok=True)

log_file = LOG_DIR / f"intraday_{date.today().strftime('%Y%m%d')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger(__name__)


# ─── Charges config ──────────────────────────────────────
def load_charges():
    """Load charges config from config.yaml."""
    cfg = load_config()
    charges_cfg = cfg.get("charges", {})
    return {
        "brokerage_per_order": charges_cfg.get("brokerage_per_order", 20),
        "gst_rate": charges_cfg.get("gst_rate", 0.18),
        "stt_sell_pct": charges_cfg.get("stt_sell_pct", 0.001),
        "exchange_transaction_pct": charges_cfg.get("exchange_transaction_pct", 0.0000375),
        "sebi_fee_per_cr": charges_cfg.get("sebi_fee_per_cr", 10),
        "stamp_duty_buy_pct": charges_cfg.get("stamp_duty_buy_pct", 0.00015),
        "broker_name": charges_cfg.get("broker", "Zerodha"),
    }

_charges_cache = None

def get_charges():
    """Return cached charges dict."""
    global _charges_cache
    if _charges_cache is None:
        _charges_cache = load_charges()
    return _charges_cache

def get_capital():
    """Return trading capital from config (default Rs.10,000)."""
    cfg = load_config()
    return cfg.get("risk", {}).get("capital", 10000)

def calculate_charges(side, trade_value, quantity):
    """Calculate total per-trade charges and return (total, breakdown_dict)."""
    charges_cfg = get_charges()
    quantity = max(quantity, 1)  # avoid division by zero
    
    brokerage = charges_cfg["brokerage_per_order"] * 2  # buy + sell
    gst = brokerage * charges_cfg["gst_rate"]
    stt = trade_value * charges_cfg["stt_sell_pct"]
    exchange = trade_value * charges_cfg["exchange_transaction_pct"] * 2
    sebi = trade_value * (charges_cfg["sebi_fee_per_cr"] / 1e8)
    stamp_duty = trade_value * charges_cfg["stamp_duty_buy_pct"]
    
    total = brokerage + gst + stt + exchange + sebi + stamp_duty
    
    breakdown = {
        "brokerage": round(brokerage, 2),
        "gst": round(gst, 2),
        "stt": round(stt, 2),
        "exchange": round(exchange, 2),
        "sebi": round(sebi, 2),
        "stamp_duty": round(stamp_duty, 2),
    }
    return round(total, 2), breakdown

def estimate_quantity(market_price, direction, capital_size=None):
    """Suggest a trade quantity based on typical capital sizes and price."""
    if capital_size is None:
        capital_size = get_capital()  # read from config (default ₹10,000)
    if direction == "LONG":
        return max(10, min(200, int(capital_size / market_price * 0.4)))
    else:
        return max(10, min(200, int(capital_size / market_price * 0.4)))

def load_config():
    import yaml
    with open(CONFIG_FILE, "r") as f:
        return yaml.safe_load(f)

config = load_config()
WATCHLIST = config.get('watchlist', {}).get('stocks', [])
POLL_INTERVAL_SEC = 5 * 60

def get_intraday_cutoff():
    """Return cutoff time as datetime.time, or None if disabled."""
    cutoff_str = config.get('time', {}).get('intraday_cutoff', None)
    if not cutoff_str:
        return None
    from datetime import time as dt_time
    parts = cutoff_str.split(':')
    return dt_time(int(int(parts[0])), int(int(parts[1])))

def is_too_late_for_trading():
    """Return True if current time is past the intraday cutoff."""
    cutoff = get_intraday_cutoff()
    if cutoff is None:
        return False
    now = datetime.now().time()
    return now > cutoff

def _serialize(obj):
    import numpy as np
    if isinstance(obj, (np.integer,)):
        return int(obj)
    elif isinstance(obj, (np.floating,)):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj

def _clean_for_json(data):
    if isinstance(data, dict):
        return {k: _clean_for_json(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [_clean_for_json(v) for v in data]
    return _serialize(data) if data is not None else None

def fetch_historical(hist, symbol, days=60):
    from jugaad_data.nse import NSEHistory
    end_date = date.today() - timedelta(days=1)
    start_date = end_date - timedelta(days=days + 10)
    try:
        raw = hist.stock_raw(symbol, from_date=start_date, to_date=end_date)
        if not raw or len(raw) < 21:
            return None
        df = pd.DataFrame(raw)
        df['date'] = pd.to_datetime(df['CH_TIMESTAMP']).dt.tz_localize(None)
        df = df.sort_values('date').reset_index(drop=True)
        df['close'] = pd.to_numeric(df['CH_CLOSING_PRICE'], errors='coerce')
        df['high'] = pd.to_numeric(df['CH_TRADE_HIGH_PRICE'], errors='coerce')
        df['low'] = pd.to_numeric(df['CH_TRADE_LOW_PRICE'], errors='coerce')
        df['volume'] = pd.to_numeric(df['CH_TOT_TRADED_QTY'], errors='coerce')
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        df['rsi_14'] = 100 - (100 / (1 + gain / loss.replace(0, np.nan)))
        df['bb_mid'] = df['close'].rolling(20).mean()
        df['low_20d'] = df['low'].rolling(20).min()
        df['avg_vol_20'] = df['volume'].rolling(20).mean()
        return df
    except Exception as e:
        logger.warning(f"Failed to fetch hist for {symbol}: {e}")
        return None

def fetch_live_price(nlive, symbol):
    try:
        quote = nlive.stock_quote(symbol)
        if quote and 'tradeInfo' in quote and 'lastPrice' in quote['tradeInfo']:
            return float(quote['tradeInfo']['lastPrice'])
        return None
    except:
        return None

def fetch_live_nifty(nlive):
    try:
        quote = nlive.index_quote('NIFTY 50')
        if quote:
            if isinstance(quote, dict):
                for k in ['tradeInfo.lastPrice', 'lastPrice', 'priceInfo.lastPrice']:
                    parts = k.split('.')
                    val = quote
                    for p in parts:
                        if isinstance(val, dict) and p in val:
                            val = val[p]
                        else:
                            val = None
                            break
                    if val is not None:
                        return float(val)
                if 'data' in quote and isinstance(quote['data'], list) and len(quote['data']) > 0:
                    item = quote['data'][0]
                    if isinstance(item, dict) and 'lastPrice' in item:
                        return float(item['lastPrice'])
            elif isinstance(quote, list) and len(quote) > 0:
                item = quote[0]
                if isinstance(item, dict) and 'lastPrice' in item:
                    return float(item['lastPrice'])
        try:
            quote = nlive.stock_quote('NIFTY 50')
            if quote and isinstance(quote, dict):
                if 'tradeInfo' in quote and 'lastPrice' in quote['tradeInfo']:
                    return float(quote['tradeInfo']['lastPrice'])
                if 'lastPrice' in quote:
                    return float(quote['lastPrice'])
        except:
            pass
        return None
    except Exception as e:
        logger.debug(f"Live Nifty failed: {e}")
        return None

def check_intraday_signals(symbol, hist, nlive, yesterdays_data, intraday_low, intraday_high, live_ltp):
    signals = []
    if yesterdays_data is None or live_ltp is None:
        return signals
    
    last_closed = yesterdays_data.iloc[-1]
    prev_closed = yesterdays_data.iloc[-2] if len(yesterdays_data) > 1 else None
    
    rsi_yesterday = last_closed['rsi_14'] if pd.notna(last_closed['rsi_14']) else None
    bb_mid_yesterday = last_closed['bb_mid'] if pd.notna(last_closed['bb_mid']) else None
    low_20d_yesterday = last_closed['low_20d'] if pd.notna(last_closed['low_20d']) else None
    
    if low_20d_yesterday is None or bb_mid_yesterday is None:
        return signals
    
    # SHORT: 20D Low Breakdown
    below_20d_low = (intraday_low is not None) and (intraday_low < low_20d_yesterday)
    rsi_ok_short = rsi_yesterday is not None and rsi_yesterday < 40
    
    if below_20d_low and rsi_ok_short:
        distance_pct = round((low_20d_yesterday - intraday_low) / low_20d_yesterday * 100, 2)
        sl_price = round(live_ltp * 1.035, 2)  # 3.5% above entry (SHORT)
        target_price = round(live_ltp * 0.975, 2)  # ~2.5% below entry (take-profit)
        target_pct = 2.5
        _too_late = is_too_late_for_trading()  # Check if too late in the day
        
        # Plain-language instructions for a beginner
        short_instruction = (
            f"This looks like a SELL (short) setup. {symbol} price dropped below its 20-day low of Rs.{low_20d_yesterday:,.2f}. "
            f"If you want to act on this:"
        )
        short_entry = (
            f"  1. On Kite: Search '{symbol}' → Click SELL → Select Product: MIS (Intraday) → "
            f"Enter price: Rs.{live_ltp:,.2f} (market) or Rs.{round(live_ltp*0.99,2):,.2f} (limit, for a better price) → "
            f"Quantity: decide based on your capital (see note below) → Place order"
        )
        short_sl = (
            f"  2. Stop Loss (safety net): Set a STOP LOSS order at Rs.{sl_price:,.2f}. "
            f"If price rises to this level, your position closes automatically — limiting your loss to about 3.5%."
        )
        short_exit = (
            f"  3. Exit: Watch the chart. If price rises above Rs.{low_20d_yesterday:,.2f} (the level it broke), "
            f"consider exiting. Or if the RSI line (the wavy line at the bottom of your chart) drops below 30, consider exiting."
        )

        # ─── Compute charges for SHORT ──────────────────────────────────────
        charges_cfg = get_charges()
        est_qty_s = estimate_quantity(live_ltp, 'SHORT')
        trade_value_s = live_ltp * est_qty_s
        total_ch_s, breakdown_ch_s = calculate_charges('SELL', trade_value_s, est_qty_s)

        signals.append({
            'type': 'SHORT (intraday)',
            'strategy': '20D Low Breakdown',
            'stock': symbol,
            'time': datetime.now().strftime('%H:%M:%S'),
            'live_ltp': round(live_ltp, 2),
            'intraday_low': round(intraday_low, 2),
            '20d_low': round(low_20d_yesterday, 2),
            'distance_pct': distance_pct,
            'rsi_yesterday': round(rsi_yesterday, 1),
            'sl_price': sl_price,
            'target_price': target_price,
            'target_pct': target_pct,
            'entry_price': round(live_ltp, 2),
            'condition': f"Intraday low {intraday_low:.2f} broke below 20D low {low_20d_yesterday:.2f} ({distance_pct}% below). RSI yesterday: {rsi_yesterday:.1f}.",
            'beginner_instruction': short_instruction,
            'beginner_entry': short_entry,
            'beginner_sl': short_sl,
            'beginner_exit': short_exit,
            'action': f"SL: Rs.{sl_price} (3.5% above entry). Target: Rs.{target_price} ({target_pct}% below entry). Exit when RSI < 45.",
            'too_late': _too_late,
            'charges': {
                'broker': 'Zerodha (intraday MIS)',
                'estimated_total': round(total_ch_s, 2),
                'breakdown': breakdown_ch_s,
                'break_even_price': round(live_ltp - total_ch_s / est_qty_s, 2) if est_qty_s > 0 else 0,
                'min_profit_for_value': round(est_qty_s * 0.005, 2) if est_qty_s > 0 else 0,
                'estimated_quantity': est_qty_s,
                'estimated_trade_value': round(trade_value_s, 2),
            }
        })
    
    # LONG: BB Mid Reclaim
    reclaim = False
    reclaim_pct = 0
    if intraday_high is not None and bb_mid_yesterday is not None:
        if intraday_high > bb_mid_yesterday * 1.003:
            if prev_closed is not None and pd.notna(prev_closed.get('bb_mid', None)):
                if prev_closed['close'] <= prev_closed['bb_mid']:
                    reclaim = True
                    reclaim_pct = round((live_ltp / bb_mid_yesterday - 1) * 100, 2)
    
    if reclaim:
        sl_price = round(live_ltp * 0.965, 2)
        target_price = round(live_ltp * 1.025, 2)  # ~2.5% above entry (take-profit)
        target_pct = 2.5
        _too_late = is_too_late_for_trading()

        # Plain-language instructions for a beginner
        long_instruction = (
            f"This looks like a BUY setup. {symbol} price went above its 20-day average of Rs.{bb_mid_yesterday:,.2f}. "
            f"If you want to act on this:"
        )
        long_entry = (
            f"  1. On Kite: Search '{symbol}' → Click BUY → Select Product: MIS (Intraday) → "
            f"Enter price: Rs.{live_ltp:,.2f} (market) or Rs.{round(live_ltp*0.98,2):,.2f} (limit, for a better price) → "
            f"Quantity: decide based on your capital (see note below) → Place order"
        )
        long_sl = (
            f"  2. Stop Loss (safety net): Set a STOP LOSS order at Rs.{sl_price:,.2f}. "
            f"If price falls to this level, your position closes automatically — limiting your loss to about 3.5%."
        )
        long_exit = (
            f"  3. Exit: Watch the chart. If price falls below Rs.{bb_mid_yesterday:,.2f} (the average it crossed above), "
            f"consider exiting. Or if the RSI line (the wavy line at the bottom of your chart) goes above 70, consider exiting."
        )

        # ─── Compute charges (before building signal dict) ────────────────────────
        charges_cfg = get_charges()
        est_qty = estimate_quantity(live_ltp, 'LONG')
        trade_value = live_ltp * est_qty
        total_charges, charge_breakdown = calculate_charges('BUY', trade_value, est_qty)

        signals.append({
            'type': 'LONG (intraday)',
            'strategy': 'BB Mid Reclaim',
            'stock': symbol,
            'time': datetime.now().strftime('%H:%M:%S'),
            'live_ltp': round(live_ltp, 2),
            'intraday_high': round(intraday_high, 2),
            'bb_mid': round(bb_mid_yesterday, 2),
            'reclaim_pct': reclaim_pct,
            'rsi_yesterday': round(rsi_yesterday, 1) if rsi_yesterday else None,
            'sl_price': sl_price,
            'entry_price': round(live_ltp, 2),
            'condition': f"Intraday high {intraday_high:.2f} crossed above BB middle {bb_mid_yesterday:.2f} (+{reclaim_pct}%). Yesterday closed at/below BB mid.",
            'beginner_instruction': long_instruction,
            'beginner_entry': long_entry,
            'beginner_sl': long_sl,
            'beginner_exit': long_exit,
            'action': f"SL: Rs.{sl_price} (3.5% below entry). Target: Rs.{target_price} ({target_pct}% above entry). Exit when RSI > 55.",
            'too_late': _too_late,
            'charges': {
                'broker': 'Zerodha (intraday MIS)',
                'estimated_total': round(total_charges, 2),
                'breakdown': charge_breakdown,
                'break_even_price': round(live_ltp + total_charges / est_qty, 2) if est_qty > 0 else 0,
                'min_profit_for_value': round(est_qty * 0.005, 2) if est_qty > 0 else 0,
                'estimated_quantity': est_qty,
                'estimated_trade_value': round(trade_value, 2),
            }
        })

    return signals

class IntradayTracker:
    def __init__(self):
        self.tracking = {}
    
    def update(self, symbol, ltp):
        if symbol not in self.tracking:
            self.tracking[symbol] = {'low': ltp, 'high': ltp}
        else:
            self.tracking[symbol]['low'] = min(self.tracking[symbol]['low'], ltp)
            self.tracking[symbol]['high'] = max(self.tracking[symbol]['high'], ltp)
    
    def get_low(self, symbol):
        return self.tracking[symbol]['low'] if symbol in self.tracking else None
    
    def get_high(self, symbol):
        return self.tracking[symbol]['high'] if symbol in self.tracking else None

def run_intraday_monitor():
    from jugaad_data.nse import NSELive, NSEHistory
    nlive = NSELive()
    hist = NSEHistory()
    
    today_str = date.today().strftime('%Y-%m-%d')
    start_time = datetime.now()
    market_close = start_time.replace(hour=15, minute=30, second=0, microsecond=0)
    
    logger.info("="*55)
    logger.info("INTRADAY MONITOR — Press Ctrl+C to stop")
    logger.info(f"Started: {start_time.strftime('%H:%M:%S')} | Poll: {POLL_INTERVAL_SEC//60} min")
    logger.info("="*55)
    
    print()
    print("╔" + "═"*53 + "╗")
    print("║  INTRADAY MONITOR — Ctrl+C to stop                    ║")
    print("╚" + "═"*53 + "╝")
    print()
    
    detected_signals = set()
    live_signals_file = SIGNALS_DIR / f"signals_live_{today_str}.json"
    
    existing_live = []
    if live_signals_file.exists():
        try:
            with open(live_signals_file, 'r') as f:
                existing_live = json.load(f)
            for sig in existing_live:
                key = f"{sig.get('type','')}/{sig.get('stock','')}/{sig.get('time','')}"
                detected_signals.add(key)
        except:
            pass
    
    intraday_tracker = IntradayTracker()
    check_count = 0
    
    try:
        while True:
            check_count += 1
            now = datetime.now()
            
            if now >= market_close:
                print("\n⏹ Market closed (15:30 IST). Monitor stopped.")
                break
            
            print(f"\n{'─'*55}")
            print(f"  Check #{check_count} — {now.strftime('%H:%M:%S')} IST")
            
            # Nifty
            nifty_live = fetch_live_nifty(nlive)
            nifty_regime = "BEARISH"
            try:
                from jugaad_data.nse import NSEIndexHistory
                ihist = NSEIndexHistory()
                raw = ihist.index_raw('NIFTY 50',
                    from_date=date.today() - timedelta(days=60),
                    to_date=date.today() - timedelta(days=1))
                if raw:
                    ndf = pd.DataFrame(raw)
                    ndf['date'] = pd.to_datetime(ndf['HistoricalDate'], format='%d %b %Y').dt.tz_localize(None)
                    ndf = ndf.sort_values('date')
                    ndf['close'] = pd.to_numeric(ndf['CLOSE'], errors='coerce')
                    ndf['sma_20'] = ndf['close'].rolling(20).mean()
                    if len(ndf) > 20:
                        last_n = ndf.iloc[-1]
                        if last_n['close'] > last_n['sma_20']:
                            nifty_regime = "BULLISH"
            except:
                pass
            
            nifty_str = f"Nifty: {nifty_live:,.2f}" if nifty_live else "Nifty: N/A"
            print(f"  {nifty_str:<20} Regime: {nifty_regime}")
            print(f"  Stocks: {len(WATCHLIST)} | Next check in {POLL_INTERVAL_SEC//60} min")
            print()
            
            # Compact header
            print(f"  {'Stock':<13} {'LTP':>9}  {'BB':>7}  {'RSI':>5}  {'20D':>7}  {'Gap':>6}  {'DayLow':>10}  {'DayHigh':>10}")
            print(f"  {'-'*13}  {'-'*9}  {'-'*7}  {'-'*5}  {'-'*7}  {'-'*6}  {'-'*10}  {'-'*10}")
            
            all_new_signals = []
            
            for symbol in WATCHLIST:
                ydata = fetch_historical(hist, symbol, days=60)
                live_ltp = fetch_live_price(nlive, symbol)
                
                if live_ltp is None:
                    print(f"  {symbol:<13} {'N/A':>9}")
                    continue
                
                intraday_tracker.update(symbol, live_ltp)
                intraday_low = intraday_tracker.get_low(symbol)
                intraday_high = intraday_tracker.get_high(symbol)
                
                # Build compact line
                line = f"  {symbol:<13} {live_ltp:>9,.2f}"
                
                if ydata is not None and len(ydata) > 0:
                    last = ydata.iloc[-1]
                    bb_mid = last['bb_mid'] if pd.notna(last['bb_mid']) else None
                    low_20d = last['low_20d'] if pd.notna(last['low_20d']) else None
                    rsi = last['rsi_14'] if pd.notna(last['rsi_14']) else None
                    prev_close = ydata.iloc[-2]['close'] if len(ydata) > 1 else None
                    
                    if bb_mid is not None:
                        line += f"  {(live_ltp/bb_mid-1)*100:>+6.1f}%"
                    else:
                        line += f"  {'---':>6}"
                    if rsi is not None:
                        line += f"  {rsi:>4.1f}"
                    else:
                        line += f"  {'---':>4}"
                    if low_20d is not None:
                        line += f"  {(live_ltp/low_20d-1)*100:>+6.1f}%"
                    else:
                        line += f"  {'---':>6}"
                    if prev_close is not None:
                        line += f"  {(live_ltp/prev_close-1)*100:>+5.1f}%"
                    else:
                        line += f"  {'---':>5}"
                else:
                    line += f"  {'---':>6}  {'---':>4}  {'---':>6}  {'---':>5}"
                
                line += f"  {intraday_low:>10,.2f}  {intraday_high:>10,.2f}"
                
                # Check signals
                signals = check_intraday_signals(symbol, hist, nlive, ydata, intraday_low, intraday_high, live_ltp)
                
                for sig in signals:
                    sig_key = f"{sig['type']}/{sig['stock']}/{sig['time']}"
                    if sig_key not in detected_signals:
                        detected_signals.add(sig_key)
                        all_new_signals.append(sig)
                        print(f"\n  ⚡ SIGNAL: {sig['type']} — {sig['stock']}")
                        # ─── Time cutoff check ──────────────────────────────────────────
                        if sig.get('too_late', False):
                            cutoff = get_intraday_cutoff()
                            print(f"     ⚠️  NOT RECOMMENDED — current time is past the intraday cutoff ({cutoff.strftime('%H:%M')} IST)")
                            print(f"     The setup qualified, but there may not be enough time left in the day to reach your target.")
                            print(f"     Consider waiting for the next trading day, or evaluate with extra caution.")
                            print()
                            continue  # Skip the full analysis below
                        
                        if 'beginner_instruction' in sig:
                            print(f"     {sig['beginner_instruction']}")
                            print(f"     {sig['beginner_entry']}")
                            print(f"     {sig['beginner_sl']}")
                            print(f"     {sig['beginner_exit']}")

                        # Charges + target awareness
                        if 'charges' in sig:
                            c = sig['charges']
                            print(f"     Charges (Zerodha intraday MIS, est.): Rs.{c['estimated_total']:,.2f}")
                            be = c.get('break_even_price', 0)
                            print(f"     Break-even for this trade size: Rs.{be:,.2f}" if be > 0 else "     Break-even: N\\A")
                            # Target (take-profit)
                            tp = sig.get('target_price', 0)
                            tpp = sig.get('target_pct', 0)
                            if tp > 0:
                                direction = "rise" if sig['type'].startswith('LONG') else "drop"
                                print(f"     🎯 Target (take-profit): Rs.{tp:,.2f} ({tpp}% {direction})")
                                print(f"     Exit here if reached — don't get greedy, take the profit.")
                            # Quantity guide
                            print(f"     Quantity guide: With your capital (~Rs.10,000), a typical trade might be 10-25 shares. With MIS (intraday), you may get leverage — start small, paper trade first.")
                        else:
                            print(f"     LTP: Rs.{sig['live_ltp']:,.2f}")
                            print(f"     {sig['condition']}")
                            print(f"     {sig['action']}")
                        print()
                
                print(line)
            
            # Save signals
            if all_new_signals:
                existing_live.extend(all_new_signals)
                with open(live_signals_file, 'w', encoding='utf-8') as f:
                    json.dump(_clean_for_json(existing_live), f, indent=2, ensure_ascii=False)
                logger.info(f"New signals saved: {len(all_new_signals)}")
            
            print(f"\n  Sleep {POLL_INTERVAL_SEC//60} min. Ctrl+C to stop.")
            _time_module.sleep(POLL_INTERVAL_SEC)
            
    except KeyboardInterrupt:
        logger.info("Monitor stopped by user.")
        print("\n⏹ Monitor stopped.")
    
    print(f"\n{'='*55}")
    print(f"  MONITOR FINISHED")
    print(f"  Checks: {check_count} | Signals: {len(detected_signals)}")
    print(f"  File: {live_signals_file}")
    print(f"{'='*55}")

if __name__ == '__main__':
    print("\n⚠ Stable internet required. Polls every 5 min until market close (15:30 IST) or Ctrl+C.")
    print()
    run_intraday_monitor()
