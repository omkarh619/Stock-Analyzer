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
  - POST `/api/stop` → stops the collector thread (`STATE.running = False`, `COLLECTOR.active = False`).
- **Collector thread**: reuses `fetch_nse_ltp` / `fetch_nifty_ltp` (yfinance fallback). Runs 8 strategies: `short_20d_low_breakdown`, `long_bb_reclaim`, `orb` (Opening Range Breakout) plus 5 option strategies — `bull_call_spread`, `bull_put_spread`, `iron_condor`, `straddle`, `strangle`.
- **SharedState** — thread-safe (uses `threading.Lock`). Holds live LTP, price history (max 200 bars), regime, active signals, collector health.
- **Signal normalization**: `normalize_signal(sig)` maps legacy schemas (`stock`/`entry_price`/`sl_price`/`target_price`/`time`, `type` values like `"SHORT (intraday)"`) onto the canonical dashboard shape (`symbol`/`entry`/`sl`/`target`/`timestamp`/`type` ∈ `{"long","short"}`). Applied to legacy strategy names (`"20D Low Breakdown"` → `short_20d_low_breakdown`, `"BB Mid Reclaim"` → `long_bb_reclaim`).
- **Active signal merge**: after each collector cycle, newly detected signals are merged into `state.active_signals` keyed by `{strategy}_{symbol}` so the frontend (which reads `state.active_signals`) sees them live.
- **Startup loader**: `main()` loads `signals/signals_live_YYYYMMDD.json` (both `signals/dashboard/` and `signals/`) into `STATE.active_signals` via `normalize_signal`, so signals survive a restart.
- **Market hours**: collector runs 9:15–15:30 IST (`now.hour < 9 or (now.hour == 15 and now.minute > 30) or now.hour > 15` → stop).
- **Option chain (Phase 2)**: option data is fetched from the NSE public option-chain-v3 endpoint (`https://www.nseindia.com/api/option-chain-v3?type=Indices&symbol=NIFTY&expiry=<DD-Mon-YYYY>`). The `expiry` parameter is required. IV is read directly from the endpoint (no local Black-Scholes).

### Option Strategy Checkers (Phase 2)

All five option checkers share the same signature: `check_<name>(state, ctx) -> list[signal]`.

`ctx` is built once per collector cycle by `_option_context(state)` and carries the shared market context: `now`, `chain`, `rows` (normalized strikes), `spot`, `expiry`, `iv_rank`, `range_15m`, `regime`, `tod_bonus`, `vol_bonus`, `allowed`, `reason`, `valid_until`, `index`.

| Checker | Direction | Gate conditions | Structure |
|---------|-----------|-----------------|-----------|
| `check_bull_call_spread` | LONG | `regime == "bullish"`, `iv_rank >= 25` | Buy `atm+otm` CE / sell `atm+otm+leg_width` CE |
| `check_bull_put_spread` | LONG | `regime == "bullish"`, `iv_rank >= 25` | Buy `atm-otm` PE / sell `atm-otm-leg_width` PE |
| `check_iron_condor` | NEUTRAL | `iv_rank >= 50`, `range_15m < 60` | Sell `atm±otm` CE/PT, buy `atm±(otm+wing_width)` wings |
| `check_straddle` | DIRECTIONAL | `range_15m > 60`, `iv_rank <= 70` | Buy ATM CE + ATM PE |
| `check_strangle` | DIRECTIONAL | `range_15m > 60`, `iv_rank <= 70` | Buy `atm+otm` CE + `atm-otm` PE |

Trigger windows are enforced centrally by `_trigger_allowed(now)`: nothing fires after the pre-close cutoff (`14:50`), and Friday signals must trigger by `14:00`. `run_strategy_checks(state)` builds the context once and calls all five; any failure is logged and skipped (never raised).

