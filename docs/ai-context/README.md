# AI Knowledge Base

## Purpose

This directory contains concise, accurate reference documentation for the Stock Analyzer repository. Future Claude Code sessions can read these documents instead of re-exploring the entire repository for common tasks.

## Index

| Document | Purpose | Consult when... |
|----------|------------|-----------------|
| `architecture.md` | Overall design, components, execution flows | Understanding how the system works end-to-end |
| `codebase-map.md` | Files, directories, responsibilities, investigation guide | Locating code for a specific task |
| `backend.md` | Python scanner/analyzer scripts, logic layers | Modifying signal generation or analysis logic |
| `frontend.md` | Dashboard UI, HTML, HTTP API | Adding/changing dashboard views or endpoints |
| `data-model.md` | File formats, signal schema, JSON structures | Reading/writing signal or report data |
| `integrations.md` | External data sources (NSE, yfinance, jugaad-data), charges | Understanding data fetching or broker integration |
| `testing-and-development.md` | Test commands, test organization, dev setup | Running tests or verifying changes |
| `decisions-and-conventions.md` | Architectural decisions, coding patterns, constraints | Understanding why the code is the way it is |

## Knowledge Maintenance — Explicit Update Only Policy

- **Knowledge maintenance is opt-in.** During ordinary coding, debugging, testing, and refactoring:
  - Read the relevant documents when useful.
  - Do **not** edit, regenerate, or automatically refresh any file under `docs/ai-context/`.
  - Do **not** modify `CLAUDE.md` to record discoveries unless explicitly requested.
  - If you discover stale documentation, mention it in your final response instead of changing it.

- **Refresh commands** (when explicitly requested by the user):
  - `Refresh AI knowledge` — review recent repo changes and update affected docs.
  - `Refresh AI knowledge for <scope>` — update only for the specified module/feature/area.
  - `Audit AI knowledge` — identify outdated, inaccurate, or contradictory docs without modifying files.
  - `Apply AI knowledge audit` — apply explicitly approved corrections.

> The actual code in the repository is the source of truth and always takes precedence over these documents. These files describe observed behavior, not desired behavior.