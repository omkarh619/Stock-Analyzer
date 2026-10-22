#!/usr/bin/env python
"""Quick smoke tests for visibility / feedback loop."""
import sys, os, time, logging
sys.path.insert(0, '.')
os.chdir('D:/OpenCode/Stock/Stock Analyzer')

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(name)s %(levelname)s %(message)s')

# 1. Module load
import dashboard
print("[PASS] Module loaded")

# 2. fetch_json visibility: call with bad URL should log FETCH_FAIL
print("\n[TEST] fetch_json bad URL -> expect FETCH_FAIL log")
dashboard.logger.info("--- TEST START fetch_json fail ---")
res = dashboard.fetch_json("http://invalid.local.invalid")
assert res is None
print("[PASS] fetch_json returned None for invalid URL; check log for FETCH_FAIL")

# 3. fetch_nse_ltp visibility: expect NSE_LTP_START / attempt logs / fail
print("\n[TEST] fetch_nse_ltp('NIFTY') -> expect NSE_LTP_START / attempts / possibly OK or FAIL")
dashboard.logger.info("--- TEST START fetch_nse_ltp ---")
val = dashboard.fetch_nse_ltp("NIFTY")
print(f"[INFO] fetch_nse_ltp('NIFTY') returned={val} (None is OK if NSE down)")
if val is not None:
    print(f"[PASS] Price fetched: {val}")
else:
    print("[PASS] Returned None — check logs for NSE_LTP_FAIL or retries")

dashboard.logger.info("--- ALL TESTS COMPLETE ---")
print("\n[DONE] All smoke tests finished. Check logs/dashboard_*.log and console for FETCH_START / FETCH_OK / FETCH_FAIL / NSE_LTP_*.")
