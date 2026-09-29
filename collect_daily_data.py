#!/usr/bin/env python3
"""
Collect daily OHLCV data for the last N days for all watchlist stocks.
Uses jugaad-data's daily historical data (free, no API key).
Output: data/daily/YYYY-MM-DD.jsonl (one record per stock per day)
"""

import os
import sys
import json
import logging
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

PROJECT_DIR = Path(r"D:\OpenCode\Stock\Stock Analyzer")
CONFIG_FILE = PROJECT_DIR / "config.yaml"
DATA_DIR = PROJECT_DIR / "data" / "daily"
LOG_DIR = PROJECT_DIR / "logs"

for d in [DATA_DIR, LOG_DIR]:
    d.mkdir(parents=True, exist_ok=True)

log_file = LOG_DIR / f"collect_daily_{date.today().strftime('%Y%m%d')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger(__name__)


def load_config():
    import yaml
    with open(CONFIG_FILE, "r") as f:
        return yaml.safe_load(f)


def main():
    cfg = load_config()
    watchlist = cfg.get('watchlist', {}).get('stocks', [])
    days_back = 30
    end_date = date.today() - timedelta(days=1)  # up to yesterday
    start_date = end_date - timedelta(days=days_back + 5)

    logger.info(f"Collecting daily data for {len(watchlist)} stocks")
    logger.info(f"Period: {start_date} to {end_date} ({days_back} days)")

    from jugaad_data.nse import NSEHistory
    hist = NSEHistory()

    for symbol in watchlist:
        logger.info(f"  Fetching {symbol}...")
        try:
            raw = hist.stock_raw(symbol, from_date=start_date, to_date=end_date)
            if not raw:
                logger.warning(f"  {symbol}: no data returned")
                continue

            df = pd.DataFrame(raw)
            df['date'] = pd.to_datetime(df['HistoricalDate'], format='%d %b %Y').dt.tz_localize(None)
            df = df.sort_values('date')

            for _, row in df.iterrows():
                record = {
                    "date": row['date'].strftime('%Y-%m-%d'),
                    "symbol": symbol,
                    "open": float(row['CH_OPENING_PRICE']) if pd.notna(row['CH_OPENING_PRICE']) else None,
                    "high": float(row['CH_TRADE_HIGH_PRICE']) if pd.notna(row['CH_TRADE_HIGH_PRICE']) else None,
                    "low": float(row['CH_TRADE_LOW_PRICE']) if pd.notna(row['CH_TRADE_LOW_PRICE']) else None,
                    "close": float(row['CH_CLOSING_PRICE']) if pd.notna(row['CH_CLOSING_PRICE']) else None,
                    "volume": float(row['CH_TOT_TRADED_QTY']) if pd.notna(row['CH_TOT_TRADED_QTY']) else None,
                    "prev_close": float(row['CH_PREVIOUS_CLS_PRICE']) if pd.notna(row['CH_PREVIOUS_CLS_PRICE']) else None,
                    "wavg": float(row['WAP']) if pd.notna(row['WAP']) else None,
                }
                # Append to daily data file
                daily_file = DATA_DIR / "daily_data.jsonl"
                with open(daily_file, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")

            logger.info(f"  {symbol}: {len(df)} days fetched")

        except Exception as e:
            logger.error(f"  {symbol}: ERROR - {e}")

    logger.info("Done.")


if __name__ == '__main__':
    main()
