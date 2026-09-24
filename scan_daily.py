#!/usr/bin/env python3
"""
Stock Analyzer — Daily Signal Scanner
Scans Nifty 50 stocks for trading signals based on configured strategies.
Writes clean signal output to JSON for dashboard/execution.
"""

import os
import sys
import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import numpy as np

# ─── Paths ─────────────────────────────────────────────────────
PROJECT_DIR = Path(r"D:\OpenCode\Stock\Stock Analyzer")
CONFIG_FILE = PROJECT_DIR / "config.yaml"
SIGNALS_DIR = PROJECT_DIR / "signals"
DATA_DIR = PROJECT_DIR / "data"
LOG_DIR = PROJECT_DIR / "logs"

# Ensure directories exist
for d in [SIGNALS_DIR, DATA_DIR, LOG_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ─── Setup logging ─────────────────────────────────────────────
log_file = LOG_DIR / f"scan_{date.today().strftime('%Y%m%d')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger(__name__)

# ─── Config loading ────────────────────────────────────────────
def load_config():
    """Load configuration from YAML file."""
    import yaml
    if not CONFIG_FILE.exists():
        logger.error(f"Config file not found: {CONFIG_FILE}")
        sys.exit(1)
    with open(CONFIG_FILE, "r") as f:
        return yaml.safe_load(f)

# ─── Data fetching ─────────────────────────────────────────────
def fetch_nifty_data(hist, days=200, end_date=None):
    """Fetch Nifty 50 index data."""
    from jugaad_data.nse import NSEIndexHistory
    if end_date is None:
        end_date = date.today()
    start_date = end_date - timedelta(days=days + 30)
    
    try:
        raw = hist.index_raw('NIFTY 50', from_date=start_date, to_date=end_date)
        df = pd.DataFrame(raw)
        df['date'] = pd.to_datetime(df['HistoricalDate'], format='%d %b %Y').dt.tz_localize(None)
        df = df.sort_values('date').reset_index(drop=True)
        df['close'] = pd.to_numeric(df['CLOSE'], errors='coerce')
        df['sma_20'] = df['close'].rolling(20).mean()
        return df
    except Exception as e:
        logger.error(f"Failed to fetch Nifty data: {e}")
        return pd.DataFrame()

def fetch_stock_data(hist, symbol, days=200, end_date=None):
    """Fetch historical data for a single stock."""
    from jugaad_data.nse import NSEHistory
    if end_date is None:
        end_date = date.today()
    start_date = end_date - timedelta(days=days + 30)
    
    try:
        raw = hist.stock_raw(symbol, from_date=start_date, to_date=end_date)
        if not raw or len(raw) < 30:
            return None
        df = pd.DataFrame(raw)
        df['date'] = pd.to_datetime(df['CH_TIMESTAMP']).dt.tz_localize(None)
        df = df.sort_values('date').reset_index(drop=True)
        
        df['close'] = pd.to_numeric(df['CH_CLOSING_PRICE'], errors='coerce')
        df['open'] = pd.to_numeric(df['CH_OPENING_PRICE'], errors='coerce')
        df['high'] = pd.to_numeric(df['CH_TRADE_HIGH_PRICE'], errors='coerce')
        df['low'] = pd.to_numeric(df['CH_TRADE_LOW_PRICE'], errors='coerce')
        df['volume'] = pd.to_numeric(df['CH_TOT_TRADED_QTY'], errors='coerce')
        df['prev_close'] = pd.to_numeric(df['CH_PREVIOUS_CLS_PRICE'], errors='coerce')
        
        return df
    except Exception as e:
        logger.warning(f"Failed to fetch {symbol}: {e}")
        return None

def compute_indicators(df):
    """Compute all technical indicators for a stock dataframe."""
    df = df.copy()
    
    # SMAs
    for period in [5, 10, 20, 50]:
        df[f'sma_{period}'] = df['close'].rolling(period).mean()
    
    # RSI (14)
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    df['rsi_14'] = 100 - (100 / (1 + gain / loss.replace(0, np.nan)))
    
    # Bollinger Bands (20, 2)
    df['bb_mid'] = df['close'].rolling(20).mean()
    bb_std = df['close'].rolling(20).std()
    df['bb_upper'] = df['bb_mid'] + 2 * bb_std
    df['bb_lower'] = df['bb_mid'] - 2 * bb_std
    
    # Lookback (shifted to exclude current day)
    df['low_20d_prev'] = df['low'].rolling(20).min().shift(1)
    df['high_20d_prev'] = df['high'].rolling(20).max().shift(1)
    
    # ATR
    tr = pd.concat([
        df['high'] - df['low'],
        abs(df['high'] - df['close'].shift(1)),
        abs(df['low'] - df['close'].shift(1))
    ], axis=1).max(axis=1)
    df['atr_14'] = tr.rolling(14).mean()
    
    # Volume average
    df['avg_vol_20'] = df['volume'].rolling(20).mean()
    
    return df

# ─── Strategy: BB Mid Reclaim (Long) ──────────────────────────
def check_bb_reclaim_long(df, nifty_row, prev_nifty_row):
    """Check for BB Mid Reclaim long signal."""
    if df is None or len(df) < 21:
        return None
    
    last = df.iloc[-1]
    prev = df.iloc[-2]
    
    # Check if we have valid indicator values
    if pd.isna(last['bb_mid']) or pd.isna(prev['bb_mid']) or pd.isna(last['sma_20']):
        return None
    
    # Nifty must be bullish
    nifty_bull = nifty_row['close'] > nifty_row['sma_20']
    if not nifty_bull:
        return None
    
    # Entry conditions
    bb_reclaim = (last['close'] > last['bb_mid'] * 1.003) and \
                 (prev['close'] <= prev['bb_mid'])
    
    if not bb_reclaim:
        return None
    
    # Compute trade parameters
    close_price = round(last['close'], 2)
    sl_price = round(close_price * 0.965, 2)  # 3.5% SL
    sl_pct = round((close_price - sl_price) / close_price * 100, 2)
    
    return {
        'type': 'LONG',
        'strategy': 'BB Mid Reclaim',
        'stock': df.attrs.get('symbol', 'UNKNOWN'),
        'date': last['date'].strftime('%Y-%m-%d'),
        'close': close_price,
        'entry_zone_low': round(close_price * 0.995, 2),
        'entry_zone_high': round(close_price, 2),
        'stop_loss': sl_price,
        'stop_loss_pct': sl_pct,
        'rsi': round(last['rsi_14'], 1),
        'bb_mid': round(last['bb_mid'], 2),
        'bb_reclaim_pct': round((last['close'] / last['bb_mid'] - 1) * 100, 2),
        'volume': round(last['volume'] / 1e6, 1),
        'volume_ratio': round(last['volume'] / last['avg_vol_20'], 2) if pd.notna(last['avg_vol_20']) and last['avg_vol_20'] > 0 else 0,
        'nifty_close': round(nifty_row['close'], 2),
        'nifty_sma20': round(nifty_row['sma_20'], 2),
        'nifty_regime': 'BULLISH' if nifty_bull else 'BEARISH',
        'rationale': f"Close {close_price} reclaimed BB middle {round(last['bb_mid'],2)} by +{round((last['close']/last['bb_mid']-1)*100,2)}% after testing below. RSI at {round(last['rsi_14'],1)}. Nifty bullish ({round(nifty_row['close'],0)} vs 20DMA {round(nifty_row['sma_20'],0)}).",
        # Beginner-friendly instructions
        'beginner_instruction': f"This looks like a BUY setup. {df.attrs.get('symbol', 'UNKNOWN')} price went above its 20-day average of Rs.{round(last['bb_mid'],2):,.2f}. If you want to act on this:",
        'beginner_entry': f"  1. On Kite: Search '{df.attrs.get('symbol', 'UNKNOWN')}' → Click BUY → Select Product: MIS (Intraday) → Enter price: Rs.{close_price:,.2f} (market) or Rs.{round(close_price*0.98,2):,.2f} (limit) → Quantity: decide based on your capital → Place order",
        'beginner_sl': f"  2. Stop Loss (safety net): Set a STOP LOSS order at Rs.{sl_price:,.2f}. If price falls to this level, your position closes automatically — limiting your loss to about 3.5%.",
        'beginner_exit': f"  3. Exit: Watch the chart. If price falls below Rs.{round(last['bb_mid'],2):,.2f} (the average it crossed above), consider exiting. Or if the RSI line (wavy line at bottom of chart) goes above 70, consider exiting."
    }

# ─── Strategy: 20-Day Low Breakdown (Short) ────────────────────
def check_breakdown_short(df, nifty_row):
    """Check for 20-Day Low Breakdown short signal."""
    if df is None or len(df) < 21:
        return None
    
    last = df.iloc[-1]
    prev = df.iloc[-2]
    
    if pd.isna(last['low_20d_prev']):
        return None
    
    # Nifty must be bearish
    nifty_bear = nifty_row['close'] < nifty_row['sma_20']
    if not nifty_bear:
        return None
    
    # Entry conditions
    breakdown = (last['close'] < last['low_20d_prev']) and \
                (prev['close'] >= prev['low_20d_prev'])
    
    if not breakdown:
        return None
    
    close_price = round(last['close'], 2)
    sl_price = round(close_price * 1.035, 2)  # 3.5% SL
    sl_pct = round((sl_price - close_price) / close_price * 100, 2)
    
    return {
        'type': 'SHORT',
        'strategy': '20D Low Breakdown',
        'stock': df.attrs.get('symbol', 'UNKNOWN'),
        'date': last['date'].strftime('%Y-%m-%d'),
        'close': close_price,
        'entry_zone_low': round(close_price * 0.997, 2),
        'entry_zone_high': round(close_price, 2),
        'stop_loss': sl_price,
        'stop_loss_pct': sl_pct,
        'rsi': round(last['rsi_14'], 1),
        'low_20d': round(last['low_20d_prev'], 2),
        'distance_from_low': round((last['low_20d_prev'] - last['close']) / last['low_20d_prev'] * 100, 2),
        'volume': round(last['volume'] / 1e6, 1),
        'volume_ratio': round(last['volume'] / last['avg_vol_20'], 2) if pd.notna(last['avg_vol_20']) and last['avg_vol_20'] > 0 else 0,
        'nifty_close': round(nifty_row['close'], 2),
        'nifty_sma20': round(nifty_row['sma_20'], 2),
        'nifty_regime': 'BEARISH' if nifty_bear else 'BULLISH',
        'rationale': f"Close {close_price} broke below 20-day low {round(last['low_20d_prev'],2)} (distance: -{round((last['low_20d_prev']-last['close'])/last['low_20d_prev']*100,2)}%). RSI at {round(last['rsi_14'],1)}. Nifty bearish ({round(nifty_row['close'],0)} vs 20DMA {round(nifty_row['sma_20'],0)})."
    }

def _serialize(obj):
    """Convert numpy types to JSON-serializable Python types."""
    import numpy as np
    if isinstance(obj, (np.integer,)):
        return int(obj)
    elif isinstance(obj, (np.floating,)):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    return obj

def _clean_for_json(data):
    """Recursively clean a data structure for JSON serialization."""
    if isinstance(data, dict):
        return {k: _clean_for_json(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [_clean_for_json(v) for v in data]
    elif isinstance(data, tuple):
        return tuple(_clean_for_json(v) for v in data)
    else:
        return _serialize(data) if data is not None else None

# ─── Main scan ─────────────────────────────────────────────────
def run_daily_scan(target_date=None):
    """
    Run the daily signal scan.
    
    Args:
        target_date: The date to scan (date object or 'YYYY-MM-DD' string).
                     If None, scans today's latest available data.
                     Useful for scanning yesterday's data if today's isn't available yet.
    """
    logger.info("="*60)
    logger.info("STOCK ANALYZER — DAILY SIGNAL SCAN")
    
    # Parse target date
    if target_date is None:
        # Default: scan yesterday's data (previous day's close)
        # This is what you run at 9 AM to get signals for today
        scan_date = date.today() - timedelta(days=1)
    elif isinstance(target_date, str):
        scan_date = datetime.strptime(target_date, '%Y-%m-%d').date()
    else:
        scan_date = target_date
    
    logger.info(f"Scan date: {scan_date.strftime('%Y-%m-%d')}")
    logger.info(f"Today: {date.today().strftime('%Y-%m-%d')}")
    logger.info("="*60)
    
    config = load_config()
    watchlist = config.get('watchlist', {}).get('stocks', [])
    strategies_config = config.get('strategies', {})
    
    # Initialize data fetchers
    from jugaad_data.nse import NSEHistory, NSEIndexHistory
    hist = NSEHistory()
    ihist = NSEIndexHistory()
    
    # Fetch Nifty data (up to scan_date)
    logger.info(f"Fetching Nifty 50 data (up to {scan_date.strftime('%Y-%m-%d')})...")
    nifty_df = fetch_nifty_data(ihist, days=200, end_date=scan_date)
    if nifty_df.empty:
        logger.error("Could not fetch Nifty data. Aborting.")
        return None
    
    latest_nifty = nifty_df.iloc[-1]
    prev_nifty = nifty_df.iloc[-2]
    
    nifty_bull = latest_nifty['close'] > latest_nifty['sma_20']
    nifty_regime = 'BULLISH' if nifty_bull else 'BEARISH'
    
    logger.info(f"Nifty: {latest_nifty['close']:.2f} | 20 SMA: {latest_nifty['sma_20']:.2f} | Regime: {nifty_regime}")
    
    # Scan all stocks
    all_signals = []
    stock_status = []
    
    for symbol in watchlist:
        logger.info(f"Scanning {symbol}...")
        
        df = fetch_stock_data(hist, symbol, days=200, end_date=scan_date)
        if df is None:
            stock_status.append({'stock': symbol, 'status': 'NO DATA', 'close': None, 'rsi': None})
            continue
        
        df = compute_indicators(df)
        df.attrs['symbol'] = symbol
        
        last = df.iloc[-1]
        prev = df.iloc[-2]
        
        # Default status
        status = {
            'stock': symbol,
            'close': round(last['close'], 2) if pd.notna(last['close']) else None,
            'rsi': round(last['rsi_14'], 1) if pd.notna(last['rsi_14']) else None,
            'status': 'no signal',
            'details': ''
        }
        
        # Check BB Reclaim (Long)
        if strategies_config.get('bb_reclaim_long', {}).get('enabled', True):
            bb_signal = check_bb_reclaim_long(df, latest_nifty, prev_nifty)
            if bb_signal:
                all_signals.append(bb_signal)
                status['status'] = 'SIGNAL (LONG)'
                status['details'] = f"BB reclaim +{bb_signal['bb_reclaim_pct']}%"
        
        # Check Breakdown (Short)
        if strategies_config.get('breakdown_short', {}).get('enabled', True):
            bd_signal = check_breakdown_short(df, latest_nifty)
            if bd_signal:
                all_signals.append(bd_signal)
                status['status'] = 'SIGNAL (SHORT)'
                status['details'] = f"20D breakdown ({bd_signal['distance_from_low']}% below)"
        
        # Add status info
        bb_pos = (last['close'] / last['bb_mid'] - 1) * 100 if pd.notna(last['bb_mid']) else None
        status['bb_position'] = round(bb_pos, 1) if bb_pos is not None else None
        status['low_20d'] = round(last['low_20d_prev'], 2) if pd.notna(last['low_20d_prev']) else None
        status['volume'] = round(last['volume'] / 1e6, 1) if pd.notna(last['volume']) else None
        
        stock_status.append(status)
        logger.info(f"  {symbol}: {status['status']} | C={status['close']} RSI={status['rsi']} BB={status['bb_position']}%")
    
    # Build report
    scan_date_str = scan_date.strftime('%Y-%m-%d')
    today_str = date.today().strftime('%Y-%m-%d')
    report = {
        'scan_date': scan_date_str,
        'data_as_of': scan_date_str,
        'today': today_str,
        'timestamp': datetime.now().isoformat(),
        'nifty': {
            'close': round(latest_nifty['close'], 2),
            'sma_20': round(latest_nifty['sma_20'], 2),
            'regime': nifty_regime,
            'change_from_prev': round(latest_nifty['close'] - prev_nifty['close'], 2),
            'change_pct': round((latest_nifty['close'] / prev_nifty['close'] - 1) * 100, 2),
        },
        'signals': all_signals,
        'signal_count': len(all_signals),
        'watchlist_status': stock_status,
        'strategies_checked': [
            'BB Mid Reclaim (Long)' if strategies_config.get('bb_reclaim_long', {}).get('enabled') else 'BB Mid Reclaim (DISABLED)',
            '20D Low Breakdown (Short)' if strategies_config.get('breakdown_short', {}).get('enabled') else '20D Low Breakdown (DISABLED)',
        ],
        'disclaimer': 'Signals are for informational purposes only. Always confirm on your trading platform before executing. Past performance does not guarantee future results.'
    }
    
    # Write signal file (use scan date in filename for historical scans)
    signal_file = SIGNALS_DIR / f"signals_{scan_date_str}.json"
    with open(signal_file, 'w', encoding='utf-8') as f:
        json.dump(_clean_for_json(report), f, indent=2, ensure_ascii=False)
    
    logger.info("")
    logger.info("="*60)
    logger.info(f"SCAN COMPLETE ({scan_date_str}) — {len(all_signals)} signal(s) found")
    logger.info(f"Signals saved to: {signal_file}")
    logger.info("="*60)
    
    # Print summary
    print("\n" + "="*60)
    if scan_date != date.today():
        print(f"📊 SIGNAL SUMMARY — {scan_date_str} (historical scan, today is {today_str})")
    else:
        print(f"📊 SIGNAL SUMMARY — {scan_date_str}")
    print("="*60)
    print(f"Nifty: {report['nifty']['close']:.2f} | 20 SMA: {report['nifty']['sma_20']:.2f} | Regime: {report['nifty']['regime']}")
    print(f"Previous close: {prev_nifty['close']:.2f} | Change: {report['nifty']['change_from_prev']:+.2f} ({report['nifty']['change_pct']:+.2f}%)")
    print()
    
    if all_signals:
        for sig in all_signals:
            print(f"\n{'─'*55}")
            print(f"  {sig['type']} — {sig['stock']} ({sig['strategy']})")
            print(f"  Close: Rs.{sig['close']}")
            print(f"  Entry zone: Rs.{sig['entry_zone_low']} - Rs.{sig['entry_zone_high']}")
            print(f"  Stop Loss: Rs.{sig['stop_loss']} ({sig['stop_loss_pct']}%)")
            print(f"  RSI(14): {sig['rsi']}")
            if sig['type'] == 'LONG':
                print(f"  BB Reclaim: +{sig['bb_reclaim_pct']}% from 20SMA ({sig['bb_mid']})")
                print(f"  Volume: {sig['volume']}M (ratio: {sig['volume_ratio']}x)")
            else:
                print(f"  20-Day Low: Rs.{sig['low_20d']} (distance: -{sig['distance_from_low']}%)")
                print(f"  Volume: {sig['volume']}M (ratio: {sig['volume_ratio']}x)")
            print(f"  Exit: When RSI crosses {'above 55' if sig['type']=='LONG' else 'below 45'}")
            print(f"  Rationale: {sig['rationale']}")
    else:
        print("\n  No signals for this date.")
        print()
        print("  What to watch today:")
        if not nifty_bull:
            print("  • Market is BEARISH — watch for stocks breaking 20-day lows")
            print("  • Look for RSI < 30 stocks near breakdown levels")
        else:
            print("  • Market is BULLISH — watch for BB reclaim setups")
            print("  • Look for RSI < 40 stocks recovering above 20 SMA")
        print()
        if scan_date < date.today():
            print(f"  Note: Scanning {scan_date_str} data (previous day).")
            print(f"  Today is {today_str}. Use --date to scan a different date.")
        else:
            print("  Check Nifty at 9:15 AM. If regime flips (Nifty crosses 20 SMA),")
            print("  strategies switch direction accordingly.")
    
    print(f"\nFull report: {signal_file}")
    print("="*60)
    
    return report

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Stock Analyzer — Daily Signal Scanner')
    parser.add_argument('--date', type=str, default=None,
                        help='Date to scan (YYYY-MM-DD). If not provided, scans today\'s latest data.')
    args = parser.parse_args()
    
    if args.date:
        print(f"\nScanning data as of: {args.date}")
        print(f"(Today is: {date.today().strftime('%Y-%m-%d')})")
        print()
    
    run_daily_scan(target_date=args.date)
