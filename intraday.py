#!/usr/bin/env python3
"""
Stock Analyzer — Combined Intraday Monitor + Data Collector
Polls every 1 minute, collects data for AI analysis, generates deduplicated signals for user.
With stronger signal filters for profitable trading.

Press Ctrl+C to stop.
"""

import os
import sys
import json
import time as _time_module
import logging
from datetime import date, datetime, timedelta, time as dt_time
from pathlib import Path

import pandas as pd
import numpy as np

PROJECT_DIR = Path(r"D:\OpenCode\Stock\Stock Analyzer")
CONFIG_FILE = PROJECT_DIR / "config.yaml"
SIGNALS_DIR = PROJECT_DIR / "signals"
DATA_DIR = PROJECT_DIR / "data" / "intraday"
LOG_DIR = PROJECT_DIR / "logs"
STATES_DIR = PROJECT_DIR / "signal_states"

for d in [SIGNALS_DIR, DATA_DIR, LOG_DIR, STATES_DIR]:
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


# ─── Config ──────────────────────────────────────────────────
def load_config():
    import yaml
    with open(CONFIG_FILE, "r") as f:
        return yaml.safe_load(f)

config = load_config()
WATCHLIST = config.get('watchlist', {}).get('stocks', [])

# Polling
POLL_INTERVAL_SEC = 60  # 1-minute

# Retention
RETENTION_DAYS = 30

# Strategy filters from config
STRATEGIES_CFG = config.get('strategies', {})
BREAKDOWN_CFG = STRATEGIES_CFG.get('breakdown_20d_low', {})
BB_RECLAIM_CFG = STRATEGIES_CFG.get('bb_reclaim_long', {})
INTRADAY_SHORT = BREAKDOWN_CFG.get('intraday', {})
INTRADAY_LONG = BB_RECLAIM_CFG.get('intraday_long', {})

FILTER = {
    # SHORT filters
    'short_rsi_min': INTRADAY_SHORT.get('rsi_min', 30),
    'short_rsi_max': INTRADAY_SHORT.get('rsi_max', 42),
    'short_gap_min_pct': INTRADAY_SHORT.get('gap_min_pct', 1.0),
    'short_breakdown_min_pct': INTRADAY_SHORT.get('breakdown_min_pct', 0.6),
    'short_nifty_confirmation': INTRADAY_SHORT.get('nifty_confirmation', True),
    'short_time_cutoff': INTRADAY_SHORT.get('time_cutoff', "12:00"),
    'short_target_pct': INTRADAY_SHORT.get('target_pct', 2.5),
    'short_sl_pct': INTRADAY_SHORT.get('sl_pct', 3.5),
    'short_enabled': INTRADAY_SHORT.get('enabled', True),
    # LONG filters
    'long_rsi_min': INTRADAY_LONG.get('rsi_min', 40) if INTRADAY_LONG else 40,
    'long_rsi_max': INTRADAY_LONG.get('rsi_max', 65) if INTRADAY_LONG else 65,
    'long_gap_min_pct': INTRADAY_LONG.get('gap_min_pct', 0.5) if INTRADAY_LONG else 0.5,
    'long_cross_min_pct': INTRADAY_LONG.get('cross_min_pct', 0.3) if INTRADAY_LONG else 0.3,
    'long_nifty_confirmation': INTRADAY_LONG.get('nifty_confirmation', True) if INTRADAY_LONG else True,
    'long_target_pct': INTRADAY_LONG.get('target_pct', 2.5) if INTRADAY_LONG else 2.5,
    'long_sl_pct': INTRADAY_LONG.get('sl_pct', 3.5) if INTRADAY_LONG else 3.5,
    'long_enabled': INTRADAY_LONG.get('enabled', True) if INTRADAY_LONG else True,
}

# Nifty regime filter
NIFTY_CFG = config.get('nifty_regime_filter', {})
NIFTY_BULLISH_ABOVE_SMA = NIFTY_CFG.get('bullish_above_sma', True)

# Capital & charges
RISK_CFG = config.get('risk', {})
CAPITAL = RISK_CFG.get('capital', 10000)

