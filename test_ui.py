"""UI Test for Stock Analyzer Dashboard"""
import urllib.request
import json
import os
import sys

BASE = "http://localhost:8899"
sys.path.insert(0, ".")
os.chdir(".")

results = []

def check(name, condition):
    results.append((name, condition))
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {name}")
    return condition

print("=" * 60)
print("UI TEST: Stock Analyzer Dashboard")
print("=" * 60)

# 1. Server is running
try:
    req = urllib.request.Request(f"{BASE}/", headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        html = resp.read().decode()
    check("Server is running on port 8899", True)
    print(f"    HTML length: {len(html)} chars")
except Exception as e:
    check("Server is running on port 8899", False)
    print(f"    ERROR: {e}")
    html = ""

# 2. API status
try:
    req = urllib.request.Request(f"{BASE}/api/status", headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        d = json.loads(resp.read().decode())
    check("API /api/status responds", True)
    print(f"    Nifty: price={d.get('nifty', {}).get('price')}, source={d.get('nifty', {}).get('source', 'MISSING')}")
    print(f"    Symbols: {len(d.get('symbols', []))}")
    print(f"    Strategies: {list(d.get('strategies', {}).keys())}")
    print(f"    Active signals: {len(d.get('active_signals', []))}")
except Exception as e:
    check("API /api/status responds", False)
    print(f"    ERROR: {e}")

# 3. HTML UI components
check("renderStrategyCards function exists", "function renderStrategyCards" in html)
check("renderInstrumentCards function exists", "function renderInstrumentCards" in html)
check("Both called from renderAll", "renderStrategyCards(s)" in html and "renderInstrumentCards(s)" in html)
check("strategyCards container exists", "id=\"strategyCards\"" in html)
check("instrumentCards container exists", "id=\"instrumentCards\"" in html)
check("strategy-card-main CSS", ".strategy-card-main" in html)
check("instrument-card CSS", ".instrument-card" in html)
check("Cache-control no-cache", "no-cache" in html)
check("niftyDelayBadge in HTML", "niftyDelayBadge" in html)
check("drawChart function", "function drawChart" in html)
check("renderSvgChart function", "function renderSvgChart" in html)
check("chart_data handler", "chart_data" in html)

# 4. Strategy/instrument card counts
strat_count = html.count("strategy-card-main")
inst_count = html.count("instrument-card")
check(f"strategy-card-main occurrences: {strat_count}", strat_count >= 3)
check(f"instrument-card occurrences: {inst_count}", inst_count >= 1)

# 5. Nifty in API (live from NSE, 'delayed' if yfinance fallback was used)
nf = d.get("nifty", {})
check("Nifty price present", nf.get("price") is not None)
check("Nifty has source field", "source" in nf)
check(f"Nifty source is 'live' or 'delayed'", nf.get("source") in ("live", "delayed"))

# 6. Collector status
check("Collector running", d.get("collector_running") == True)
check("Server running", d.get("running") == True)

print()
print("=" * 60)
passed = sum(1 for _, ok in results if ok)
total = len(results)
print(f"RESULT: {passed}/{total} tests passed")
print("=" * 60)

if passed < total:
    print("\nFAILED TESTS:")
    for name, ok in results:
        if not ok:
            print(f"  - {name}")

print(f"\n{'='*60}")
print(f"FINAL RESULT: {passed}/{total} tests passed")
print(f"{'='*60}")