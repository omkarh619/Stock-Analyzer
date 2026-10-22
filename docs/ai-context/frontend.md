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

- **No client-side routing**: single-page, all content from `/api/status` polled every 5 seconds.
- **State source**: a single JS module-level object updated from the API response. No state management library.
- **Polling**: `setInterval(refresh, 5000)` → GET `/api/status`, then re-renders affected cards. No WebSockets.

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
- **Live Signals table** (`renderSignals`): reads `s.active_signals || []`; dedupes by `sig.id || (sig.strategy + '_' + sig.symbol)`; updates the `#signalCountBadge` count; renders an empty state ("No active signals") when the list is empty. Expected fields include: `symbol`, `entry`, `sl`, `target`, `timestamp`, `type` (`"long"`/`"short"`/`"directional"`/`"neutral"`), `strategy`, `priority_score`, `strike`, `expiry`, `legs`, `status`, `iv_rank`, `valid_until`, `max_loss_amount`, `risk_exceeded`.
- **Option signal cards**: 5 new option strategies (`bull_call_spread`, `bull_put_spread`, `iron_condor`, `straddle`, `strangle`) appear alongside the 3 equity strategies, for 8 cards total. Each card shows direction label (`LONG`/`DIRECTIONAL`/`NEUTRAL` for options, `long`/`short` for equity), last signal time, signal count, and toggle button.
- **Direction styling**: `directionClass(dir)` maps `"LONG"` → `long`, `"SHORT"` → `short`, `"DIRECTIONAL"` / `"NEUTRAL"` → `both` (neutral style). Signal tags render as `String(sig.type || sig.direction || '').toUpperCase()`. Option direction labels pass through unchanged.
- **Chart modal**: clicking a signal row calls `openChart(symbol, strategy, signalJson)` → `drawChart` → `chart_data_for(symbol, price_history, signal)`, which reads `signal.get("entry"/"sl"/"target"/"type")` and returns `{"stock", "data", "lines": {entry/sl/target}, "signal_type"}`.
- **P&L**: `getCurrentPnl(sig)` treats `signal.type === 'long'` as long, otherwise short.
- **Strategy cards**: one per strategy in `STRATEGY_DEFS` (8 total), with toggle + signal count + last-signal time.
- **Option signal rendering**: option signals carry a `symbol` of the form `NIFTY-2026-10-27-24200` plus a `legs` array. The signal row shows the strategy's direction label, strike/expiry, priority score, and the leg summary from `description`. `status` values map to the active/expired/squared indicator; `risk_exceeded: true` marks a trade whose minimum size already busts the risk budget.

## Testing

`test_ui.py` and `test_dashboard.py` contain assertions that verify:
- `renderStrategyCards` / `renderInstrumentCards` functions exist and are called.
- `strategyCards` / `instrumentCards` containers exist.
- `drawChart` / `renderSvgChart` functions exist.
- Strategy card count ≥ 8 (matches `STRATEGY_DEFS`).
- `niftyDelayBadge` element exists (for yfinance fallback indicator).
- `/api/status` returns expected fields (price, source, symbols, strategies, active_signals).

**Note**: Tests require the dashboard server to be live on port 8899. They are not unit tests — they perform HTTP requests against a running instance.

## Files

- `dashboard.html` — the only static asset (served by `dashboard.py`).
- `dashboard.py` — HTTP server + collector + API (backend serves the frontend).