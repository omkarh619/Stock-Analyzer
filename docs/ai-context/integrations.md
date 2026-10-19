# Integrations

## Overview

The system depends on **three external data sources** for market prices and historical data. All integrations are best-effort with automatic fallbacks — the code never hard-fails on source failure.

| Source | Purpose | Location | Status |
|--------|---------|----------|--------|
| `jugaad-data` | Historical OHLCV for stocks & Nifty (primary) | `config.yaml` → `data.provider` | Verified from config.yaml; underlying package not in repo |
| `yfinance` (via `nsepython`) | Live LTP fetch fallback | `intraday.py`, `dashboard.py` | Primary live source; NSE API direct also used |
| Yfinance directly (`^NSEI`) | Fallback when `nsepython` unavailable | `fetch_nifty_ltp()`, `fetch_nifty_fut_ltp()` | Module-level imports inside functions |

## Data Providers

### `jugaad-data`

Configured as `config.yaml` → `data.provider`:

```yaml
data:
  provider: "jugaad-data"
  history_days: 200
```

This is used by `scan_daily.py` to fetch 200 days of daily history for each stock and Nifty. Underlying Python package is referenced but not bundled in the repository (not installed in any tracked dependency file).

**Note**: Cannot verify exact API contract of `jugaad-data`. The call pattern matches standard PyChecks usage — `fetch_stock_data(hist, symbol)` / `fetch_nifty_data(hist)`.

### `nsepython`

Used by `intraday.py` to fetch real-time LTP via `https://www.nseindia.com/api/quote-equity?symbol=<SYMBOL>` and `https://www.nseindia.com/api/quote-derivative?symbol=NIFTY...FO`. Imported lazily inside functions (`from nsepython import StockAPI as newapi`).

**Note**: NSE India API calls are rate-limited and may fail if NSE is down. Fallback handles are present everywhere.

### Yfinance

Used as a robust fallback when both `jugaad-data` and `nsepython` are unavailable:

- `fetch_nifty_ltp()` → `yf.download("^NSEI", period="5d", interval="1d")`
- `fetch_nifty_fut_ltp()` → iterates month codes (`NIFTY<MON>FO`) calling `fetch_nse_ltp()`
- `fetch_stock_20d_low()` / `fetch_stock_daily_bb()` → `yf.Ticker(f"{symbol}.NS").history(...)`
- `dashboard.py` → same patterns for `/api/status` yfinance fallback

Yfinance is imported at function level (lazy imports), so no top-level dependency assumption.

## Charges (Broker Integration)

The charges calculation is **broker-agnostic in structure** but reflects Zerodha MIS intraday rules:

| Component | Formula | Source |
|-----------|---------|--------|
| Brokerage | `min(20, qty*price*0.0003)` — ₹20 flat cap | `calculate_charges` |
| STT | `qty*price*0.001` (sell side only) | Same |
| Exchange transaction | `qty*price*0.0000325` | Same |
| Stamp duty | `qty*price*0.00015` (Maharashtra, buy side) | Same |
| SEBI turnover fee | `qty*price*0.00000001` | Same |
| GST | `(brokerage + exchange) * 0.18` | Same |

Reference files:
- `scan_daily.py` line 87
- `dashboard.py` line 380

**Important**: The breakdown is hardcoded values matching Zerodha MIS rates. This is documentation-only accuracy — verify against actual broker quotes before acting. Never trust exact figures from static docs for live trades.

## Authentication & Authorization Boundaries

- **No authentication**: dashboard runs locally on `localhost:8899`, no auth middleware.
- **No API keys/credentials in code or config**: `config.yaml` contains no secrets.
- **HTTP server**: plain HTTP with CORS wildcard (`Access-Control-Allow-Origin: *`), no auth headers.

## Background Processing / Queues

- **No job queues**: collector runs synchronously in a daemon thread inside `dashboard.py`.
- **No message bus**: all scripts run sequentially or polled.
- **Async collector**: thread in `dashboard.py`; mon in `intraday.py` (pure synchronous polling).

## Events / Logging

- **Logging**: each script has its own log file at `logs/<script>_<date>.log` (e.g., `analyzer_20260928.log`). Level: INFO. Format: `%(asctime)s [%(levelname)s] %(message)s`.
- **No structured events emitted** — logs are the only observability mechanism.
- **Error handling**: `try/except` around every external call; failures logged at ERROR level. No alerting pipeline.