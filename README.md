# Stock Analyzer

A systematic trading signal pipeline for Indian equities. Scans stocks for setups, outputs clear buy/sell recommendations, and scales to multiple strategies.

## Project Structure

```
D:/OpenCode/Stock/Stock Analyzer/
├── config.yaml            # Global config: watchlist, strategies, risk, schedule
├── scan_daily.py          # Main daily signal scanner
├── scan_intraday.py       # (To be built) Intraday monitoring script
├── dashboard.py           # (To be built) HTML dashboard
├── signals/               # Signal output files (signals_YYYYMMDD.json)
├── data/                  # Cached historical data (optional)
├── logs/                  # Scan logs
└── README.md              # This file
```

## Quick Start

```bash
cd "D:/OpenCode/Stock/Stock Analyzer"
python scan_daily.py
```

This scans all watchlist stocks, detects signals, and writes `signals/signals_YYYYMMDD.json`.

## Configuration

Edit `config.yaml` to change:

- **Watchlist**: Add/remove stocks under `watchlist.stocks`
- **Strategies**: Toggle strategies on/off under `strategies`
- **Risk parameters**: Adjust under `risk`
- **Schedule**: Set scan times under `schedule`

## Signal Types

### BB Mid Reclaim (LONG)
- Condition: Close crosses above 20 SMA after testing below it
- Market regime: Nifty must be above 20 SMA (bullish)
- Exit: When RSI(14) crosses above 55
- Stop Loss: 3.5% below entry (or 1.5x ATR if wider)

### 20-Day Low Breakdown (SHORT)
- Condition: Close breaks below lowest low of past 20 days
- Market regime: Nifty must be below 20 SMA (bearish)
- Exit: When RSI(14) crosses below 45
- Stop Loss: 3.5% above entry

## Roadmap

1. **Now**: Daily scanner working. Paper trade signals.
2. **Next**: Intraday monitor script + HTML dashboard.
3. **Later**: Scheduler (Windows Task Scheduler), notifications, more strategies, backtesting framework.

## Important Notes

- Signals are based on EOD data (previous day's close). For intraday, check the latest price.
- Always confirm on your trading platform (Kite) before executing.
- Paper trade first. Do not go live until you have a proven track record.
- Past performance does not guarantee future results.