CHARGES_CFG = config.get('charges', {})
CHARGES = {
    "brokerage_per_order": CHARGES_CFG.get("brokerage_per_order", 20),
    "gst_rate": CHARGES_CFG.get("gst_rate", 0.18),
    "stt_sell_pct": CHARGES_CFG.get("stt_sell_pct", 0.001),
    "exchange_transaction_pct": CHARGES_CFG.get("exchange_transaction_pct", 0.0000375),
    "sebi_fee_per_cr": CHARGES_CFG.get("sebi_fee_per_cr", 10),
    "stamp_duty_buy_pct": CHARGES_CFG.get("stamp_duty_buy_pct", 0.00015),
}


# ─── Helpers ──────────────────────────────────────────────────
def calculate_charges(side, trade_value, quantity):
    quantity = max(quantity, 1)
    brokerage = CHARGES["brokerage_per_order"] * 2
    gst = brokerage * CHARGES["gst_rate"]
    stt = trade_value * CHARGES["stt_sell_pct"]
    exchange = trade_value * CHARGES["exchange_transaction_pct"] * 2
    sebi = trade_value * (CHARGES["sebi_fee_per_cr"] / 1e8)
    stamp_duty = trade_value * CHARGES["stamp_duty_buy_pct"]
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

def estimate_quantity(market_price):
    return max(10, min(200, int(CAPITAL / market_price * 0.4)))

def load_config_yaml():
    return load_config()


# ─── Data fetching ───────────────────────────────────────────
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
        df['high_20d'] = df['high'].rolling(20).max()
        df['avg_vol_20'] = df['volume'].rolling(20).mean()
        return df
    except Exception as e:
        logger.warning(f"Failed to fetch history for {symbol}: {e}")
        return None

def fetch_live_price(nlive, symbol):
    try:
        quote = nlive.stock_quote(symbol)
        if quote and 'tradeInfo' in quote and 'lastPrice' in quote['tradeInfo']:
            return float(quote['tradeInfo']['lastPrice'])
        return None
    except Exception:
        return None

def fetch_live_nifty(nlive):
    try:
        quote = nlive.index_quote('NIFTY 50')
        if quote:
            if isinstance(quote, dict):
                keys_to_try = [
                    ('tradeInfo', 'lastPrice'),
                    ('lastPrice',),
                    ('priceInfo', 'lastPrice'),
                ]
                for key_path in keys_to_try:
                    val = quote
                    for k in key_path:
                        if isinstance(val, dict) and k in val:
                            val = val[k]
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
                quote2 = nlive.stock_quote('NIFTY 50')
                if quote2 and isinstance(quote2, dict):
                    if 'tradeInfo' in quote2 and 'lastPrice' in quote2['tradeInfo']:
                        return float(quote2['tradeInfo']['lastPrice'])
                    if 'lastPrice' in quote2:
                        return float(quote2['lastPrice'])
            except Exception:
                pass
        return None
    except Exception:
        return None

def fetch_nifty_daily(hist):
    """Get Nifty daily data for regime check."""
    from jugaad_data.nse import NSEIndexHistory
    try:
        end_date = date.today() - timedelta(days=1)
        start_date = end_date - timedelta(days=30)
        raw = hist.index_raw('NIFTY 50', from_date=start_date, to_date=end_date)
        if not raw:
            return None, None, None
        df = pd.DataFrame(raw)
        df['date'] = pd.to_datetime(df['HistoricalDate'], format='%d %b %Y').dt.tz_localize(None)
        df = df.sort_values('date')
        last = df.iloc[-1]
        close = float(last['CLOSE'])
        sma_20 = float(df['CLOSE'].rolling(20).mean().iloc[-1])
        return close, sma_20, close > sma_20 if NIFTY_BULLISH_ABOVE_SMA else close < sma_20
    except Exception:
        return None, None, None


