# Stock Analyzer — AI Knowledge Base

A systematic trading-signal pipeline for Indian equities (Nifty 50). Scans stocks for setups, generates buy/sell recommendations with entry/SL/target/charges, and collects data for continuous improvement.

## Quick Start

```bash
cd "D:/OpenCode/Stock/Stock Analyzer"

# 1. Daily signal scan (morning, after market close)
python scan_daily.py

# 2. Intraday monitor + data collector (combined, during market 9:15–15:30 IST)
python intraday.py

# 3. End-of-day analysis (after market close)
python analyze_eod.py

# 4. Live dashboard (anytime, opens browser at localhost:8899)
python dashboard.py
```

**Python interpreter**: Python 3.9 at `/d/Gradient/PyChecks_vevn39/Scripts/python` (documented in `README.md`).

## Configuration

- `config.yaml` — watchlist (16 stocks), strategies (BB Mid Reclaim / 20D Low Breakdown), risk (capital ₹10k, charges Zerodha MIS), time cutoff `12:00`.
- Most strategy changes are config-only — no code changes needed.

## Knowledge Documents (`docs/ai-context/`)

| Document | What it covers |
|----------|----------------|
| `README.md` | Index + knowledge maintenance policy |
| `architecture.md` | Overall design, components, execution flows |
| `codebase-map.md` | Files, directories, investigation guide |
| `backend.md` | Python scripts, signal logic, API flow |
| `frontend.md` | Dashboard UI, HTML, HTTP endpoints |
| `data-model.md` | JSON/JSONL schemas, signal and report structures |
| `integrations.md` | External data sources (NSE, yfinance, jugaad-data), charges |
| `testing-and-development.md` | Test commands, local setup requirements |
| `decisions-and-conventions.md` | Architectural decisions, coding patterns, constraints |

## Important Rules

- **Code takes precedence over documentation.** The knowledge documents describe observed behavior — they are reference material, not the source of truth.
- **Knowledge maintenance is opt-in.** Do not edit `docs/ai-context/` or `CLAUDE.md` unless explicitly requested to refresh/update AI knowledge. If you find stale documentation, mention it in your response instead of changing it.
- **Do not modify application code, configuration, tests, or business logic** unless asked.
- Do not create hooks, scheduled jobs, CI workflows, or automation that updates knowledge files.
