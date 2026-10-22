# Architecture

## Overview

A systematic trading-signal pipeline for Indian equities (Nifty 50 stocks). Not a trading platform — it scans for setups, generates buy/sell recommendations with entry/SL/target/charges, and collects data for continuous improvement.

**Runtime**: Python 3.9 (uses a virtualenv at `/d/Gradient/PyChecks_vevn39/Scripts/python`, documented in `README.md`).

## Major Components

```
┌─────────────┐   ┌──────────────┐   ┌──────────────┐   ┌───────────┐
│  Data Feeds  │   │  Scanners    │   │ Signal Store │   │ Analyzer  │
│  (NSE/yfin)  │──▶│  (Python)    │──▶│  (JSON/JSONL)│──▶│ (EOD)     │
└─────────────┘   └──────────────┘   └──────────────┘   └───────────┘
                              │                               │
                              ▼                               ▼
                      ┌──────────────┐             ┌──────────────────┐
                      │  Dashboard    │           │  Reports          │
                      │ (HTTP server) │           │ (analysis_*.json)  │
                      └──────────────┘           └──────────────────┘
```

## Execution Flows

### 1. Daily Morning Scan → Signals
```
scan_daily.py
  └─ reads yesterday's close (config.yaml history_days=200)
  └─ applies strategy filters (config.yaml → strategies.*)
  └─ computes RSI(14), SMA(20), Bollinger Bands, ATR(14)
  └─ writes signals/signals_YYYY-MM-DD.json
```

### 2. Intraday Monitoring (Market Hours 9:15–15:30 IST)
```
intraday.py (combined collector + signal generator)
  └─ polls every 1 minute during market hours
  └─ fetches LTP for all 16 stocks + Nifty (NSE API, yfinance fallback)
  └─ appends data/intraday/YYYY-MM-DD.jsonl (1-min snapshots)
  └─ checks intraday strategy filters each cycle
  └─ writes signals/signals_live_YYYYMMDD.json (deduplicated)
  └─ writes signal_states/states_YYYYMMDD.json (state tracking)
  └─ auto-stops at market close (15:30)
```

### 3. End-of-Day Analysis
```
analyze_eod.py (after market close)
  └─ reads data/intraday/YYYY-MM-DD.jsonl
  └─ reads signals/signals_live_YYYYMMDD.json
  └─ evaluates each signal: target hit / SL hit / reversed / open
  └─ computes paper P&L
  └─ writes reports/analysis_YYYYMMDD.json + reports/ai_summary_YYYYMMDD.json
```

### 4. Live Dashboard
```
dashboard.py
  └─ HTTP server on localhost:8899
  └─ serves dashboard.html (UI) + JSON API
  └─ collector thread reuses intraday.py patterns (NSE/yfinance data)
  └─ 3 live strategies: short_20d_low_breakdown, long_bb_reclaim, orb + 5 option strategies (bull_call, bull_put, iron_condor, straddle, strangle) — 8 total
  └─ option context per cycle: NSE option chain (15-min cache) + IV Rank + Nifty 15-min range → shared ctx for all 5 option checkers
  └─ real-time LTP, price history (200-bar), charts via SVG
```

## Boundaries

- **No database**: all persistence is flat-file (JSON, JSONL).
- **No auth**: local-only dashboard, no authentication.
- **No CI/CD**: no build pipeline, scheduler scripts, or deployment config.
- **Broker-agnostic output**: signals include Zerodha-specific instructions but charges are computed generically.

## Strategy Summary (from config.yaml)

| Strategy | Direction | Daily Condition | Intraday Condition | Regime |
|----------|-----------|-----------------|--------------------|--------|
| BB Mid Reclaim | LONG | Close > BB mid (≥0.5%) after testing below | LTP crosses ≥0.3% above 20-SMA + RSI 40–65 + gap up ≥0.5% | Nifty bullish |
| 20D Low Breakdown | SHORT | Close < 20-day low | Intraday low ≥0.5% below 20D low + RSI 25–45 + gap down ≥0.5% | Nifty bearish |
| ORB | long/short | — (live only) | Opening-range breakout | any |
| Bull Call Spread | LONG | — (live only) | Bullish regime + IV Rank ≥ 25 | Nifty bullish |
| Bull Put Spread | LONG | — (live only) | Bullish regime + IV Rank ≥ 25 | Nifty bullish |
| Iron Condor | NEUTRAL | — (live only) | IV Rank ≥ 50 + Nifty 15-min range < 60 | any |
| Straddle | DIRECTIONAL | — (live only) | Nifty 15-min range > 60 + IV Rank ≤ 70 | any |
| Strangle | DIRECTIONAL | — (live only) | Nifty 15-min range > 60 + IV Rank ≤ 70 | any |

Intraday variants have tighter filters (see `config.yaml` → `strategies.*.intraday*`). The 5 option strategies are configured under `config.yaml` → `strategies.option_strategies`.

## References

- `README.md` — project narrative, pipeline overview, quick start
- `config.yaml` — all tunable parameters
- `scan_daily.py` — daily signal generation
- `intraday.py` — combined intraday collector/signals
- `analyze_eod.py` — post-market analysis
- `dashboard.py` — live dashboard + HTTP API