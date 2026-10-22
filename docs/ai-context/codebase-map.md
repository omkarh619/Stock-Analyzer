# Codebase Map

## Repository Root: `D:/OpenCode/Stock/Stock Analyzer`

## Important Directories

| Directory | Purpose | Retention |
|-----------|---------|-----------|
| `data/intraday/` | 1-min candlestick snapshots as JSONL | 30 days (README-stated) |
| `signals/` | Daily + intraday signal JSON output | Indefinite |
| `signal_states/` | Active/complete state tracking for AI analysis | Indefinite |
| `reports/` | EOD analysis JSON + AI-readable summary | Indefinite |
| `logs/` | Per-script log files (dated) | Indefinite |
| `docs/ai-context/` | This knowledge base | N/A |

## Key Files

### Core Scripts

| File | Responsibility |
|------|----------------|
| `scan_daily.py` | Morning daily scanner. Reads yesterday's close → writes today's signals. Strategies: `bb_reclaim_long`, `breakdown_20d_low`. CLI: `--date YYYY-MM-DD`. |
| `intraday.py` | Combined 1-min collector + signal generator for market-hours monitoring. Replaces older `scan_intraday.py` + `collect_intraday.py`. Auto-stops at 15:30 IST. |
| `analyze_eod.py` | Post-market analyzer. Reads intraday data + today's signals → produces `reports/analysis_*.json` + `reports/ai_summary_*.json`. CLI: `--date YYYY-MM-DD`. |
| `dashboard.py` | Live dashboard server (localhost:8899). Serves `dashboard.html` + JSON API. Runs collector thread with 8 strategies (3 equity + 5 option). |
| `collect_daily_data.py` | Daily data collection helper (historical, uses yfinance). Lower priority than `intraday.py`. |
| `collect_intraday.py` | Older intraday collector (largely superseded by `intraday.py` but still present). |
| `scan_intraday.py` | Older intraday scanner (largely superseded by `intraday.py` but still present). |

### Configuration & Static Assets

| File | Responsibility |
|------|----------------|
| `config.yaml` | All tunable parameters: watchlist, strategies, risk, charges, time cutoffs, data provider. |
| `dashboard.html` | Standalone HTML UI served by `dashboard.py`. Self-contained JS/CSS (no framework). |
| `daily_trade_log.txt` | Trade recommendations log (human-readable, not source code). |
| `README.md` | Project documentation: pipeline overview, strategy details, quick start. |

### Tests

| File | What it tests |
|------|---------------|
| `test_dashboard.py` | Comprehensive dashboard tests: config, state, helpers, strategies, chart data, server, API, HTML content. Run with dashboard live (port 8899). |
| `test_ui.py` | UI-level HTTP tests against running dashboard: server status, `/api/status`, HTML UI components. |

## Investigation Guide

- **To modify a strategy filter**: `config.yaml` → `strategies.<name>.intraday*` (no code change needed in most cases).
- **To change signal output format**: `scan_daily.py` (build_signal) or `intraday.py`.
- **To add a data field to the JSONL**: `intraday.py` Collector snapshot loop + `analyze_eod.py` loader.
- **To add a dashboard strategy**: `dashboard.py` `STRATEGY_DEFS` + `dashboard.html` strategy card.
- **To change charges calculation**: `dashboard.py calculate_charges()` / `scan_daily.py calculate_charges()`.

## Legacy Files (Keep but Don't Prefer)

- `collect_intraday.py` — superseded by `intraday.py` Collector thread
- `scan_intraday.py` — superseded by `intraday.py` signal checks

These are still present in the repo and may be referenced by old scripts or logs. The `README.md` explicitly states `intraday.py` replaces both.

## Entry Points

- `python scan_daily.py` — daily signals (morning, after market close)
- `python intraday.py` — live intraday (market hours)
- `python analyze_eod.py` — end-of-day report (after market close)
- `python dashboard.py` — live dashboard (anytime, browser opens automatically)