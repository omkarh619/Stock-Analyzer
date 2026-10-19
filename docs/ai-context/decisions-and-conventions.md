# Decisions and Conventions

## Established Architectural Decisions

### 1. Flat-File Persistence (No Database)
All data is JSON or JSONL. No relational database, no ORM, no migration files. This keeps the project dependency-light but means schema evolution must be manual and careful.

**Evidence**: `data/intraday/YYYY-MM-DD.jsonl`, `signals/signals_*.json`, `signal_states/states_*.json` — all flat text.
**Source**: README.md → Project Structure section; directory listing confirms no db/ or sqlite/ folder.

### 2. Python 3.9 Single-Interpreter Scripts (No Framework)
Each script runs independently. No FastAPI/Flask for the dashboard — built-in `http.server`. No PyPI frameworks declared in any config file.

**Evidence**: `dashboard.py` uses `from http.server import HTTPServer, BaseHTTPRequestHandler`; scripts use only stdlib + `pandas`/`numpy`/`yaml`.
**Source**: README.md line 272: Python 3.9 at specific path; no `requirements.txt`.

### 3. Config-Driven Strategy Tuning
All strategy parameters live in `config.yaml` under `strategies.<name>.intraday*`. Changing filters requires no code changes. The dashboard reads the same config and applies it to live strategies.

**Evidence**: `config.yaml` → `strategies:` section with both daily and intraday variants per strategy. `dashboard.py` `_map_config()` maps these into dashboard strategy definitions.
**Source**: `config.yaml` lines 38–119; `dashboard.py` lines 51–126.

### 4. Combined Intraday Collector + Signal Generator
`intraday.py` replaced both `scan_intraday.py` and `collect_intraday.py`. The README states this explicitly (README lines 70–78). Legacy files are kept but flagged as superseded.

**Evidence**: README.md → "Combined script: `intraday.py` replaces both..."
**Source**: `scan_intraday.py` and `collect_intraday.py` present but documented as legacy.

### 5. Single-Page Dashboard with Polling
The UI is one HTML file served by a single-process HTTP server. State refreshes via HTTP polling every 2 seconds — no WebSockets, no push.

**Evidence**: `dashboard.html` has no routing framework; JS uses `setInterval` polling `/api/status`.
**Source**: `dashboard.html`; `test_ui.py` tests confirm polling pattern.

### 6. All Charges Computed from Fixed Formulas
Brokerage is capped at ₹20 flat (not quantity-based). STT is sell-side only. GST applies to brokerage+exchange. These formulas appear duplicated between `scan_daily.py` and `dashboard.py`.

**Evidence**: Both files have `calculate_charges()`. Structures match exactly.
**Source**: `scan_daily.py` line 87; `dashboard.py` line 380.

### 7. Daemon Collector Thread in Dashboard
The dashboard runs a separate daemon thread collecting data, with thread-safe `SharedState` using `threading.Lock`. Other scripts run synchronously.

**Evidence**: `dashboard.py` `Collector` class with `threading.Thread(daemon=True)`.
**Source**: `dashboard.py` lines 613–742.

## Recurring Implementation Patterns

### Pattern A: CLI with Date Flags
Most scripts accept `--date YYYY-MM-DD`. Example: `python scan_daily.py --date 2026-09-23`.

**Source**: `scan_daily.py` line 381 (argparse); `analyze_eod.py` line 371 (argparse).

### Pattern B: Lazy External Imports
Third-party libraries (`yfinance`, `nsepython`) are imported inside functions, not at module top level, so missing dependencies don't break startup.

**Evidence**: `dashboard.py` imports inside `fetch_nifty_ltp()` etc.; same in `scan_daily.py`.
**Source**: Multiple function bodies across scripts.

### Pattern C: Logging to File + stdout
Every script sets up `logging.basicConfig` with both file and stream handlers, using `logs/<script>_<date>.log`.

**Evidence**: `scan_daily.py`, `intraday.py`, `analyze_eod.py`, `dashboard.py` all have this setup.
**Source**: Across all four scripts.

### Pattern D: Safe Data Conversion with NaN Checks
Functions like `_safe_float()` guard against `NaN` and type errors when reading config or LTP values.

**Evidence**: `dashboard.py` `_safe_float()` at line 206; used throughout `SharedState` and API responses.
**Source**: `dashboard.py` lines 206–217; applied broadly.

## Important Constraints

1. **Risk controls are advisory, not enforced.** `config.yaml` → `risk.*` exists (max_open_positions, max_daily_loss_pct, weekly_loss_pct) but no script enforces them. Treat as documentation, not hard limits.

2. **No retry mechanism for failed fetches.** Scripts log errors and continue. Data gaps silently result in "no data" rather than retries.

3. **Daily history = 200 days.** Both `fetch_stock_data` and `fetch_nifty_data` default to 200 days from config.

4. **Signal deduplication is within-session only.** `SignalTracker` prevents repeats while a session runs, but does not persist across sessions.

5. **Nifty regime computed locally.** In `intraday.py`, Nifty above/below SMA(20) determines bullish/bearish regime inline — no external regime feed.

## Verified Conventions

| Convention | Where | Notes |
|------------|-------|-------|
| Python 3.9 (Windows virtualenv) | README.md | Line 272 |
| 16 watchlist stocks | config.yaml | Watchlist ordered alphabetically |
| Market hours 9:15–15:30 IST | intraday.py `main()` | Auto-skip otherwise |
| 60-second polling interval | intraday.py `Collector.run()` | During market hours only |
| CSV-style JSONL | `data/intraday/` | One JSON object per line |
| JSON arrays for signals | `signals/signals_*.json` | Array of signal objects |
| Date formats: `YYYY-MM-DD` and `YYYYMMDD` | Files named accordingly | Consistent across systems |
| UID: `strategy_symbol` keyed dict | `signals/signals_live_*.json` | Deduplication keys |
| Currency: ₹ with decimal (2 places) | Prices and charges | Standard formatting |
| Executable scripts (.py with shebang) | Repo root | All runnable directly |

## Gaps / Unverified Items

- **`jugaad-data` package API**: Not bundled, package-specific calls assumed. Needs verification if this repo scales.
- **Historical source provider**: `jugaad-data` is the configured provider but no `requirements.txt` lists it.
- **Auth on NSE API**: NSE India API calls may require headers/cookies; current implementation doesn't track this.
- **Dependency versions**: No lock file exists, making exact version pinning impossible.
- **Test coverage beyond HTTP smoke tests**: No unit tests for individual functions.

## Audit Trail Notes

Recent git history shows two commits: `db3079f init` (initial commit) and `7c2b57a .` (housekeeping). No feature additions or refactors visible — the repository appears stable. Given the 3+ day staleness and unchanged file set in `git status`, any current modifications should be verified against these docs before assuming correctness.

## Known Issue / Fix Applied

**Issue**: Dashboard UI button states not updating when Start/Stop clicked.
**Root cause**: `dashboard.py` `do_POST()` was missing `/api/stop` endpoint; the `/api/start` handler had unreachable dead code (`return` followed by `self._send_json`).
**Fix**: Added complete `/api/stop` handler (sets `STATE.running = False`, `COLLECTOR.active = False`) and cleaned unreachable line after `/api/start`. Verified with `grep`. Source: `dashboard.py` lines 838–860 (post-fix).