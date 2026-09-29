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
SIGNALS_DIR = PROJECT_DIR / "signals"
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


def load_intraday_data(target_date=None):
    """Load intraday JSONL data for a given date into a DataFrame."""
    if target_date is None:
        target_date = date.today()
    date_str = target_date.strftime('%Y-%m-%d')
    data_file = DATA_DIR / f"{date_str}.jsonl"

    if not data_file.exists():
        logger.warning(f"No intraday data found for {date_str}")
        return None, []

    records = []
    with open(data_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except:
                    pass

    if not records:
        return None, []

    df = pd.DataFrame(records)
    df['ts'] = pd.to_datetime(df['ts'])
    df = df.sort_values('ts').reset_index(drop=True)

    # Pivot to get per-stock time series
    stocks = sorted(df['symbol'].unique())
    return df, stocks


def load_today_signals():
    """Load today's intraday signals from scan_intraday output."""
    today_str = date.today().strftime('%Y%m%d')
    signals_file = SIGNALS_DIR / f"signals_live_{today_str}.json"

    if not signals_file.exists():
        return []

    try:
        with open(signals_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except:
        return []


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

    entry = signal.get('entry_price')
    target = signal.get('target_price')
    sl = signal.get('sl_price')
    sig_type = signal.get('type', '')

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
            "entry": sig.get('entry_price'),
            "target": sig.get('target_price'),
            "sl": sig.get('sl_price'),
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
            "no_data": sum(1 for r in signal_results if r['outcome'] in ('no_data', 'unknown')),
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
    signals = load_today_signals() if target_date == date.today() else []
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
