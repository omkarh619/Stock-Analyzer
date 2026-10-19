# Testing and Development

## Python Version

- **Python 3.9** (Windows virtualenv)
- Interpreter path (from README.md line 272): `/d/Gradient/PyChecks_vevn39/Scripts/python`
- Standard library + `pandas`, `numpy`, `pyyaml`, `yfinance`

## Verified Development Commands

### Run Scripts

```bash
# Daily signal scan (morning, after market close)
python scan_daily.py

# Intraday monitor + data collector (combined, during market)
python intraday.py

# End-of-day analysis (after market close)
python analyze_eod.py

# Live dashboard (anytime, browser opens)
python dashboard.py
```

### Test Commands

Tests require a running dashboard on port 8899:

```bash
# UI-level HTTP test (expects dashboard already running)
python test_ui.py

# Comprehensive dashboard tests
python test_dashboard.py
```

**Important**: Tests are not unit tests — they perform HTTP requests against a live server. The `-404` result in test_dashboard.py means the specific file doesn't exist, not a test name.

### Test Files

| File | Tests | Entry Point |
|------|-------|-------------|
| `test_dashboard.py` | Full suite: config, state, helpers, strategies, chart_data, server status, API responses, HTML content validation | `run()` function |
| `test_ui.py` | UI-level HTTP tests: server status, `/api/status`, HTML UI components | Direct script execution |

## Test Organization

- Both test files are standalone scripts (no `unittest`/`pytest` framework).
- `test_dashboard.py` defines a `run()` function called from `if __name__ == "__main__":`.
- Results are printed to console with `[PASS]`/`[FAIL]` markers.
- `test_dashboard.py` includes a `section(title)` helper for organized output.

## Local Setup Requirements

1. **Virtual Environment**: Python 3.9 is expected at the documented path. Activate or ensure `python` is Python 3.9+.

2. **Dependencies**: Not managed by `requirements.txt`. The README implies dependencies are pre-installed in a virtualenv:
   - `pip install pandas numpy pyyaml yfinance` (if needed)

3. **Data directories**: Scripts expect these to exist or will create them:
   - `data/intraday/` — 1-min snapshots
   - `signals/` — signal JSON files
   - `signal_states/` — state tracking
   - `reports/` — EOD analysis
   - `logs/` — log files

4. **Market hours**: `intraday.py` only runs during 9:15–15:30 IST; will skip otherwise.

5. **Network**: Access to NSE India API (`nseindia.com`) or `yfinance` required for live prices.

## Quick Start Commands

```bash
cd "D:/OpenCode/Stock/Stock Analyzer"

# 1. Daily scan (morning)
python scan_daily.py

# 2. Intraday monitor (market hours)
python intraday.py

# 3. End-of-day analysis (after close)
python analyze_eod.py

# 4. Dashboard (anytime)
python dashboard.py
```