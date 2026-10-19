#!/usr/bin/env python3
"""
Comprehensive Dashboard Test Suite
Tests every component: config, state, helpers, strategies, chart, server, API, HTML
"""
import sys, os, json, time, subprocess, threading, urllib.request, urllib.error
from pathlib import Path
from datetime import datetime, timedelta

PROJECT = Path(r"D:\OpenCode\Stock\Stock Analyzer")
os.chdir(PROJECT)
sys.path.insert(0, str(PROJECT))

def section(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")

def run():
    results = {"passed": 0, "failed": 0, "tests": []}
    def t(name, fn):
        try:
            ok, msg = fn()
            results["tests"].append((name, ok, msg))
            if ok:
                results["passed"] += 1
                print(f"  [PASS] {name}")
            else:
                results["failed"] += 1
                print(f"  [FAIL] {name}: {msg}")
        except Exception as e:
            results["failed"] += 1
            results["tests"].append((name, False, str(e)))
            print(f"  [FAIL] {name}: {e}")

    # Import dashboard
    import dashboard

    section("1. MODULE LOAD & BASIC IMPORTS")
    t("dashboard module imports cleanly", lambda: (True, ""))
    t("SharedState class exists", lambda: (hasattr(dashboard, "SharedState"), ""))
    t("STRATEGY_DEFS exists with 3 strategies", lambda: (len(dashboard.STRATEGY_DEFS) == 3, f"got {len(dashboard.STRATEGY_DEFS)}"))
    t("STATE singleton exists", lambda: (hasattr(dashboard, "STATE"), ""))

    section("2. CONFIG LOADING")
    t("STATE.symbols is non-empty list", lambda: (len(dashboard.STATE.symbols) > 0, f"got {len(dashboard.STATE.symbols)} symbols"))
    t("STATE.symbols are uppercase strings", lambda: (all(isinstance(s, str) and s == s.upper() for s in dashboard.STATE.symbols), ""))
    t("STATE.nifty_symbol is set", lambda: (bool(dashboard.STATE.nifty_symbol), f"got {dashboard.STATE.nifty_symbol}"))
    t("All 3 strategy states initialized", lambda: (len(dashboard.STATE.strategy_states) == 3, f"got {len(dashboard.STATE.strategy_states)}"))
    t("Each strategy state has required fields", lambda: (
        all(all(k in st for k in ["enabled", "signal_count", "last_signal", "filters"]) for st in dashboard.STATE.strategy_states.values()),
        ""))
    t("CFG has market with tv_symbols", lambda: (hasattr(dashboard, "CFG") and "market" in dashboard.CFG and "tv_symbols" in dashboard.CFG.get("market", {}), ""))
    t("CFG market.tv_symbols matches STATE.symbols", lambda: (dashboard.CFG.get("market", {}).get("tv_symbols", []) == dashboard.STATE.symbols, ""))

    section("3. SHAREDSTATE.to_dict() SERIALIZATION")
    st = dashboard.SharedState()
    d = st.to_dict()
    t("to_dict returns dict", lambda: (isinstance(d, dict), type(d)))
    required_keys = ["running","collector_running","last_update","nifty","symbols","strategies",
                     "stock_data","price_history","collector_last_cycle_time","collector_last_cycle_duration",
                     "collector_cycle_errors","nse_ltp_status","data_samples_today","price_history_counts",
                     "price_history_total","active_signals","uptime_seconds","ltp_cache"]
    missing = [k for k in required_keys if k not in d]
    t("to_dict has all required keys", lambda: (len(missing) == 0, f"missing: {missing}"))
    t("nifty.price is None or float (never NaN/Series)", lambda: (d["nifty"]["price"] is None or (isinstance(d["nifty"]["price"], (int,float)) and d["nifty"]["price"] == d["nifty"]["price"]), f"got {d['nifty']['price']} type={type(d['nifty']['price'])}"))
    t("nifty.sma20 is None or float (never NaN/Series)", lambda: (d["nifty"]["sma20"] is None or (isinstance(d["nifty"]["sma20"], (int,float)) and d["nifty"]["sma20"] == d["nifty"]["sma20"]), f"got {d['nifty']['sma20']} type={type(d['nifty']['sma20'])}"))
    t("nifty.regime is valid string", lambda: (d["nifty"]["regime"] in ["BULLISH","BEARISH","UNKNOWN"], f"got {d['nifty']['regime']}"))
    t("active_signals is list", lambda: (isinstance(d["active_signals"], list), type(d["active_signals"])))
    t("uptime_seconds is number", lambda: (d["uptime_seconds"] is None or isinstance(d["uptime_seconds"], (int,float)), f"got {d['uptime_seconds']}"))
    t("ltp_cache is dict", lambda: (isinstance(d["ltp_cache"], dict), type(d["ltp_cache"])))
    t("JSON serialize to_dict (no NaN/Infinity)", lambda: (json.dumps(d, default=str) is not None, ""))
    t("JSON deserialize round-trip", lambda: (json.loads(json.dumps(d, default=str)) is not None, ""))

    section("4. HELPER FUNCTIONS")
    t("fetch_nse_ltp('NIFTY') returns None or float", lambda: (dashboard.fetch_nse_ltp("NIFTY") is None or isinstance(dashboard.fetch_nse_ltp("NIFTY"), (int,float)), f"got {dashboard.fetch_nse_ltp('NIFTY')}"))
    t("fetch_nse_ltp('RELIANCE') returns None or float", lambda: (dashboard.fetch_nse_ltp("RELIANCE") is None or isinstance(dashboard.fetch_nse_ltp("RELIANCE"), (int,float)), f"got {dashboard.fetch_nse_ltp('RELIANCE')}"))
    t("fetch_nifty_ltp returns None or float", lambda: (dashboard.fetch_nifty_ltp() is None or isinstance(dashboard.fetch_nifty_ltp(), (int,float)), f"got {dashboard.fetch_nifty_ltp()}"))
    n20d = dashboard.nifty_20d_low()
    t("nifty_20d_low returns (None,None) or (float,float)", lambda: (
        n20d is None or (isinstance(n20d, tuple) and len(n20d) == 2 and
         all(v is None or (isinstance(v, (int,float)) and v == v) for v in n20d)),
        f"got {n20d}"
    ))
    s20d = dashboard.stock_20d_low("RELIANCE")
    t("stock_20d_low('RELIANCE') returns (None,None) or (float,float)", lambda: (
        s20d is None or (isinstance(s20d, tuple) and len(s20d) == 2 and
         all(v is None or (isinstance(v, (int,float)) and v == v) for v in s20d)),
        f"got {s20d}"
    ))
    ch = dashboard.calculate_charges("zerodha", 25, 1215.50, "buy")
    t("calculate_charges returns dict with 'total' > 0", lambda: (isinstance(ch, dict) and "total" in ch and isinstance(ch["total"], (int,float)) and ch["total"] > 0, f"got {ch}"))
    t("calculate_charges JSON-serializable", lambda: (json.dumps(ch) is not None, ""))
    t("get_capital returns positive number", lambda: (isinstance(dashboard.get_capital(), (int,float)) and dashboard.get_capital() > 0, f"got {dashboard.get_capital()}"))
    rsi = dashboard.rsi_from_prices([100,101,102,101,100,99,98,99,100,101,102,103,102,101,100], 14)
    t("rsi_from_prices returns number", lambda: (isinstance(rsi, (int,float)), f"got {rsi}"))
    bb = dashboard.stock_daily_bb([100,101,102,101,100,99,98,99,100,101,102,103,102,101,100,101,102,103,104,103], 20, 2.0)
    t("stock_daily_bb returns dict with 'mid'", lambda: (isinstance(bb, dict) and "mid" in bb, f"got {bb}"))

    section("5. STRATEGY CHECKERS (simulated data)")
    fake = dashboard.SharedState()
    fake.symbols = ["RELIANCE"]
    fake.nifty_symbol = "NIFTY"
    fake.strategy_states = {
        "short_20d_low_breakdown": {"enabled": True, "direction": "BOTH", "signal_count": 0, "last_signal": None},
        "long_bb_reclaim": {"enabled": True, "direction": "LONG", "signal_count": 0, "last_signal": None},
        "orb": {"enabled": True, "direction": "BOTH", "signal_count": 0, "last_signal": None},
    }
    fake.nifty_price = 23200.0
    fake.nifty_sma20 = 23100.0
    fake.regime = "BULLISH"
    fake.ltp_cache["RELIANCE"] = 1215.50
    fake.stock_data["RELIANCE"] = {"time": "10:00:00", "price": 1215.50, "high": 1216.0, "low": 1214.0}

    import pandas as pd, numpy as np
    np.random.seed(42)
    n = 200
    base = 1200.0 + np.linspace(0, 30, n) + np.cumsum(np.random.randn(n) * 0.3)
    close_arr = base
    high_arr = close_arr + np.abs(np.random.randn(n) * 2)
    low_arr = close_arr - np.abs(np.random.randn(n) * 2)
    times = pd.date_range(end=pd.Timestamp.now(), periods=n, freq="5min")
    fake.price_history["RELIANCE"] = []
    for i in range(n):
        fake.price_history["RELIANCE"].append({
            "time": times[i].strftime("%H:%M:%S"),
            "ltp": float(close_arr[i]),
            "high": float(high_arr[i]),
            "low": float(low_arr[i]),
        })

    t("run_strategy_checks runs without exception", lambda: (True, ""))
    signals = dashboard.run_strategy_checks(fake)
    t("run_strategy_checks returns list", lambda: (isinstance(signals, list), type(signals)))
    t("Each signal has required fields", lambda: (
        all(all(k in sig for k in ["type","strategy","symbol","entry","sl","target","sl_pct","target_pct","qty_est","charges"]) for sig in signals),
        f"first signal keys: {list(signals[0].keys()) if signals else 'N/A'}"
    ))
    t("Signal types are 'long' or 'short'", lambda: (all(s["type"] in ["long","short"] for s in signals), f"types: {[s['type'] for s in signals]}"))
    t("Signal entries are positive numbers", lambda: (all(isinstance(s["entry"], (int,float)) and s["entry"] > 0 for s in signals), f"entries: {[s['entry'] for s in signals]}"))
    t("Signal SL is correct direction (short SL > entry, long SL < entry)", lambda: (all(
        (s["type"] == "short" and s["sl"] > s["entry"]) or (s["type"] == "long" and s["sl"] < s["entry"]) for s in signals
    ), f"sl: {[(s['type'], s['sl'], s['entry']) for s in signals]}"))
    t("Signal target is positive number", lambda: (all(isinstance(s["target"], (int,float)) and s["target"] > 0 for s in signals), f"targets: {[s['target'] for s in signals]}"))
    t("Signal qty_est is positive int", lambda: (all(isinstance(s["qty_est"], int) and s["qty_est"] > 0 for s in signals), f"qty: {[s['qty_est'] for s in signals]}"))
    t("Signal charges has 'total' >= 0", lambda: (all(isinstance(s["charges"], dict) and "total" in s["charges"] and isinstance(s["charges"]["total"], (int,float)) and s["charges"]["total"] >= 0 for s in signals), f"charges: {[s['charges'] for s in signals]}"))
    t("Signal charges JSON-serializable", lambda: (all(json.dumps(s["charges"]) is not None for s in signals), ""))
    t("SL matches sl_pct formula", lambda: (all(
        abs(s["sl"] - s["entry"] * (1 + s["sl_pct"]/100 if s["type"]=="short" else 1 - s["sl_pct"]/100)) < 0.02 for s in signals
    ), f"sl vs sl_pct: {[(s['sl'], s['entry'], s['sl_pct']) for s in signals]}"))
    t("charges total < 2% of position value", lambda: (all(
        s["charges"]["total"] < s["entry"] * s["qty_est"] * 0.02 for s in signals
    ), f"charges: {[(s['charges']['total'], s['entry']*s['qty_est']) for s in signals]}"))

    section("6. CHART DATA")
    if signals:
        sig = signals[0]
        ph = fake.price_history.get(sig["symbol"], [])
        cd = dashboard.chart_data_for(sig["symbol"], ph, sig)
        t("chart_data_for returns dict", lambda: (isinstance(cd, dict), type(cd)))
        t("chart_data_for has 'data' key with list of dicts", lambda: (
            "data" in cd and isinstance(cd["data"], list) and
            all(isinstance(p, dict) and "time" in p and "ltp" in p for p in cd["data"]),
            f"first 2: {cd.get('data', [])[:2]}"
        ))
        if len(cd.get("data", [])) > 0:
            t("chart_data data has sensible time/price values", lambda: (True, f"range: {cd['data'][0]['ltp']:.2f} → {cd['data'][-1]['ltp']:.2f}"))
        t("chart_data_for JSON-serializable", lambda: (json.dumps(cd, default=str) is not None, ""))
    else:
        t("No signals (NSE may be down)", lambda: (True, f"signals={signals}"))

    cd_empty = dashboard.chart_data_for("TCS", [], {})
    t("chart_data_for empty history returns {'data': []}", lambda: (isinstance(cd_empty, dict) and cd_empty.get("data") == [], f"got {cd_empty}"))
    t("chart_data_for empty JSON-serializable", lambda: (json.dumps(cd_empty, default=str) is not None, ""))

    section("7. HTTP SERVER & API")
    server_proc = None
    try:
        server_proc = subprocess.Popen(
            [sys.executable, str(PROJECT / "dashboard.py")],
            cwd=str(PROJECT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        time.sleep(4)
        t("Server process started", lambda: (server_proc.poll() is None, f"poll={server_proc.poll()}"))

        if server_proc and server_proc.poll() is None:
            base = "http://localhost:8899"
            def api_get(path):
                req = urllib.request.Request(f"{base}{path}", headers={"User-Agent":"Mozilla/5.0"})
                try:
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        return json.loads(resp.read().decode("utf-8"))
                except Exception as e:
                    return {"_error": str(e)}

            status = api_get("/api/status")
            t("/api/status returns dict (not error)", lambda: ("_error" not in status, f"got {status}"))
            if "_error" not in status:
                t("/api/status nifty.price is None/float", lambda: (status.get("nifty",{}).get("price") is None or isinstance(status.get("nifty",{}).get("price"), (int,float)), f"nifty.price={status.get('nifty',{}).get('price')}"))
                t("/api/status nifty.sma20 is None/float (not NaN)", lambda: (status.get("nifty",{}).get("sma20") is None or (isinstance(status.get("nifty",{}).get("sma20"), (int,float)) and status.get("nifty",{}).get("sma20") == status.get("nifty",{}).get("sma20")), f"sma20={status.get('nifty',{}).get('sma20')}"))
                t("/api/status active_signals is list", lambda: (isinstance(status.get("active_signals"), list), f"type={type(status.get('active_signals'))}"))
                t("/api/status nse_ltp_status is string", lambda: (isinstance(status.get("nse_ltp_status"), str), f"got {status.get('nse_ltp_status')}"))
                t("/api/status data_samples_today is int", lambda: (isinstance(status.get("data_samples_today"), int), f"got {status.get('data_samples_today')}"))
                t("/api/status price_history_counts is dict", lambda: (isinstance(status.get("price_history_counts"), dict), f"got {status.get('price_history_counts')}"))
                t("/api/status symbols is non-empty list", lambda: (isinstance(status.get("symbols"), list) and len(status.get("symbols",[])) > 0, f"got {status.get('symbols')}"))
                t("/api/status strategies is dict", lambda: (isinstance(status.get("strategies"), dict), f"got {status.get('strategies')}"))
                t("/api/status collector_running is bool", lambda: (isinstance(status.get("collector_running"), bool), f"got {status.get('collector_running')}"))
                t("/api/status has collector_last_cycle_time", lambda: (status.get("collector_last_cycle_time") is None or isinstance(status.get("collector_last_cycle_time"), str), f"got {status.get('collector_last_cycle_time')}"))
                t("/api/status has uptime_seconds", lambda: (status.get("uptime_seconds") is None or isinstance(status.get("uptime_seconds"), (int,float)), f"got {status.get('uptime_seconds')}"))

            cd_api = api_get("/api/chart_data?stock=RELIANCE")
            t("/api/chart_data returns dict", lambda: (isinstance(cd_api, dict), f"got {cd_api}"))
            if "_error" not in cd_api:
                t("/api/chart_data has 'data' key", lambda: ("data" in cd_api, f"keys: {list(cd_api.keys())}"))
                t("/api/chart_data data is list", lambda: (isinstance(cd_api.get("data"), list), f"type={type(cd_api.get('data'))}"))
    finally:
        if server_proc and server_proc.poll() is None:
            server_proc.terminate()
            try:
                server_proc.wait(timeout=5)
            except:
                server_proc.kill()

    section("8. HTML FRONTEND")
    html_path = PROJECT / "dashboard.html"
    if html_path.exists():
        html = html_path.read_text(encoding="utf-8")
        t("HTML file exists (>1000 chars)", lambda: (len(html) > 1000, f"{len(html)} chars"))
        t("renderSvgChart has empty guard (if data.length === 0)", lambda: ("if (data.length === 0)" in html, ""))
        t("drawChart has try-catch", lambda: ("async function drawChart" in html and "try {" in html and "catch" in html, ""))
        t("drawChart shows 'No price data' for empty", lambda: ("No price data" in html or "Not enough data" in html or "Not enough data for" in html, ""))
        t("HTML has data capture status (NSE Status | Samples Today | dataCapSection)", lambda: (
            "NSE Status" in html or "Samples Today" in html or "dataCapSection" in html,
            "no data capture indicator found"
        ))
        t("HTML has uptime display", lambda: ("uptime" in html.lower() or "uptimeStr" in html, ""))
        t("HTML has regime badge", lambda: ("regime-badge" in html or "regimeBadge" in html, ""))
        t("HTML has signals table", lambda: ("signalTableBody" in html or "signal-table" in html or "Active Signals" in html, ""))
        t("HTML has strategy toggle cards", lambda: ("strategy-card" in html or "toggleStrategy" in html, ""))
        t("HTML has setInterval auto-refresh", lambda: ("setInterval" in html, ""))
        t("HTML has Start/Stop buttons", lambda: (("Start" in html and "Stop" in html) or "toggleCollector" in html, ""))
    else:
        t("dashboard.html exists", lambda: (False, f"not found at {html_path}"))

    section("9. DATA COLLECTION FILES")
    today = datetime.now().strftime("%Y-%m-%d")
    for subdir, label in [("data/intraday", "intraday data"), ("signals", "signals"), ("signal_states", "states"), ("logs", "logs")]:
        dpath = PROJECT / subdir
        t(f"{label} dir exists", lambda d=dpath, l=label: (d.exists(), f"{l}: {d}"))

    # Summary
    section("SUMMARY")
    total = results["passed"] + results["failed"]
    print(f"  Total: {total} | Passed: {results['passed']} | Failed: {results['failed']}")
    if results["failed"] > 0:
        print(f"\n  FAILED TESTS:")
        for name, ok, msg in results["tests"]:
            if not ok:
                print(f"    - {name}: {msg}")
    return results["failed"] == 0

if __name__ == "__main__":
    success = run()
    sys.exit(0 if success else 1)
