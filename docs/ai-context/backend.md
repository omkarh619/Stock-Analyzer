# Backend Architecture

## Overview

The backend is a set of Python 3.9 scripts (no framework). Each script is runnable standalone, reads `config.yaml`, and writes structured JSON/JSONL output to disk.

**Interpreter**: `/d/Gradient/PyChecks_vevn39/Scripts/python` (Windows virtualenv at Python 3.9 — documented in `README.md` line 272).

## Service Responsibilities

### scan_daily.py — Daily Signal Scanner
- **Entry**: `main()` with `--date YYYY-MM-DD` flag (default: yesterday's data for today's signals).
- **Input**: Historical OHLCV from yfinance/jugaad-data (config `data.provider`), `config.yaml`.
- **Logic**:
  - `fetch_stock_data()` / `fetch_nifty_data()` — fetches 200-day history.
  - `compute_indicators()` — RSI(14), SMA(20), Bollinger Bands, ATR(14), MACD, volume ratio, gap %.
  - `check_bb_reclaim_long()` — LONG signal: close crosses above BB mid ≥0.5%.
  - `check_breakdown_20d_low()` — SHORT signal: close breaks below 20-day low, Nifty must be bearish.
- **Output**: `signals/signals_YYYY-MM-DD.json` with per-stock entry, SL, target, charges, beginner_instruction, break-even price.

### intraday.py — Combined Collector + Signal Generator
- **Entry**: `main()` (run `python intraday.py`, Ctrl+C or auto-stop at 15:30).
- **Input**: Live NSE LTP (via `jugaad-data` / `nsepython`), 1-min loop.
- **Logic**:
  - `Collector` thread (class) — polls every 60s during market hours, appends JSONL snapshot.
  - `SignalTracker` class — deduplicates signals (no repeat spam within session).
  - `SignalState` class — tracks each active signal: entry → target_hit / sl_hit / expired.
  - `check_short_filters()` / `check_long_filters()` — applies `config.yaml` → `strategies.*.intraday*` filters.
- **Output**:
  - `data/intraday/YYYY-MM-DD.jsonl` — 1-min snapshots (nifty + 16 stocks per row).
  - `signals/signals_live_YYYYMMDD.json` — current active intraday signals (dict keyed by `strategy_symbol`).
  - `signal_states/states_YYYYMMDD.json` — full state dump for AI analysis.

### analyze_eod.py — End-of-Day Analyzer
- **Entry**: `main()` with `--date YYYY-MM-DD` flag (default: today).
- **Input**: `data/intraday/YYYY-MM-DD.jsonl`, `signals/signals_live_YYYYMMDD.json`, yesterday's `signals/signals_YYYY-MM-DD.json`.
- **Logic**:
  - `load_intraday_data()` — parses JSONL into DataFrame, pivots per-symbol time series.
  - `evaluate_signal_outcome()` — simulates: from entry, did LTP reach target/SL/reverse. Computes paper P&L.
  - Outcomes: `HIT_TARGET`, `HIT_SL`, `REVERSED`, `OPEN_AT_CLOSE`, `no_data`.
- **Output**:
  - `reports/analysis_YYYYMMDD.json` — full report (market summary, signal outcomes, stats).
  - `reports/ai_summary_YYYYMMDD.json` — machine-readable summary for AI review (nifty regime, per-signal P&L, stats).

### dashboard.py — Live Dashboard Server
- **Entry**: `main()` — HTTP server on `localhost:8899`.
- **Structure**: Single-file `BaseHTTPRequestHandler` server. Thread for collector + main loop.
- **API**:
  - GET ` `/`index.html` → serves `dashboard.html`.
  - GET `/api/status` → full `SharedState.to_dict()` (nifty, symbols, strategies, stock_data, price_history counts, active_signals).
  - GET `/api/chart_data` → price history + signal lines for SVG chart.
  - GET `/api/strategies` → strategy definitions + current config.
  - POST `/api/start` → starts collector thread.
  - POST `/api/toggle_strategy` → enable/disable strategy at runtime.
  - POST `/api/configure` → updates strategy filters at runtime.
- **Collector thread**: reuses `fetch_nse_ltp` / `fetch_nifty_ltp` (yfinance fallback). Runs 3 strategies: `short_20d_low_breakdown`, `long_bb_reclaim`, `orb` (Opening Range Breakout).
- **SharedState** — thread-safe (uses `threading.Lock`). Holds live LTP, price history (max 200 bars), regime, active signals, collector health.

## Key Functions (Verified Symbols)

| Script | Function | Purpose |
|--------|----------|---------|
| `scan_daily.py` | `calculate_charges(side, trade_value, quantity)` `@L87` | Zerodha MIS charges breakdown |
| `scan_daily.py` | `compute_indicators(df)` `@L172` | RSI, SMA, BB, ATR, MACD |
| `scan_daily.py` | `build_signal(...)` | Constructs full signal dict |
| `intraday.py` | `SignalTracker.check_and_add_short(...)` `@L282` | Short signal dedup + state |
| `intraday.py` | `get_capital()` | Reads risk.capital from config |
| `intraday.py` | `load_config_yaml()` `@L129` | Loads + validates config |
| `analyze_eod.py` | `evaluate_signal_outcome(symbol, signal, df)` `@L160` | P&L + outcome simulation |
| `dashboard.py` | `calculate_charges(broker, qty, price, side)` `@L380` | Same as scan_daily but parameterized |
| `dashboard.py` | `_map_config(loaded)` `@L73` | Maps config.yaml → dashboard expected shape |

## Error Handling Patterns

- All scripts use `logging` (file + stdout). Log files: `logs/<script>_<date>.log`.
- NSE fetch failures fall back to `yfinance` (e.g., `fetch_nifty_ltp()` → yfinance `^NSEI`).
- Most data-missing cases log a warning and return `None`/empty rather than crashing.
- `try/except` blocks wrap every external API call; failures are logged, not raised.

## Risk / State Management

- **No persistent trade ledger**: signals are stateless snapshots. Outcome tracking is computed by `analyze_eod.py` post-hoc.
- **`signal_states/`**: the only persistent state — stores `SharedState.to_dict()` snapshots from dashboard runs, for AI pattern analysis.
- Risk controls live only in `config.yaml` (`risk.max_daily_loss_pct`, `risk.max_open_positions`) — **not enforced by code**. They are advisory for the AI/human reviewer.
- **Capital**: `risk.capital` (default ₹10,000) used for quantity estimation, not enforced.