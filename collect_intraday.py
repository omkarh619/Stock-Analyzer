#!/usr/bin/env python3
"""
Stock Analyzer — Intraday Data Collector
Polls every 1 minute during market hours and stores a snapshot per stock.
Data is stored as JSONL (one line per stock per minute) in data/intraday/.
Retention: 30 days (old files auto-deleted on startup).
"""

import os
import sys
import json
import time as _time_module
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

PROJECT_DIR = Path(r"D:\OpenCode\Stock\Stock Analyzer")
CONFIG_FILE = PROJECT_DIR / "config.yaml"
DATA_DIR = PROJECT_DIR / "data" / "intraday"
LOG_DIR = PROJECT_DIR / "logs"

for d in [DATA_DIR, LOG_DIR]:
    d.mkdir(parents=True, exist_ok=True)

log_file = LOG_DIR / f"collector_{date.today().strftime('%Y%m%d')}.log"
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
POLL_INTERVAL_SEC = 60  # 1 minute
RETENTION_DAYS = 30
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MIN = 15
MARKET_CLOSE_HOUR = 15
MARKET_CLOSE_MIN = 30

today_str = date.today().strftime('%Y-%m-%d')
data_file = DATA_DIR / f"{today_str}.jsonl"


# ─── Cleanup old data ────────────────────────────────────────
def cleanup_old_data():
    """Remove intraday data files older than RETENTION_DAYS."""
    cutoff = date.today() - timedelta(days=RETENTION_DAYS)
    removed = 0
    for f in DATA_DIR.glob("*.jsonl"):
        try:
            file_date = datetime.strptime(f.stem, "%Y-%m-%d").date()
            if file_date < cutoff:
                f.unlink()
                removed += 1
                logger.info(f"Cleaned up old data: {f.name}")
        except:
            pass
    if removed:
        logger.info(f"Cleanup: removed {removed} file(s) older than {RETENTION_DAYS} days")