# ─── Signal state tracking ───────────────────────────────────
class SignalState:
    """Tracks a single signal's lifecycle."""
    def __init__(self, symbol, signal_type, strategy, **extra):
        self.symbol = symbol
        self.signal_type = signal_type
        self.strategy = strategy
        self.entry = extra.get('entry')
        self.sl = extra.get('sl')
        self.target = extra.get('target')
        self.extra = {k: v for k, v in extra.items() if k not in ('entry', 'sl', 'target')}
        self.state = 'active'
        self.fired_at = datetime.now().strftime('%H:%M:%S')
        self.current_ltp = self.entry
        self.day_low = self.entry
        self.day_high = self.entry

    def update(self, ltp, day_low, day_high):
        self.current_ltp = ltp
        self.day_low = min(self.day_low, day_low) if day_low is not None else self.day_low
        self.day_high = max(self.day_high, day_high) if day_high is not None else self.day_high
        if ltp is not None and self.target is not None and ltp <= self.target:
            self.state = 'target_hit'
        elif ltp is not None and self.sl is not None and ltp >= self.sl:
            self.state = 'sl_hit'

    def to_dict(self):
        d = {
            'symbol': self.symbol,
            'signal_type': self.signal_type,
            'strategy': self.strategy,
            'entry': self.entry,
            'sl': self.sl,
            'target': self.target,
            'state': self.state,
            'fired_at': self.fired_at,
            'current_ltp': self.current_ltp,
            'day_low': self.day_low,
            'day_high': self.day_high,
            'sl_pct': self.extra.get('sl_pct'),
            'target_pct': self.extra.get('target_pct'),
        }
        d.update(self.extra)
        return d


class SignalTracker:
    """Manages all active signal states. Deduplicates re-fires."""
    def __init__(self):
        self.signals = {}

    def check_and_add_short(self, symbol, ltp, day_low, day_high, signal_details):
        if symbol in self.signals:
            existing = self.signals[symbol]
            existing.update(ltp, day_low, day_high)
            return False, existing.to_dict()

        state = SignalState(
            symbol=symbol,
            signal_type='SHORT (intraday)',
            strategy=signal_details.get('strategy', '20D Low Breakdown'),
            entry=signal_details['entry'],
            sl=signal_details['sl'],
            target=signal_details['target'],
            **{k: v for k, v in signal_details.items() if k not in ('entry', 'sl', 'target', 'strategy')}
        )
        state.update(ltp, day_low, day_high)
        self.signals[symbol] = state
        return True, state.to_dict()

    def remove_expired(self):
        expired = [s for s in self.signals.values() if s.state in ('target_hit', 'sl_hit', 'expired')]
        for s in expired:
            del self.signals[s.symbol]
        return expired

    def get_all_active(self):
        return [s.to_dict() for s in self.signals.values()]


