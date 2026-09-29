# Stock Analyzer

A systematic trading signal pipeline for Indian equities — designed for non-traders. Scans stocks for setups, outputs clear buy/sell recommendations with entry/SL/target/Charges, and collects data for continuous improvement.

**For non-traders**: Every signal includes plain-English instructions for executing on Zerodha Kite.

---

## Project Structure

```
D:/OpenCode/Stock/Stock Analyzer/
├── config.yaml              # Global config: watchlist, strategies, risk, charges, time cutoff
├── intraday.py              # COMBINED: 1-min data collector + signal generator (replaces scan_intraday.py + collect_intraday.py)
├── scan_daily.py            # Daily signal scanner (yesterday's data → today's signals)
├── analyze_eod.py           # End-of-day analyzer (reads data + signals → summary report)
├── signals/                 # Signal output files
│   ├── signals_YYYY-MM-DD.json      # Daily scan results
│   └── signals_live_YYYYMMDD.json   # Intraday signals
├── signal_states/           # Active signal state tracking (for AI analysis)
│   └── states_YYYYMMDD.json
├── data/intraday/           # 1-min collected data (JSONL, 30-day retention)
│   └── YYYY-MM-DD.jsonl
├── reports/                 # End-of-day analysis reports
│   ├── analysis_YYYYMMDD.json       # Full report
│   └── ai_summary_YYYYMMDD.json     # Machine-readable summary for AI review
├── logs/                    # Scan logs
└── README.md
```

---

## Pipeline Overview

```python
Morning (9 AM):
  scan_daily.py → reads yesterday's close → writes today's signals
  You read signals, check Kite chart, execute if valid

During market (9:15 AM — 3:30 PM):
  intraday.py → polls every 1 min → collects data + alerts when signals form
  (Combined: data collection AND signal generation in one script)
  Press Ctrl+C to stop. Auto-stops at market close.

After market close:
  analyze_eod.py → reads today's data + signals → writes summary report
  You share report with AI → AI analyzes, suggests strategy changes
```

---

## Scripts

### intraday.py — Combined Intraday Monitor + Data Collector (NEW)

**Replaces both `scan_intraday.py` and `collect_intraday.py`.**

One script that does everything during market hours:
- **Polls every 1 minute** — fetches all 16 stocks + Nifty
- **Collects data** — appends JSONL snapshot every minute (278+ samples/day)
- **Generates signals** — checks filters every cycle, deduplicates (no more spam)
- **Tracks signal state** — active → target_hit / sl_hit / expired
- **Writes signal states** — for AI analysis later

**Two strategies supported:**

| Strategy | Type | Intraday Trigger | Regime |
|----------|------|-----------------|--------|
| BB Mid Reclaim | LONG | Intraday LTP crosses ≥0.3% above 20 SMA + RSI 40-65 + gap up ≥0.5% | Nifty bullish |
| 20D Low Breakdown | SHORT | Intraday low breaks ≥0.5% below 20D low + RSI 25-45 + gap down ≥0.5% | Nifty bearish |

**Output**: Console alerts + `signals/signals_live_YYYYMMDD.json` + `signal_states/states_YYYYMMDD.json`

**Usage**:
```bash
python intraday.py
# Press Ctrl+C to stop. Auto-stops at market close (15:30).
```

### scan_daily.py — Daily Signal Scanner

Scans Nifty 50 stocks using yesterday's closing data. Detects two strategies:

| Strategy | Type | Condition | Regime |
|----------|------|-----------|--------|
| BB Mid Reclaim | LONG | Close crosses above 20 SMA (≥0.5%) after testing below | Nifty bullish |
| 20-Day Low Breakdown | SHORT | Close breaks below lowest low of past 20 days | Nifty bearish |

**Output**: `signals/signals_YYYY-MM-DD.json` with entry, SL, target, Charges breakdown, beginner instructions.

**Usage**:
```bash
# Default: scans yesterday's data (for today's signals)
python scan_daily.py

# Scan a specific date
python scan_daily.py --date 2026-09-23
```

### analyze_eod.py — End-of-Day Analyzer

Reads today's intraday data + today's signals → produces a summary report.

**Output**:
- `reports/analysis_YYYYMMDD.json` — Full report (market overview, per-signal outcomes, stats)
- `reports/ai_summary_YYYYMMDD.json` — Machine-readable summary for AI review

**Signal outcome tracking**: For each signal fired, the analyzer checks if price reached target, SL, reversed, or stayed open at close. Computes paper P&L.

**Usage**:
```bash
# Analyze today (run after market close)
python analyze_eod.py

# Analyze a past date
python analyze_eod.py --date 2026-09-24
```

---

## Configuration (`config.yaml`)

### Strategy Filters (Intraday)

#### SHORT filters (20D Low Breakdown — bearish regime)
```yaml
strategies:
  breakdown_20d_low:
    intraday:
      enabled: true
      rsi_min: 25          # RSI must be ≥25 (avoids deeply oversold bounce risk)
      rsi_max: 45          # RSI must be ≤45 (still falling, not recovered)
      gap_min_pct: 0.5     # Gap down ≥0.5% from prev close (bearish momentum)
      breakdown_min_pct: 0.5  # Intraday low must be ≥0.5% below 20D low
      nifty_confirmation: true  # Only if Nifty bearish
      target_pct: 2.5      # Take profit 2.5% below entry
      sl_pct: 3.5          # Stop loss 3.5% above entry
```