# ─── Load today's existing data to restore tracking ──────────
def load_existing_tracking():
    """Load today's existing JSONL to restore running high/low per symbol."""
    tracking = {}
    if not data_file.exists():
        return tracking
    try:
        with open(data_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    sym = rec.get('symbol', '')
                    ltp = rec.get('ltp')
                    if sym and ltp is not None:
                        if sym not in tracking:
                            tracking[sym] = {'high': ltp, 'low': ltp}
                        else:
                            tracking[sym]['high'] = max(tracking[sym]['high'], ltp)
                            tracking[sym]['low'] = min(tracking[sym]['low'], ltp)
                except:
                    pass
    except:
        pass
    return tracking


# ─── Fetch helpers ───────────────────────────────────────────
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
    except:
        return None


# ─── Get yesterday's close for gap calculation ───────────────
def get_prev_close(hist, symbol):
    """Get yesterday's closing price for gap calculation."""
    from jugaad_data.nse import NSEHistory
    end_date = date.today() - timedelta(days=1)
    start_date = end_date - timedelta(days=10)
    try:
        raw = hist.stock_raw(symbol, from_date=start_date, to_date=end_date)
        if raw and len(raw) > 0:
            df = pd.DataFrame(raw)
            df['date'] = pd.to_datetime(df['CH_TIMESTAMP']).dt.tz_localize(None)
            df = df.sort_values('date')
            return float(df.iloc[-1]['CH_CLOSING_PRICE'])
    except:
        pass
    return None


# ─── Main collector loop ─────────────────────────────────────
def run_collector():
    from jugaad_data.nse import NSELive, NSEHistory
    nlive = NSELive()
    hist = NSEHistory()

    # Restore tracking from existing file (if restarted mid-day)
    tracking = load_existing_tracking()
    logger.info(f"Tracking restored: {len(tracking)} symbols from existing data")

    # Get previous close for gap calc (do once)
    prev_closes = {}
    for sym in WATCHLIST:
        prev_closes[sym] = get_prev_close(hist, sym)

    # Market close time today
    now = datetime.now()
    market_close = now.replace(hour=MARKET_CLOSE_HOUR, minute=MARKET_CLOSE_MIN, second=0, microsecond=0)
    if now >= market_close:
        logger.info("Market already closed. Nothing to collect.")
        print("Market already closed. Nothing to collect today.")
        return

    samples_collected = 0

    logger.info("=" * 55)
    logger.info("INTRADAY DATA COLLECTOR — 1-min intervals")
    logger.info(f"Started: {now.strftime('%H:%M:%S')} | File: {data_file.name}")
    logger.info(f"Stocks: {len(WATCHLIST)} | Retention: {RETENTION_DAYS} days")
    logger.info("=" * 55)

    print()
    print("╔" + "═" * 53 + "╗")
    print("║  INTRADAY DATA COLLECTOR — Ctrl+C to stop          ║")
    print("╚" + "═" * 53 + "╝")
    print(f"  Collecting 1-min snapshots → {data_file}")
    print(f"  Market close: {MARKET_CLOSE_HOUR:02d}:{MARKET_CLOSE_MIN:02d} IST")
    print()

    try:
        while True:
            now = datetime.now()

            # Check market close
            if now >= market_close:
                print("\n⏹ Market closed. Collection stopped.")
                logger.info("Market closed. Collection stopped.")
                break

            # Fetch Nifty once per cycle
            nifty_ltp = fetch_live_nifty(nlive)

            # Fetch all stocks
            records = []
            for symbol in WATCHLIST:
                ltp = fetch_live_price(nlive, symbol)
                if ltp is not None:
                    # Update running high/low
                    if symbol not in tracking:
                        tracking[symbol] = {'high': ltp, 'low': ltp}
                    else:
                        tracking[symbol]['high'] = max(tracking[symbol]['high'], ltp)
                        tracking[symbol]['low'] = min(tracking[symbol]['low'], ltp)

                    record = {
                        "ts": now.strftime('%Y-%m-%dT%H:%M:%S+05:30'),
                        "symbol": symbol,
                        "ltp": round(ltp, 2),
                        "intraday_high": round(tracking[symbol]['high'], 2),
                        "intraday_low": round(tracking[symbol]['low'], 2),
                        "nifty_ltp": round(nifty_ltp, 2) if nifty_ltp else None,
                        "prev_close": prev_closes.get(symbol),
                    }
                    records.append(record)

            # Append to file
            if records:
                with open(data_file, 'a', encoding='utf-8') as f:
                    for rec in records:
                        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                samples_collected += len(records)

            # Compact status line
            ts_str = now.strftime('%H:%M:%S')
            live_count = len([r for r in records if r['ltp'] is not None])
            nifty_str = f"Nifty:{nifty_ltp:,.0f}" if nifty_ltp else "Nifty:N/A"
            print(f"  [{ts_str}] {nifty_str} | {live_count}/{len(WATCHLIST)} stocks | Total samples: {samples_collected}")
            sys.stdout.flush()

            logger.debug(f"Collected {len(records)} records at {ts_str}")

            _time_module.sleep(POLL_INTERVAL_SEC)

    except KeyboardInterrupt:
        logger.info("Collection stopped by user.")
        print("\n⏹ Collection stopped by user.")
    except Exception as e:
        logger.error(f"Collection error: {e}")
        print(f"\n Error: {e}")

    # Final summary
    print()
    print("=" * 55)
    print(f"  COLLECTION FINISHED")
    print(f"  File: {data_file}")
    print(f"  Total samples: {samples_collected}")
    print(f"  Stocks tracked: {len(tracking)}")
    print(f"  Data points today: {samples_collected}")
    print("=" * 55)

    # Cleanup old data on exit
    cleanup_old_data()


if __name__ == '__main__':
    print("\n Collecting intraday data every 1 minute.")
    print(" Press Ctrl+C to stop. Data saved to data/intraday/YYYY-MM-DD.jsonl")
    print()
    run_collector()