# ─── Main loop ───────────────────────────────────────────────
def run_combined():
    from jugaad_data.nse import NSELive, NSEHistory
    nlive = NSELive()
    hist_obj = NSEHistory()

    today_str = date.today().strftime('%Y-%m-%d')
    today_file = DATA_DIR / f"{today_str}.jsonl"
    signals_file = SIGNALS_DIR / f"signals_live_{today_str}.json"
    states_file = STATES_DIR / f"states_{today_str}.json"

    market_close = datetime.now().replace(hour=15, minute=30, second=0, microsecond=0)
    if datetime.now() >= market_close:
        print("Market already closed.")
        return

    intraday_tracker = {}
    if today_file.exists():
        try:
            with open(today_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        sym = rec.get('symbol', '')
                        ltp = rec.get('ltp')
                        if sym and ltp is not None:
                            if sym not in intraday_tracker:
                                intraday_tracker[sym] = {'low': ltp, 'high': ltp}
                            else:
                                intraday_tracker[sym]['low'] = min(intraday_tracker[sym]['low'], ltp)
                                intraday_tracker[sym]['high'] = max(intraday_tracker[sym]['high'], ltp)
                    except Exception:
                        pass
        except Exception:
            pass

    nifty_close, nifty_sma20, nifty_bullish = fetch_nifty_daily(hist_obj)
    nifty_regime = "BULLISH" if nifty_bullish else "BEARISH"

    signal_tracker = SignalTracker()

    existing_signals = []
    if signals_file.exists():
        try:
            with open(signals_file, 'r', encoding='utf-8') as f:
                existing_signals = json.load(f)
        except Exception:
            pass

    samples_collected = 0

    logger.info("=" * 60)
    logger.info("COMBINED INTRADAY MONITOR + DATA COLLECTOR")
    logger.info(f"Started: {datetime.now().strftime('%H:%M:%S')} | Poll: 1 min | Filters active")
    logger.info(f"Short filters: RSI {FILTER['short_rsi_min']}-{FILTER['short_rsi_max']}, gap≥{FILTER['short_gap_min_pct']}%, breakdown≥{FILTER['short_breakdown_min_pct']}%, time cutoff {FILTER['short_time_cutoff']}")
    logger.info(f"Long filters: RSI {FILTER['long_rsi_min']}-{FILTER['long_rsi_max']}, gap≥{FILTER['long_gap_min_pct']}%, cross≥{FILTER['long_cross_min_pct']}%")
    logger.info(f"Target: {FILTER['short_target_pct']}% (SHORT) / {FILTER['long_target_pct']}% (LONG) | SL: {FILTER['short_sl_pct']}% | Nifty confirm: {FILTER['short_nifty_confirmation']} / {FILTER['long_nifty_confirmation']}")
    logger.info(f"Nifty: {nifty_close} | 20 SMA: {nifty_sma20} | Regime: {nifty_regime}")
    logger.info("=" * 60)

    print()
    print("╔" + "═" * 58 + "╗")
    print("║  INTRADAY MONITOR + DATA COLLECTOR — Ctrl+C to stop                 ║")
    print("╚" + "═" * 58 + "╝")
    print(f"  Market close: 15:30 IST")
    print(f"  Data file: {today_file}")
    print(f"  Signals file: {signals_file}")
    print(f"  Filters: RSI {FILTER['short_rsi_min']}-{FILTER['short_rsi_max']} (SHORT) | gap≥{FILTER['short_gap_min_pct']}% | breakdown≥{FILTER['short_breakdown_min_pct']}% | time cutoff {FILTER['short_time_cutoff']}")
    print(f"  Long: RSI {FILTER['long_rsi_min']}-{FILTER['long_rsi_max']} | gap≥{FILTER['long_gap_min_pct']}% | cross≥{FILTER['long_cross_min_pct']}%")
    print(f"  Target: {FILTER['short_target_pct']}% (SHORT) / {FILTER['long_target_pct']}% (LONG) | SL: {FILTER['short_sl_pct']}%")
    print()

    try:
        while True:
            now = datetime.now()

            if now >= market_close:
                print("\n⏹ Market closed. Stopping.")
                logger.info("Market closed. Stopping.")
                break

            nifty_ltp = fetch_live_nifty(nlive)

            records = []
            for symbol in WATCHLIST:
                ltp = fetch_live_price(nlive, symbol)
                if ltp is None:
                    continue

                if symbol not in intraday_tracker:
                    intraday_tracker[symbol] = {'low': ltp, 'high': ltp}
                else:
                    intraday_tracker[symbol]['low'] = min(intraday_tracker[symbol]['low'], ltp)
                    intraday_tracker[symbol]['high'] = max(intraday_tracker[symbol]['high'], ltp)

                day_low = intraday_tracker[symbol]['low']
                day_high = intraday_tracker[symbol]['high']

                record = {
                    "ts": now.strftime('%Y-%m-%dT%H:%M:%S+05:30'),
                    "symbol": symbol,
                    "ltp": round(ltp, 2),
                    "intraday_high": round(day_high, 2),
                    "intraday_low": round(day_low, 2),
                    "nifty_ltp": round(nifty_ltp, 2) if nifty_ltp is not None else None,
                }
                records.append(record)

            if records:
                with open(today_file, 'a', encoding='utf-8') as f:
                    for rec in records:
                        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                samples_collected += len(records)

            all_new_signals = []
            all_state_updates = []

            for symbol in WATCHLIST:
                ltp = None
                for rec in records:
                    if rec['symbol'] == symbol:
                        ltp = rec['ltp']
                        break
                if ltp is None:
                    continue

                day_low = intraday_tracker.get(symbol, {}).get('low')
                day_high = intraday_tracker.get(symbol, {}).get('high')
                if day_low is None:
                    continue

                ydata = fetch_historical(hist_obj, symbol, days=60)
                if ydata is None or len(ydata) < 21:
                    continue

                last_closed = ydata.iloc[-1]
                prev_closed_row = ydata.iloc[-2] if len(ydata) > 1 else None

                rsi_yesterday = None
                if pd.notna(last_closed['rsi_14']):
                    rsi_yesterday = float(last_closed['rsi_14'])
                low_20d_yesterday = None
                if pd.notna(last_closed['low_20d']):
                    low_20d_yesterday = float(last_closed['low_20d'])
                prev_close = None
                if prev_closed_row is not None:
                    prev_close = float(prev_closed_row['close'])

                if FILTER['short_enabled'] and low_20d_yesterday is not None and day_low < low_20d_yesterday:
                    breakdown_pct = round((low_20d_yesterday - day_low) / low_20d_yesterday * 100, 2)
                    gap_pct = 0.0
                    if prev_close and prev_close != 0:
                        gap_pct = round((ltp - prev_close) / prev_close * 100, 2)

                    rsi_ok = rsi_yesterday is not None and FILTER['short_rsi_min'] <= rsi_yesterday <= FILTER['short_rsi_max']
                    gap_ok = gap_pct <= -FILTER['short_gap_min_pct']
                    breakdown_ok = breakdown_pct >= FILTER['short_breakdown_min_pct']
                    nifty_ok = (not FILTER['short_nifty_confirmation']) or (nifty_regime == "BEARISH")

                    # Time cutoff: don't trigger new signals after cutoff time
                    current_time = now.strftime("%H:%M")
                    time_cutoff = FILTER['short_time_cutoff']
                    time_ok = True
                    if time_cutoff and time_cutoff != "null":
                        time_ok = current_time < time_cutoff

                    if rsi_ok and gap_ok and breakdown_ok and nifty_ok and time_ok:
                        sl_price = round(ltp * (1 + FILTER['short_sl_pct'] / 100), 2)
                        target_price = round(ltp * (1 - FILTER['short_target_pct'] / 100), 2)
                        est_qty = estimate_quantity(ltp)
                        trade_value = ltp * est_qty
                        total_ch, breakdown_ch = calculate_charges('SELL', trade_value, est_qty)

                        signal_details = {
                            'type': 'SHORT (intraday)',
                            'strategy': '20D Low Breakdown',
                            'rsi_yesterday': round(rsi_yesterday, 1),
                            'gap_pct': gap_pct,
                            'breakdown_pct': breakdown_pct,
                            '20d_low': round(low_20d_yesterday, 2),
                            'entry': round(ltp, 2),
                            'sl': sl_price,
                            'target': target_price,
                            'target_pct': FILTER['short_target_pct'],
                            'sl_pct': FILTER['short_sl_pct'],
                            'charges': {
                                'estimated_total': round(total_ch, 2),
                                'breakdown': breakdown_ch,
                                'break_even_price': round(ltp - total_ch / est_qty, 2) if est_qty and est_qty > 0 else 0,
                                'estimated_quantity': est_qty,
                                'estimated_trade_value': round(trade_value, 2),
                            }
                        }

                        created, state_dict = signal_tracker.check_and_add_short(
                            symbol, ltp, day_low, day_high, signal_details
                        )

                        if created:
                            all_new_signals.append(state_dict)

                # ─── LONG: BB Mid Reclaim (intraday) ─────────────────
                if FILTER['long_enabled'] and nifty_bullish:
                    bb_mid_yesterday = None
                    if pd.notna(last_closed['bb_mid']):
                        bb_mid_yesterday = float(last_closed['bb_mid'])
                    prev_close_val = prev_close

                    if bb_mid_yesterday is not None and prev_close_val is not None:
                        cross_pct = round((ltp - bb_mid_yesterday) / bb_mid_yesterday * 100, 2)
                        gap_pct_long = round((ltp - prev_close_val) / prev_close_val * 100, 2) if prev_close_val else 0

                        rsi_ok_long = (rsi_yesterday is not None and
                                       FILTER['long_rsi_min'] <= rsi_yesterday <= FILTER['long_rsi_max'])
                        gap_ok_long = gap_pct_long >= FILTER['long_gap_min_pct']
                        cross_ok_long = cross_pct >= FILTER['long_cross_min_pct']

                        if rsi_ok_long and gap_ok_long and cross_ok_long:
                            sl_price_long = round(ltp * (1 - FILTER['long_sl_pct'] / 100), 2)
                            target_price_long = round(ltp * (1 + FILTER['long_target_pct'] / 100), 2)
                            est_qty_long = estimate_quantity(ltp)
                            trade_value_long = ltp * est_qty_long
                            total_ch_long, breakdown_ch_long = calculate_charges('BUY', trade_value_long, est_qty_long)

                            # Dedup: use symbol + "_LONG" key
                            long_key = f"{symbol}_LONG"
                            if long_key in signal_tracker.signals:
                                existing_long = signal_tracker.signals[long_key]
                                existing_long.update(ltp, day_low, day_high)
                            else:
                                long_state = SignalState(
                                    symbol=symbol,
                                    signal_type='LONG (intraday)',
                                    strategy='BB Mid Reclaim',
                                    entry=ltp,
                                    sl=sl_price_long,
                                    target=target_price_long,
                                    rsi_yesterday=round(rsi_yesterday, 1),
                                    gap_pct=gap_pct_long,
                                    cross_pct=cross_pct,
                                    bb_mid=round(bb_mid_yesterday, 2),
                                    sl_price=sl_price_long,
                                    target_price=target_price_long,
                                    target_pct=FILTER['long_target_pct'],
                                    sl_pct=FILTER['long_sl_pct'],
                                    charges={
                                        'estimated_total': round(total_ch_long, 2),
                                        'breakdown': breakdown_ch_long,
                                        'break_even_price': round(ltp + total_ch_long / est_qty_long, 2) if est_qty_long and est_qty_long > 0 else 0,
                                        'estimated_quantity': est_qty_long,
                                        'estimated_trade_value': round(trade_value_long, 2),
                                    }
                                )
                                long_state.update(ltp, day_low, day_high)
                                signal_tracker.signals[long_key] = long_state
                                all_new_signals.append(long_state.to_dict())

            expired = signal_tracker.remove_expired()
            for exp in expired:
                all_state_updates.append(exp.to_dict())

            ts_str = now.strftime('%H:%M:%S')
            nifty_str = f"Nifty:{nifty_ltp:,.0f}" if nifty_ltp is not None else "Nifty:N/A"
            active_stocks = len(intraday_tracker)
            active_signals = len(signal_tracker.signals)
            print(f"  [{ts_str}] {nifty_str} | {active_stocks}/{len(WATCHLIST)} stocks | Samples: {samples_collected} | Signals: {active_signals}")

            for sig in all_new_signals:
                sig_type = sig['signal_type']
                s = sig
                if 'LONG' in sig_type:
                    print(f"\n  ⚡ NEW SIGNAL — {sig_type} — {sig['symbol']}")
                    entry_val = s.get('entry', s.get('sl_price', None))
                    sl_val = s.get('sl_price', s.get('sl', None))
                    target_val = s.get('target_price', s.get('target', None))
                    print(f"     Entry: Rs.{entry_val} | SL: Rs.{sl_val} ({s.get('sl_pct', '?')}% below)")
                    print(f"     Target: Rs.{target_val} ({s.get('target_pct', '?')}% above)")
                    print(f"     RSI (yesterday): {s.get('rsi_yesterday','?')} | Gap: {s.get('gap_pct','?')}% | Cross above BB mid: {s.get('cross_pct','?')}% (BB mid Rs.{s.get('bb_mid','?')})")
                    print(f"     Nifty regime: {nifty_regime} ({nifty_close} vs 20 SMA {nifty_sma20})")
                    print(f"     Charges (est.): Rs.{s['charges']['estimated_total']} | Break-even: Rs.{s['charges']['break_even_price']}")
                    print(f"     Quantity: {s['charges']['estimated_quantity']} shares | Trade value: Rs.{s['charges']['estimated_trade_value']}")
                    entry_zone_low = round(entry_val * 0.997, 2) if entry_val else None
                    entry_zone_high = entry_val
                    print(f"     Entry zone: Rs.{entry_zone_low} — Rs.{entry_zone_high}")
                    kite_limit = round(entry_val * 1.01, 2) if entry_val else None
                    print(f"     On Kite: Search '{s['symbol']}' → BUY → MIS → Limit Rs.{kite_limit} → Stop Loss Rs.{sl_val} → Place")
                    print(f"     Exit: Target Rs.{target_val} OR price falls below BB mid Rs.{s.get('bb_mid','?')}")
                else:
                    print(f"\n  ⚡ NEW SIGNAL — {sig_type} — {sig['symbol']}")
                    print(f"     Entry: Rs.{s['entry']} | SL: Rs.{s['sl']} ({s['sl_pct']}% above)")
                    print(f"     Target: Rs.{s['target']} ({s['target_pct']}% below)")
                    print(f"     RSI (yesterday): {s.get('rsi_yesterday','?')} | Gap: {s.get('gap_pct','?')}% | Breakdown: {s.get('breakdown_pct','?')}% below 20D low (Rs.{s.get('20d_low','?')})")
                    print(f"     Nifty regime: {nifty_regime} ({nifty_close} vs 20 SMA {nifty_sma20})")
                    print(f"     Charges (est.): Rs.{s['charges']['estimated_total']} | Break-even: Rs.{s['charges']['break_even_price']}")
                    print(f"     Quantity: {s['charges']['estimated_quantity']} shares | Trade value: Rs.{s['charges']['estimated_trade_value']}")
                    print(f"     Entry zone: Rs.{round(s['entry']*0.997, 2)} — Rs.{s['entry']}")
                    print(f"     On Kite: Search '{s['symbol']}' → SELL → MIS → Limit Rs.{round(s['entry']*0.99, 2)} → Stop Loss Rs.{s['sl']} → Place")
                    print(f"     Exit: Target Rs.{s['target']} OR price rises above 20D low Rs.{s.get('20d_low','?')}")

            for sig in all_state_updates:
                if sig['state'] == 'target_hit':
                    print(f"\n  🎯 TARGET HIT — {sig['signal_type']} — {sig['symbol']}")
                    print(f"     Target Rs.{sig['target']} reached! Exit now.")
                elif sig['state'] == 'sl_hit':
                    print(f"\n  🛑 SL HIT — {sig['signal_type']} — {sig['symbol']}")
                    print(f"     SL Rs.{sig['sl']} reached! Loss limited to {sig['sl_pct']}%.")

            if all_new_signals or all_state_updates:
                existing_signals.extend(all_new_signals)
                with open(signals_file, 'w', encoding='utf-8') as f:
                    json.dump(existing_signals, f, indent=2, ensure_ascii=False)

                all_states = signal_tracker.get_all_active()
                with open(states_file, 'w', encoding='utf-8') as f:
                    json.dump({
                        'date': today_str,
                        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'nifty_close': nifty_close,
                        'nifty_sma20': nifty_sma20,
                        'nifty_regime': nifty_regime,
                        'active_signals': all_states,
                        'filters': FILTER,
                        'filters_passed_today': {
                            'short_rsi_range': f"{FILTER['short_rsi_min']}-{FILTER['short_rsi_max']}",
                            'short_gap_min_pct': FILTER['short_gap_min_pct'],
                            'short_breakdown_min_pct': FILTER['short_breakdown_min_pct'],
                            'short_time_cutoff': FILTER['short_time_cutoff'],
                            'long_rsi_range': f"{FILTER['long_rsi_min']}-{FILTER['long_rsi_max']}",
                            'long_gap_min_pct': FILTER['long_gap_min_pct'],
                            'long_cross_min_pct': FILTER['long_cross_min_pct'],
                        }
                    }, f, indent=2, ensure_ascii=False)

                logger.info(f"Signals updated: {len(all_new_signals)} new, {len(all_state_updates)} updates")

            _time_module.sleep(POLL_INTERVAL_SEC)

    except KeyboardInterrupt:
        logger.info("Stopped by user.")
        print("\n⏹ Stopped by user.")
    except Exception as e:
        logger.error(f"Error: {e}")
        print(f"\n Error: {e}")

    cutoff = date.today() - timedelta(days=RETENTION_DAYS)
    removed = 0
    for f in DATA_DIR.glob("*.jsonl"):
        try:
            file_date = datetime.strptime(f.stem, "%Y-%m-%d").date()
            if file_date < cutoff:
                f.unlink()
                removed += 1
        except Exception:
            pass
    if removed:
        logger.info(f"Cleaned up {removed} file(s) older than {RETENTION_DAYS} days")

    print(f"\n{'='*60}")
    print(f"  FINISHED")
    print(f"  Samples collected: {samples_collected}")
    print(f"  Data file: {today_file}")
    print(f"  Signals file: {signals_file}")
    print(f"{'='*60}")


if __name__ == '__main__':
    print("\n Collecting 1-min data + generating signals (stronger filters).")
    print(f" Data → data/intraday/{date.today().strftime('%Y-%m-%d')}.jsonl")
    print(f" Signals → signals/signals_live_{date.today().strftime('%Y%m%d')}.json")
    print(f" States → signal_states/states_{date.today().strftime('%Y%m%d')}.json")
    print()
    run_combined()
