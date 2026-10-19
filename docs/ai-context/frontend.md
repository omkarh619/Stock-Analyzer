# Frontend Architecture

## Overview

The user interface is a **single static HTML file** (`dashboard.html`, ~60KB) served by `dashboard.py`'s built-in HTTP server. It is vanilla JavaScript (no React/Vue/Angular) with inline CSS and SVG-based charting.

**URL**: `http://localhost:8899` (opens automatically when `dashboard.py` starts).

## Component Structure

The UI is organized into three sections rendered by JS functions inside `dashboard.html`:

1. **Strategy Cards** (`renderStrategyCards`) — one card per strategy showing status, signal count, filters, and quick-configure buttons.
2. **Instrument Cards** (`renderInstrumentCards`) — one card per stock showing live LTP, change, range, gap, and an inline SVG chart.
3. **Chart Panel** (`drawChart` / `renderSvgChart`) — price history with entry/SL/target reference lines.

## Routing / State

- **No client-side routing**: single-page, all content from `/api/status` polled every 2 seconds.
- **State source**: a single JS module-level object updated from the API response. No state management library.
- **Polling**: `setInterval` → GET `/api/status`, then re-renders affected cards. No WebSockets.

## Data Fetching

| Endpoint | Method | Returns |
|----------|--------|---------|
| `/` | GET | HTML page |
| `/api/status` | GET | Full state: nifty price/SMA/regime, all stock LTPs, price history counts, strategy states, active signals, collector health |
| `/api/chart_data` | GET | Price history (time/ltp/high/low) + signal reference lines (entry/sl/target) |
| `/api/strategies` | GET | Strategy definitions + current filter config |
| `/api/start` | POST | Starts collector thread |
| `/api/toggle_strategy` | POST | Enable/disable strategy at runtime |
| `/api/configure` | POST | Update strategy filters (rsi_min, target_pct, etc.) |

## Key UI Behaviors

- **Nifty regime badge**: shows "BULLISH"/"BEARISH" + distance from 20-SMA. Falls back to "delayed" (yfinance) source when NSE is down.
- **Cache-control**: `dashboard.html` sends `Cache-Control: no-cache` header so browser always fetches fresh HTML.
- **Price history**: each stock card shows a sparkline rendered as inline SVG from the `/api/chart_data` response.
- **Signal cards**: active signals appear with entry/SL/target prices, estimated quantity, and charge breakdown — sourced from the `active_signals` array in `/api/status`.

## Testing

`test_ui.py` and `test_dashboard.py` contain assertions that verify:
- `renderStrategyCards` / `renderInstrumentCards` functions exist and are called.
- `strategyCards` / `instrumentCards` containers exist.
- `drawChart` / `renderSvgChart` functions exist.
- Strategy card count ≥ 3 (matches `STRATEGY_DEFS`).
- `niftyDelayBadge` element exists (for yfinance fallback indicator).
- `/api/status` returns expected fields (price, source, symbols, strategies, active_signals).

**Note**: Tests require the dashboard server to be live on port 8899. They are not unit tests — they perform HTTP requests against a running instance.

## Files

- `dashboard.html` — the only static asset (served by `dashboard.py`).
- `dashboard.py` — HTTP server + collector + API (backend serves the frontend).