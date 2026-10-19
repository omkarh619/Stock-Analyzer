# Data Model

## Overview

The system uses **flat-file persistence** — no database. All data is JSON or JSONL. This document describes the structures you'll read and write.

## File Inventories (by date convention)

| Path Pattern | Format | Writer | Reader |
|--------------|--------|--------|--------|
| `signals/signals_YYYY-MM-DD.json` | JSON | `scan_daily.py` | `analyze_eod.py` |
| `signals/signals_live_YYYYMMDD.json` | JSON | `intraday.py` | `analyze_eod.py`, `dashboard.py` |
| `data/intraday/YYYY-MM-DD.jsonl` | JSONL | `intraday.py` | `analyze_eod.py` |
| `signal_states/states_YYYYMMDD.json` | JSON | `dashboard.py` | Human/AI review |
| `reports/analysis_YYYYMMDD.json` | JSON | `analyze_eod.py` | Human/AI review |
| `reports/ai_summary_YYYYMMDD.json` | JSON | `analyze_eod.py` | AI review |

## Signal Schema (signals/signals_YYYY-MM-DD.json)

Example structure (from README):

```json
{
  "date": "2026-09-25",
  "nifty_regime": "BULLISH|BEARISH",
  "signals": [
    {
      "type": "SHORT (intraday)",
      "strategy": "20D Low Breakdown",
      "stock": "RELIANCE",
      "time": "10:30:00",
      "entry_price": 1220.90,
      "sl_price": 1263.63,
      "target_price": 1190.38,
      "target_pct": 2.5,
      "sl_pct": 3.5,
      "condition": "human-readable trigger description",
      "beginner_instruction": "...",
      "beginner_entry": "...",
      "beginner_sl": "...",
      "beginner_exit": "...",
      "charges": {
        "broker": "Zerodha (intraday MIS)",
        "estimated_total": 62.16,
        "breakdown": {"brokerage": 40, "gst": 7.2, "stt": 1.22, "exchange": 0.09, "sebi": 0.0, "stamp_duty": 0.18},
        "break_even_price": 1214.68,
        "estimated_quantity": 10,
        "estimated_trade_value": 12209.00
      }
    }
  ]
}
```

### Intraday signal additions

Live signals (`signals/signals_live_YYYYMMDD.json`) additionally include fields not in daily signals:

```json
{
  "type": "short",
  "strategy": "short_20d_low_breakdown",
  "symbol": "RELIANCE",
  "entry": 1219.70,
  "sl": 1262.39,
  "target": 1207.50,
  "sl_pct": 3.5,
  "target_pct": 2.5,
  "qty_est": 10,
  "gap_pct": -0.08,
  "breakdown_pct": 0.36,
  "stock_20d_low": 1226.40,
  "nifty_20d_low": null,
  "nifty_close": null,
  "nifty_sma20": null,
  "regime": "BEARISH",
  "timestamp": "10:30:00",
  "charges": { ... same as daily ... }
}
```

Key differences from daily signals: `type` uses short form ("short"/"long"), strategy uses config name (`short_20d_low_breakdown`), symbol replaces stock, and technical context fields (`stock_20d_low`, `nifty_close`, etc.) are included.

## Intraday Snapshot Schema (JSONL rows)

Each line in `data/intraday/YYYY-MM-DD.jsonl`:

```json
{"time": "2026-09-25 10:30:00", "nifty": 22438.0, "stocks": {"RELIANCE": {"time":..., "price": 1220.90, "high": ..., "low": ...}}}
```

**Note**: The live schema has evolved — field names `stocks.<SYMBOL>.time/price/high/low` may vary. Always inspect actual rows.

## SharedState Schema (signal_states/states_YYYYMMDD.json)

Full dashboard state dump. Key nested objects:

- `nifty`: `{symbol, price, sma20, regime, source}`
- `strategies`: per-strategy `{enabled, last_signal, signal_count, filters}`
- `stock_data`: map of `{symbol: {time, price, high, low}}`
- `price_history`: map of `{symbol: [{time, ltp, high, low}]}`
- `active_signals`: list of signal dicts (subset of above fields)
- `collector_*`: cycle timestamps, error counts, data sample counts

## EOD Report Schema (reports/analysis_YYYYMMDD.json)

Nested report produced by `analyze_eod.py`. Key sections:

- `analysis_date`, `generated_at`
- `market_summary`: nifty open/last/range/change, per-stock summary (first LTP, last LTP, range %, change %, gap %, samples)
- `signals_fired`: count
- `signal_results`: array with `stock, type, strategy, time_fired, entry, target, sl, outcome, final_ltp, pnl_pct, target_reached, sl_reached, day_high, day_low`
- `signal_stats`: counts for hit_target, hit_sl, reversed, open_at_close, no_data
- `yesterday_daily_signals`: yesterday's signals (for reference)

## Report Summary Schema (reports/ai_summary_YYYYMMDD.json)

Machine-readable subset for AI review:

```json
{
  "date": "YYYY-MM-DD",
  "market": {"nifty_change_pct": x, "nifty_close": y, "regime": "BULLISH|BEARISH"},
  "signals": [...per-signal P&L + outcome...],
  "stats": {"total": N, "hit_target": A, "hit_sl": B, "reversed": C, "open_at_close": D, "no_data": E},
  "yesterday_signals_count": N
}
```

## Charges Calculation (scan_daily.py / dashboard.py)

```python
brokerage = min(20, qty * price * 0.0003)        # ₹20 flat cap
stt          = qty * price * 0.001 if side == "sell" else 0
exchange     = qty * price * 0.0000325
stamp_duty   = qty * price * 0.00015
sebi        = qty * price * 0.00000001
gst         = (brokerage + exchange) * 0.18
total = brokerage + stt + exchange + stamp_duty + sebi + gst
```

Reference files:
- `scan_daily.py` `calculate_charges()` at line 87
- `dashboard.py` `calculate_charges()` at line 380

## Watchlist Schema (config.yaml → watchlist.stocks)

16 liquid Nifty 50 stocks, listed alphabetically:

`RELIANCE`, `HDFCBANK`, `ICICIBANK`, `SBIN`, `BHARTIARTL`, `KOTAKBANK`, `LT`, `MARUTI`, `NTPC`, `WIPRO`, `TATASTEEL`, `TITAN`, `HCLTECH`, `INFY`, `TCS`, `ASIANPAINT`

## State / Outcome Enum

| Value | Meaning |
|-------|---------|
| `HIT_TARGET` | LTP reached target level |
| `HIT_SL` | LTP reached stop loss level |
| `REVERSED` | Reversed beyond entry ( LONG: below entry; SHORT: above entry ) |
| `OPEN_AT_CLOSE` | Still open at last price in series |
| `no_data` | No intraday data for the symbol |
| `no_ltp_data` | Symbol present but no LTP values |