#### LONG filters (BB Mid Reclaim — bullish regime)
```yaml
  bb_reclaim_long:
    intraday_long:
      enabled: true
      rsi_min: 40          # RSI must be ≥40 (recovering, not oversold)
      rsi_max: 65          # RSI must be ≤65 (not yet overbought)
      gap_min_pct: 0.5     # Gap up ≥0.5% from prev close (bullish momentum)
      cross_min_pct: 0.3   # LTP must be ≥0.3% above 20 SMA (real cross)
      nifty_confirmation: true  # Only if Nifty bullish
      target_pct: 2.5      # Take profit 2.5% above entry
      sl_pct: 3.5          # Stop loss 3.5% below entry
```

### Other Key Settings

```yaml
watchlist:
  stocks:
    - RELIANCE
    - HDFCBANK
    # ... 16 liquid Nifty 50 stocks

risk:
  capital: 10000               # Trading capital (₹) — adjust to your actual capital
  risk_per_trade_pct: 0.015    # 1.5% of capital per trade

charges:
  broker: "Zerodha"
  brokerage_per_order: 20      # ₹20 per order (buy + sell = ₹40 total)
  gst_rate: 0.18
  stt_sell_pct: 0.001          # 0.1% on sell side
  exchange_transaction_pct: 0.0000375
  sebi_fee_per_cr: 10
  stamp_duty_buy_pct: 0.00015

time:
  intraday_cutoff: "12:00"     # Signals after this time = NOT RECOMMENDED
```

---

## Signal Output Format

Each signal in the JSON includes:

```json
{
  "type": "SHORT (intraday)",
  "strategy": "20D Low Breakdown",
  "stock": "RELIANCE",
  "time": "10:30:00",
  "live_ltp": 1220.90,
  "entry_price": 1220.90,
  "sl_price": 1263.63,
  "target_price": 1190.38,
  "target_pct": 2.5,
  "condition": "Intraday low 1219.70 broke below 20D low 1226.40...",
  "beginner_instruction": "This looks like a SELL (short) setup...",
  "beginner_entry": "1. On Kite: Search 'RELIANCE' → Click SELL...",
  "beginner_sl": "2. Stop Loss: Set a STOP LOSS order at Rs.1263.63...",
  "beginner_exit": "3. Exit: Watch the chart...",
  "action": "SL: Rs.1263.63 (3.5% above entry). Target: Rs.1190.38 (2.5% below entry).",
  "too_late": false,
  "charges": {
    "broker": "Zerodha (intraday MIS)",
    "estimated_total": 62.16,
    "breakdown": {"brokerage": 40, "gst": 7.2, "stt": 1.22, "exchange": 0.09, "sebi": 0.0, "stamp_duty": 0.18},
    "break_even_price": 1214.68,
    "estimated_quantity": 10,
    "estimated_trade_value": 12209.00
  }
}
```

---

## Indicators — All Computed from Price Data

All indicators are calculated from OHLC (Open, High, Low, Close) + Volume. No external data needed:

| Indicator | Formula | Data needed |
|---|---|---|
| RSI(14) | 100 - 100/(1 + RS), where RS = avg gain / avg loss over 14 periods | Close prices |
| SMA(20) | Sum of last 20 closes / 20 | Close prices |
| Bollinger Bands | Middle = SMA(20), Upper = SMA + 2σ, Lower = SMA - 2σ | Close prices |
| ATR(14) | Average True Range = avg of max[(H-L), abs(H-Cp), abs(L-Cp)] | High, Low, Close |
| MACD | EMA(12) - EMA(26), signal = EMA(9) of MACD | Close prices |
| Volume ratio | Today's volume / 20-day avg volume | Volume |
| Gap % | (Open - Previous Close) / Previous Close | Open, Previous Close |
| Day Range % | (High - Low) / Low | High, Low |

The analyzer computes these on the fly from collected 1-min data.

---

## Learning Loop

```
Day 1-30: Collect data (intraday.py runs daily)
          → After each day: analyze_eod.py produces report
          → Share report with AI: "Here's today's analysis"
          → AI reviews: signal outcomes, patterns, what worked/failed
          → AI suggests: "Consider X change to strategy" or "Need more data"

Month 2: Enough data to identify patterns
          → AI analyzes 30 days of outcomes
          → Recommendations: time-of-day patterns, strategy tweaks, regime filters
          → Update config.yaml if evidence supports change

Ongoing: Every day collect → analyze → AI review → refine
```

**AI's role**: The scripts collect data and produce structured summaries. The AI (you) reads the reports and applies judgment — identifying patterns, suggesting changes, deciding when there's enough evidence to modify the strategy.

---

## Quick Start

```bash
cd "D:/OpenCode/Stock/Stock Analyzer"

# 1. Daily scan (morning, get today's signals)
python scan_daily.py

# 2. Intraday monitor + data collector (combined, during market)
python intraday.py

# 3. End-of-day analysis (after market close)
python analyze_eod.py
```

All scripts use `/d/Gradient/PyChecks_vevn39/Scripts/python` as the Python interpreter.

---

## Important Notes

- **Paper trade first.** Do not go live until you have a proven track record.
- **Always confirm on Kite** before executing. The signal is a trigger, not a command.
- **Charges are estimated** (Zerodha intraday MIS). Verify exact charges with your broker.
- **Past performance does not guarantee future results.**
- **Time cutoff**: Signals after 12:00 PM are flagged as NOT RECOMMENDED (may not have time to reach target).
- **Capital**: Currently set to ₹10,000 in config. Adjust `risk.capital` as needed.
- **Combined script**: `intraday.py` replaces both `scan_intraday.py` and `collect_intraday.py`. Use it going forward.
- **Filters are tunable**: Edit `config.yaml` to adjust RSI ranges, gap thresholds, breakdown/cross minimums, targets, and SL. No code changes needed.
