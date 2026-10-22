#!/usr/bin/env python3
"""
Stock Analyzer — End-of-Day Analyzer
Reads today's intraday data + today's signals and produces a summary report.
Run after market close. Output: JSON summary + human-readable text.
"""

import os
import sys
import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import numpy as np

PROJECT_DIR = Path(r"D:\OpenCode\Stock\Stock Analyzer")
CONFIG_FILE = PROJECT_DIR / "config.yaml"
DATA_DIR = PROJECT_DIR / "data" / "intraday"
DASHBOARD_DATA_DIR = PROJECT_DIR / "data" / "dashboard"
SIGNALS_DIR = PROJECT_DIR / "signals"
DASHBOARD_SIGNALS_DIR = PROJECT_DIR / "signals" / "dashboard"
REPORTS_DIR = PROJECT_DIR / "reports"
LOG_DIR = PROJECT_DIR / "logs"

for d in [REPORTS_DIR, LOG_DIR]:
    d.mkdir(parents=True, exist_ok=True)

log_file = LOG_DIR / f"analyzer_{date.today().strftime('%Y%m%d')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger(__name__)


def load_config():
    import yaml
    with open(CONFIG_FILE, "r") as f:
        return yaml.safe_load(f)


def _expand_snapshot(snapshot, tracker):
    """Convert a dashboard snapshot row into per-symbol rows.

    dashboard.py writes one row per poll cycle: {"time", "nifty", "stocks": {...}}.
    intraday.py writes one row per stock per cycle. This normalises the former
    into the latter's shape so the rest of the analyzer sees one schema.

    The dashboard stores the current tick as high/low, so the running day range
    is tracked here instead (same semantics as intraday.py's intraday_tracker).
    """
    ts_raw = snapshot.get('time')
    if not ts_raw:
        return []
    nifty = snapshot.get('nifty')
    rows = []
    for symbol, d in (snapshot.get('stocks') or {}).items():
        price = d.get('price')
        if price is None:
            continue
        if symbol not in tracker:
            tracker[symbol] = {'high': price, 'low': price}
        else:
            tracker[symbol]['high'] = max(tracker[symbol]['high'], price)
            tracker[symbol]['low'] = min(tracker[symbol]['low'], price)
        rows.append({
            "ts": ts_raw.replace(' ', 'T') + "+05:30",
            "symbol": symbol,
            "ltp": price,
            "intraday_high": tracker[symbol]['high'],
            "intraday_low": tracker[symbol]['low'],
            "nifty_ltp": nifty,
        })
    return rows


def _read_jsonl(path, records, tracker):
    """Append rows from one JSONL file to `records`, expanding dashboard snapshots."""
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rec = json.loads(line)
                except:
                    continue
                if 'symbol' in rec:
                    records.append(rec)
                elif 'stocks' in rec:
                    records.extend(_expand_snapshot(rec, tracker))


def load_intraday_data(target_date=None):
    """Load intraday JSONL data for a given date into a DataFrame.

    Two writers produce intraday data, each in its own directory:
      data/intraday/   - intraday.py / scan_intraday.py (one row per stock per cycle)
      data/dashboard/  - dashboard.py                  (one snapshot per cycle)
    Both are read and merged; the row schema is used as-is, the snapshot schema
    is expanded into the same shape.
    """
    if target_date is None:
        target_date = date.today()
    date_str = target_date.strftime('%Y-%m-%d')

    data_files = [d / f"{date_str}.jsonl" for d in (DATA_DIR, DASHBOARD_DATA_DIR)]
    data_files = [f for f in data_files if f.exists()]
    if not data_files:
        logger.warning(f"No intraday data found for {date_str}")
        return None, []

    records = []
    tracker = {}
    for data_file in data_files:
        _read_jsonl(data_file, records, tracker)

    if not records:
        return None, []

    df = pd.DataFrame(records)
    df['ts'] = pd.to_datetime(df['ts'], format='ISO8601')
    df = df.sort_values('ts').reset_index(drop=True)

    # Pivot to get per-stock time series
    stocks = sorted(df['symbol'].unique())
    return df, stocks


