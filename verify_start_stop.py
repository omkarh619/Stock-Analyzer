# Quick verification script for the start/stop flow
# This checks UI state transitions and server responses

# Expected state transitions:
# 1. dashboard loads: STATE.running=False, btnStart.enabled=True, btnStop.disabled=True, status="Stopped"
# 2. Click start: POST /api/start → {"status":"started"}, STATE.running=True
# 3. After start: btnStart.disabled=True, btnStop.enabled=True, status="Running"
# 4. Click stop: POST /api/stop → {"status":"stopped"}, STATE.running=False
# 5. After stop: btnStart.enabled=True, btnStop.disabled=True, status="Stopped"

# The current issue reported: clicking start doesn't change button states.
# This suggests the /api/start request succeeds but either:
# A) STATE.running is not actually set to True (check server code)
# B) The status response doesn't include running=True properly
# C) The refresh() doesn't pick up the new state

# Note: There is a known issue in dashboard.py line 850:
# A dead return line exists after the /api/start handler (line 849-850):
#     return
#     self._send_json(200, {"status": "stopped"})
# This unreachable line is harmless but indicates the code may have had edits.
# More importantly, check if there's a missing /api/stop endpoint — the JS calls api('stop')
# but the server code only handles "/api/start", not "/api/stop".