Sizing uses `_option_sizing()`: lots are chosen so `max_loss_per_lot × lots <= capital × max_loss_pct` (default 1.5% of `risk.capital`), capped by `qty_est` from config. If one lot already exceeds the budget, the trade is still sized at 1 lot and flagged with `risk_exceeded: true` rather than silently dropped.

Debit structures (spreads, straddles, straddles) set `sl = entry × (1 - sl_pct)` and `target = entry × (1 + target_pct)`. Credit structures (iron condor) invert this: `sl = entry × (1 + sl_pct)`, `target = entry × (1 - target_pct)`.

Charges are computed per leg by `_option_charges(legs, lot_size)` — each leg is one order, so brokerage applies per leg and STT is charged on the sell side only.

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
| `dashboard.py` | `calculate_charges(broker, qty, price, side)` `@L1166` | Same as scan_daily but parameterized |
| `dashboard.py` | `_map_config(loaded)` `@L76` | Maps config.yaml → dashboard expected shape |
| `dashboard.py` | `normalize_signal(sig)` `@L1194` | Normalizes legacy and new signal dicts to canonical format |
| `dashboard.py` | `run_strategy_checks(state)` `@L1439` | Runs all enabled strategy checks; returns list of signals |
| `dashboard.py` | `Collector.run()` `@L1447` | Polling loop (every 60s during market); writes live signals |
| `dashboard.py` | `fetch_option_chain(symbol, expiry_date, force)` `@L353` | NSE option-chain-v3 fetch with 15-min cache; discovers expiry when not given |
| `dashboard.py` | `_option_chain_expiries(symbol)` `@L382` | Expiry date list from the contract-info endpoint |
| `dashboard.py` | `_chain_rows(chain)` `@L391` | Normalizes chain records → `[{strike, CE, PE}, ...]` |
| `dashboard.py` | `_leg_values(row, side)` `@L414` | LTP / IV / OI / volume for one side of a strike row |
| `dashboard.py` | `_iv_rank()` `@L434` | IV Rank 0–100 from INDIAVIX vs its own 90-day range (15-min cache) |
| `dashboard.py` | `nifty_range_15m(state)` `@L461` | Nifty high-low range over the last ~15 min of snapshots |
| `dashboard.py` | `_tod_bonus(now)` / `_vol_bonus(range, now)` `@L483` / `@L494` | Time-of-day and volatility bonus from `priority.*` config |
| `dashboard.py` | `_trigger_allowed(now)` `@L507` | Friday 14:00 / pre-close 14:50 trigger cutoffs |
| `dashboard.py` | `_valid_until(now)` `@L521` | Signal validity horizon from the `validity` config windows |
| `dashboard.py` | `priority_score(iv_rank, tod_bonus, weight, vol_bonus, now)` `@L530` | Ranking score; Thursday scales by 0.60 |
| `dashboard.py` | `_market_regime(state)` `@L548` | bullish / bearish / neutral / unknown from Nifty vs 20 SMA |
| `dashboard.py` | `_option_sizing(max_loss_per_lot, ...)` `@L560` | Lots from risk budget; flags `risk_exceeded` |
| `dashboard.py` | `_option_charges(legs, lot_size)` `@L581` | Per-leg round-trip charges (brokerage per leg, STT sell-side) |
| `dashboard.py` | `_build_option_signal(state, ctx, strategy, cfg, legs, ...)` `@L610` | Assembles the canonical option signal dict |
| `dashboard.py` | `_option_context(state)` `@L674` | Builds the shared context for all five option checkers |
| `dashboard.py` | `check_bull_call_spread(state, ctx)` `@L711` | Bullish regime debit spread |
| `dashboard.py` | `check_bull_put_spread(state, ctx)` `@L755` | Bullish regime put debit spread |
| `dashboard.py` | `check_iron_condor(state, ctx)` `@L799` | Neutral/rich-IV credit structure |
| `dashboard.py` | `check_straddle(state, ctx)` `@L854` | ATM long-volatility structure |
| `dashboard.py` | `check_strangle(state, ctx)` `@L895` | OTM long-volatility structure |

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