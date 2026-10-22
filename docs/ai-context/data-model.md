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

### Canonical Dashboard Signal Schema

`dashboard.py` `normalize_signal(sig)` converts every legacy shape into this form before it reaches `state.active_signals`:

| Field | Source (fallback order) | Notes |
|-------|--------------------------|-------|
| `symbol` | `symbol` → `stock` | Required; signals without it are dropped |
| `entry` | `entry` → `entry_price` | Required; signals without it are dropped |
| `sl` | `sl` → `sl_price` | |
| `target` | `target` → `target_price` | |
| `timestamp` | `timestamp` → `time` → `fired_at` | |
| `type` | `type` → `signal_type` | Contains "SHORT" → `short`; contains "LONG" → `long`; default `short` |
| `strategy` | `strategy` | Legacy names mapped: `"20D Low Breakdown"` → `short_20d_low_breakdown`, `"BB Mid Reclaim"` → `long_bb_reclaim` |
| `charges` | `charges` | Dict; `total` added from `estimated_total` when missing |

`state.active_signals` is a list of these dicts. The frontend's Live Signals table and `chart_data_for` depend on these exact field names.

### Option Signal Fields (Phase 2)

Option strategies add these fields to the canonical shape:

| Field | Meaning |
|-------|---------|
| `strike` | Strike price of the reference leg (long leg for spreads, ATM for straddle) |
| `expiry` | Expiry date (`YYYY-MM-DD`, ISO) |
| `legs` | List of legs — each `{symbol, side, strike, ltp, qty, iv, oi, volume}` (`side` ∈ `buy`/`sell`) |
| `priority_score` | Ranking score (see Priority Scoring) |
| `signal_time` | IST timestamp the signal fired |
| `status` | `active` / `expired` / `squared` / `executed` |
| `market_regime` | `bullish` / `bearish` / `neutral` / `unknown` |
| `iv_rank` | Percentile rank of implied volatility (0–100) |
| `lots` | Number of option lots traded (1 lot = 25 qty for NIFTY) |
| `nifty_range_15m` | Nifty high-low range over the last 15 min at signal time |
| `valid_until` | Latest time the signal remains actionable (from the `validity` config windows) |
| `max_loss_amount` | Rupee risk if the trade goes to SL |
| `risk_exceeded` | `true` when even 1 lot exceeds the configured risk budget |
| `description` | Human-readable leg summary |

The `symbol` field is `"{index}-{expiry}-{strike}"` (e.g. `NIFTY-2026-10-27-24200`), while each leg's `symbol` is the broker-style instrument name (e.g. `NIFTY27-Oct-202624200CE`).

Leg schema, as emitted by `dashboard.py`:

```json
{
  "symbol": "NIFTY27-Oct-202624200CE",
  "side": "buy",
  "strike": 24200,
  "ltp": 166.67,
  "qty": 25,
  "iv": 14.0,
  "oi": 1024,
  "volume": 524
}
```

Signals are keyed by `{strategy}_{symbol}` in `signals/signals_live_YYYYMMDD.json`.

## Priority Scoring

```
priority_score = signal_strength + time_of_day_bonus + strategy_weight + volatility_bonus
```

| Component | Rule | Value |
|-----------|------|-------|
| Signal strength | IV Rank > 70% / 25–70% / < 25% | +15 / +10 / +5 |
| Time of day | 9:30–11:00 / 11:00–12:30 / 12:30–14:30 / 14:30–15:00 | +10 / +5 / 0 / −5 |
| Strategy weight | Bull Call Spread, Straddle / Bull Put Spread, 20D Low Breakdown, Strangle / ORB / BB Mid Reclaim / Iron Condor | 15 / 12 / 10 / 8 / 6 |
| Volatility bonus | Nifty 15-min range > 60 pts / 30–60 / < 30 | +10 / +5 / −5 |

Thursday applies a further 40% reduction to the score (square-off day). Friday signals must be triggered by 14:00; signals from 14:30–15:00 must be triggered by 14:50.

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