def _normalize_signal(sig):
    """Normalise a signal dict to the keys the analyzer expects.

    Three writers exist with three shapes:
      scan_intraday.py: entry_price / sl_price / target_price / stock / type
      intraday.py:      entry / sl / target / symbol / signal_type
      dashboard.py:     entry / sl / target / symbol / type

    The type is canonicalised to start with LONG/SHORT because the outcome
    simulation branches on it — dashboard.py writes lowercase "long"/"short".
    """
    raw_type = sig.get('type') or sig.get('signal_type') or ''
    type_str = str(raw_type).upper()
    if type_str.startswith('LONG'):
        type_str = 'LONG'
    elif type_str.startswith('SHORT'):
        type_str = 'SHORT'
    return {
        'stock': sig.get('stock') or sig.get('symbol') or '',
        'type': type_str,
        'strategy': sig.get('strategy', ''),
        'time': sig.get('time') or sig.get('fired_at') or sig.get('timestamp') or '',
        'entry': sig.get('entry_price', sig.get('entry')),
        'target': sig.get('target_price', sig.get('target')),
        'sl': sig.get('sl_price', sig.get('sl')),
    }


def load_today_signals(target_date=None):
    """Load intraday signals for a given date from scan_intraday / intraday / dashboard output.

    Both writers are read and merged - intraday.py writes a list, dashboard.py writes
    a dict keyed by "{strategy}_{symbol}". A day where both fired keeps both sets.
    """
    if target_date is None:
        target_date = date.today()
    date_str = target_date.strftime('%Y-%m-%d')
    candidates = [
        SIGNALS_DIR / f"signals_live_{date_str}.json",
        DASHBOARD_SIGNALS_DIR / f"signals_live_{date_str}.json",
    ]

    merged = []
    seen = set()
    for signals_file in candidates:
        if not signals_file.exists():
            continue
        try:
            with open(signals_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except:
            continue
        if isinstance(data, dict):
            data = list(data.values())
        if not isinstance(data, list):
            continue
        for sig in data:
            if not isinstance(sig, dict):
                continue
            norm = _normalize_signal(sig)
            # Dedup on the fields that identify a distinct firing
            key = (norm['stock'], norm['type'], norm['time'], norm['strategy'])
            if key in seen:
                continue
            seen.add(key)
            merged.append(norm)
    return merged


def load_yesterday_daily_signals():
    """Load yesterday's daily scan signals."""
    yesterday = date.today() - timedelta(days=1)
    date_str = yesterday.strftime('%Y-%m-%d')
    signals_file = SIGNALS_DIR / f"signals_{date_str}.json"

    if not signals_file.exists():
        return None

    try:
        with open(signals_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except:
        return None


def compute_market_summary(df):
    """Compute daily market summary from intraday data."""
    if df is None or df.empty:
        return {}

    # Nifty data
    nifty = df[df['nifty_ltp'].notna()].copy()
    nifty_summary = {}
    if not nifty.empty:
        nifty_summary = {
            "first_ltp": float(nifty.iloc[0]['nifty_ltp']),
            "last_ltp": float(nifty.iloc[-1]['nifty_ltp']),
            "high": float(nifty['nifty_ltp'].max()),
            "low": float(nifty['nifty_ltp'].min()),
            "change_pct": float(nifty.iloc[-1]['nifty_ltp'] / nifty.iloc[0]['nifty_ltp'] - 1) * 100 if len(nifty) > 0 and nifty.iloc[0]['nifty_ltp'] else None,
        }

    # Per-stock summary
    stock_summary = {}
    for symbol in df['symbol'].unique():
        sd = df[df['symbol'] == symbol].sort_values('ts')
        if sd.empty:
            continue
        first_ltp = float(sd.iloc[0]['ltp']) if sd.iloc[0]['ltp'] else None
        last_ltp = float(sd.iloc[-1]['ltp']) if sd.iloc[-1]['ltp'] else None
        hi = float(sd['intraday_high'].max())
        lo = float(sd['intraday_low'].min())
        pc = sd.iloc[0].get('prev_close')

        stock_summary[symbol] = {
            "first_ltp": first_ltp,
            "last_ltp": last_ltp,
            "high": hi,
            "low": lo,
            "range_pct": round((hi - lo) / lo * 100, 2) if lo else None,
            "change_pct": round((last_ltp - first_ltp) / first_ltp * 100, 2) if first_ltp and last_ltp else None,
            "gap_pct": round((first_ltp - pc) / pc * 100, 2) if first_ltp and pc else None,
            "samples": len(sd),
        }

    return {
        "nifty": nifty_summary,
        "stocks": stock_summary,
        "total_samples": len(df),
        "trading_hours": f"{df['ts'].iloc[0].strftime('%H:%M') if len(df) > 0 else 'N/A'} — {df['ts'].iloc[-1].strftime('%H:%M') if len(df) > 0 else 'N/A'}",
    }


def evaluate_signal_outcome(symbol, signal, df):
    """Evaluate what happened to a signal during the day."""
    if df is None or df.empty:
        return {"status": "no_data"}

    sd = df[df['symbol'] == symbol].sort_values('ts')
    if sd.empty:
        return {"status": "no_data"}

    entry = signal.get('entry')
    target = signal.get('target')
    sl = signal.get('sl')
    sig_type = signal.get('type', '')

    if entry is None or target is None or sl is None:
        return {"status": "incomplete_signal"}

    ltp_series = sd['ltp'].dropna()
    if ltp_series.empty:
        return {"status": "no_ltp_data"}

    # Find when signal fired (use signal time or first data point)
    signal_time = signal.get('time', sd.iloc[0]['ts'].strftime('%H:%M:%S'))

    # Simulate: from signal entry, did price reach target, SL, or reverse?
    # We use the entry price as the starting point and check subsequent prices
    entry_reached = False
    target_reached = False
    sl_reached = False
    target_time = None
    sl_time = None
    final_ltp = float(ltp_series.iloc[-1])
    max_ltp = float(ltp_series.max())
    min_ltp = float(ltp_series.min())

    for idx, row in sd.iterrows():
        ltp = row['ltp']
        if ltp is None:
            continue
        if not entry_reached and abs(ltp - entry) / entry < 0.005:
            entry_reached = True
        if entry_reached:
            if sig_type.startswith('LONG'):
                if not target_reached and ltp >= target:
                    target_reached = True
                    target_time = row['ts'].strftime('%H:%M')
                if not sl_reached and ltp <= sl:
                    sl_reached = True
                    sl_time = row['ts'].strftime('%H:%M')
            else:  # SHORT
                if not target_reached and ltp <= target:
                    target_reached = True
                    target_time = row['ts'].strftime('%H:%M')
                if not sl_reached and ltp >= sl:
                    sl_reached = True
                    sl_time = row['ts'].strftime('%H:%M')

    # Determine outcome
    if target_reached:
        outcome = "HIT_TARGET"
    elif sl_reached:
        outcome = "HIT_SL"
    elif sig_type.startswith('LONG') and final_ltp < entry:
        outcome = "REVERSED"
    elif sig_type.startswith('SHORT') and final_ltp > entry:
        outcome = "REVERSED"
    else:
        outcome = "OPEN_AT_CLOSE"

    # Paper P&L (simplified)
    if sig_type.startswith('LONG'):
        pnl_pct = (final_ltp - entry) / entry * 100 if entry else None
    else:
        pnl_pct = (entry - final_ltp) / entry * 100 if entry else None

    return {
        "status": outcome,
        "entry": entry,
        "target": target,
        "sl": sl,
        "final_ltp": final_ltp,
        "day_high": max_ltp,
        "day_low": min_ltp,
        "target_reached": target_reached,
        "target_time": target_time,
        "sl_reached": sl_reached,
        "sl_time": sl_time,
        "pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else None,
        "samples_after_entry": len(sd[sd['ts'] >= sd.iloc[0]['ts']]),
    }


def analyze_signals(signals, df):
    """Analyze all signals that fired today."""
    results = []
    for sig in signals:
        symbol = sig.get('stock', '')
        outcome = evaluate_signal_outcome(symbol, sig, df)
        result = {
            "stock": symbol,
            "type": sig.get('type', ''),
            "strategy": sig.get('strategy', ''),
            "time_fired": sig.get('time', ''),
            "entry": sig.get('entry'),
            "target": sig.get('target'),
            "sl": sig.get('sl'),
            "outcome": outcome.get('status', 'unknown'),
            "final_ltp": outcome.get('final_ltp'),
            "pnl_pct": outcome.get('pnl_pct'),
            "target_reached": outcome.get('target_reached'),
            "sl_reached": outcome.get('sl_reached'),
            "day_high": outcome.get('day_high'),
            "day_low": outcome.get('day_low'),
        }
        results.append(result)
    return results


def generate_report(market_summary, signal_results, yesterday_daily):
    """Generate the full analysis report."""
    report = {
        "analysis_date": date.today().strftime('%Y-%m-%d'),
        "generated_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "market_summary": market_summary,
        "signals_fired": len(signal_results),
        "signal_results": signal_results,
        "signal_stats": {
            "total": len(signal_results),
            "hit_target": sum(1 for r in signal_results if r['outcome'] == 'HIT_TARGET'),
            "hit_sl": sum(1 for r in signal_results if r['outcome'] == 'HIT_SL'),
            "reversed": sum(1 for r in signal_results if r['outcome'] == 'REVERSED'),
            "open_at_close": sum(1 for r in signal_results if r['outcome'] == 'OPEN_AT_CLOSE'),
            "no_data": sum(1 for r in signal_results if r['outcome'] in ('no_data', 'unknown', 'incomplete_signal')),
        },
        "yesterday_daily_signals": yesterday_daily,
    }
    return report


def print_report(report):
    """Print human-readable report."""
    print()
    print("═" * 65)
    print("  END-OF-DAY ANALYSIS REPORT")
    print(f"  Date: {report['analysis_date']}")
    print(f"  Generated: {report['generated_at']}")
    print("═" * 65)

    # Market summary
    ms = report['market_summary']
    if ms:
        print("\n  📊 MARKET OVERVIEW")
        nifty = ms.get('nifty', {})
        if nifty:
            print(f"    Nifty: Open {nifty.get('first_ltp', 'N/A'):,.0f} → Close {nifty.get('last_ltp', 'N/A'):,.0f}")
            print(f"    Nifty Range: {nifty.get('low', 'N/A'):,.0f} — {nifty.get('high', 'N/A'):,.0f}")
            chg = nifty.get('change_pct')
            print(f"    Nifty Change: {chg:+.2f}%" if chg is not None else "    Nifty Change: N/A")
            regime = "BULLISH" if (chg or 0) > 0 else "BEARISH"
            print(f"    Regime: {regime}")

        print(f"\n    Per-Stock Summary ({len(ms.get('stocks', {}))} stocks):")
        for sym, data in sorted(ms.get('stocks', {}).items()):
            chg = data.get('change_pct')
            rng = data.get('range_pct')
            gap = data.get('gap_pct')
            chg_str = f"{chg:+.2f}%" if chg is not None else "N/A"
            rng_str = f"{rng:.1f}%" if rng is not None else "N/A"
            gap_str = f"{gap:+.2f}%" if gap is not None else "N/A"
            print(f"      {sym:<13} Close:{data.get('last_ltp', 'N/A')}  Range:{rng_str:>7}  Gap:{gap_str:>7}  Change:{chg_str:>7}  Samples:{data.get('samples', 0)}")

    # Signal results
    print(f"\n  ⚡ SIGNAL OUTCOMES ({report['signals_fired']} signals fired)")
    stats = report['signal_stats']
    print(f"    Hit Target: {stats['hit_target']} | Hit SL: {stats['hit_sl']} | Reversed: {stats['reversed']} | Open: {stats['open_at_close']} | No Data: {stats['no_data']}")

    if report['signal_results']:
        print(f"\n    Per-Signal Breakdown:")
        for r in report['signal_results']:
            outcome = r['outcome']
            pnl = r['pnl_pct']
            pnl_str = f"{pnl:+.2f}%" if pnl is not None else "N/A"
            print(f"      {r['stock']:<13} {r['type']:<20} Entry:{r['entry']} Target:{r['target']} SL:{r['sl']}")
            print(f"        Outcome: {outcome:<15} Final:{r['final_ltp']}  P&L(paper):{pnl_str:>8}")
            if r['target_reached']:
                print(f"        ✓ Target hit at {r.get('target_time', 'N/A')}")
            if r['sl_reached']:
                print(f"        ✗ SL hit at {r.get('sl_time', 'N/A')}")

    # Yesterday's daily signals reference
    if report.get('yesterday_daily_signals'):
        yds = report['yesterday_daily_signals']
        sigs = yds.get('signals', [])
        print(f"\n  📋 YESTERDAY'S DAILY SIGNALS (for reference)")
        if sigs:
            for s in sigs:
                print(f"      {s.get('stock', ''):<13} {s.get('type', '')} — {s.get('rationale', '')[:80]}")
        else:
            print("      No signals yesterday.")

    print("\n" + "═" * 65)
    print("  END OF REPORT")
    print("═" * 65)
    print()
    print("  → Save this report and share with AI for analysis.")
    print("  → AI will review outcomes, identify patterns, and suggest strategy changes.")


def main():
    target_date = date.today()  # Default: today's data

    # Allow --date flag for analyzing past days
    import argparse
    parser = argparse.ArgumentParser(description='End-of-Day Signal Analyzer')
    parser.add_argument('--date', type=str, default=None,
                        help='Date to analyze (YYYY-MM-DD). Default: today.')
    args = parser.parse_args()

    if args.date:
        try:
            target_date = datetime.strptime(args.date, '%Y-%m-%d').date()
        except:
            logger.error(f"Invalid date: {args.date}")
            print(f"Invalid date: {args.date}")
            sys.exit(1)

    logger.info(f"Analyzing intraday data for {target_date.strftime('%Y-%m-%d')}")

    # Load data
    df, stocks = load_intraday_data(target_date)
    signals = load_today_signals(target_date)
    yesterday_daily = load_yesterday_daily_signals()

    if df is None:
        print(f"No intraday data found for {target_date.strftime('%Y-%m-%d')}.")
        print("Was the collector running today?")
        sys.exit(1)

    # Compute summaries
    market_summary = compute_market_summary(df)
    signal_results = analyze_signals(signals, df)
    report = generate_report(market_summary, signal_results, yesterday_daily)

    # Save JSON report
    report_file = REPORTS_DIR / f"analysis_{target_date.strftime('%Y%m%d')}.json"
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    logger.info(f"Report saved: {report_file}")

    # Print human-readable report
    print_report(report)
    print(f"\n  JSON report: {report_file}")

    # Also save a machine-readable summary for AI consumption
    ai_summary = {
        "date": target_date.strftime('%Y-%m-%d'),
        "market": {
            "nifty_change_pct": market_summary.get('nifty', {}).get('change_pct'),
            "nifty_close": market_summary.get('nifty', {}).get('last_ltp'),
            "regime": "BULLISH" if (market_summary.get('nifty', {}).get('change_pct') or 0) > 0 else "BEARISH",
        },
        "signals": signal_results,
        "stats": report['signal_stats'],
        "yesterday_signals_count": len(yesterday_daily.get('signals', [])) if yesterday_daily else 0,
    }
    ai_file = REPORTS_DIR / f"ai_summary_{target_date.strftime('%Y%m%d')}.json"
    with open(ai_file, 'w', encoding='utf-8') as f:
        json.dump(ai_summary, f, indent=2, ensure_ascii=False)
    logger.info(f"AI summary saved: {ai_file}")
    print(f"  AI summary: {ai_file}")


if __name__ == '__main__':
    main()
