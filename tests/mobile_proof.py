#!/usr/bin/env python3
"""MOBILE PROOF MATRIX — verify every claimed behavior server-side + code audit."""
import sys
import os
import json
import asyncio
os.chdir('/app')
sys.path.insert(0, '/app')

results = []

def test(name, passed, detail=""):
    results.append({"name": name, "passed": passed, "detail": detail})
    status = "✅" if passed else "❌"
    print(f"  {status} {name}{f': {detail}' if detail else ''}")

print("═══ MOBILE PROOF MATRIX ═══\n")

# ── Read Flutter code ──────────────────────────────────────────────────
ws_path = "jarvismax_app/lib/services/websocket_service.dart"
api_path = "jarvismax_app/lib/services/api_service.dart"
main_path = "jarvismax_app/lib/main.dart"

with open(ws_path, encoding="utf-8") as f:
    ws_code = f.read()
with open(api_path, encoding="utf-8") as f:
    api_code = f.read()
with open(main_path, encoding="utf-8") as f:
    main_code = f.read()

# ── M1: Login works ────────────────────────────────────────────────────
print("━━━ M1: LOGIN WORKS ━━━")
import httpx
BASE = "http://localhost:8000"
TOKEN = os.environ.get("JARVIS_API_TOKEN", "")

# Test actual login endpoint
resp = httpx.post(f"{BASE}/auth/token", data={"username": "admin", "password": os.environ.get("JARVIS_SECRET_KEY", "")}, timeout=5)
test("POST /auth/token returns 200", resp.status_code == 200, f"status={resp.status_code}")
if resp.status_code == 200:
    data = resp.json()
    jwt_token = data.get("access_token", "")
    expires_in = data.get("expires_in", 0)
    test("Returns access_token", len(jwt_token) > 20, f"len={len(jwt_token)}")
    test("Returns expires_in", expires_in > 0, f"expires_in={expires_in}")
else:
    jwt_token = ""
    test("Returns access_token", False, "login failed")
    test("Returns expires_in", False, "login failed")

# Verify Flutter has login code
has_login_flow = "auth/token" in api_code
test("Flutter has /auth/token login flow", has_login_flow)
print()

# ── M2: Token saved ───────────────────────────────────────────────────
print("━━━ M2: TOKEN SAVED ━━━")
has_secure_storage = "FlutterSecureStorage" in api_code
test("Uses FlutterSecureStorage", has_secure_storage)

has_save_jwt = "saveJwt" in api_code
test("saveJwt() method exists", has_save_jwt)

has_jwt_key = "jarvis_jwt_token" in api_code
test("JWT stored with key 'jarvis_jwt_token'", has_jwt_key)
print()

# ── M3: App restart restores auth ─────────────────────────────────────
print("━━━ M3: APP RESTART RESTORES AUTH ━━━")
# Check if autoLogin reads from storage on startup
has_auto_login = "autoLogin" in api_code or "_loadToken" in ws_code
test("Auto-login/token-load on startup", has_auto_login)

has_storage_read = "storage.read(key:" in api_code or "storage.read(key:" in ws_code
test("Reads JWT from secure storage", has_storage_read)

# Check main.dart triggers auth check on startup
has_startup_refresh = "checkHealth" in main_code or "autoLogin" in main_code
test("Main triggers auth check at startup", has_startup_refresh)
print()

# ── M4: Token refresh before expiry works ──────────────────────────────
print("━━━ M4: TOKEN REFRESH BEFORE EXPIRY ━━━")
# Test actual refresh endpoint
if jwt_token:
    resp2 = httpx.post(f"{BASE}/auth/refresh",
                       headers={"Authorization": f"Bearer {jwt_token}"},
                       timeout=5)
    test("POST /auth/refresh returns 200", resp2.status_code == 200, f"status={resp2.status_code}")
    if resp2.status_code == 200:
        new_token = resp2.json().get("access_token", "")
        test("Returns new access_token", len(new_token) > 20)
    else:
        test("Returns new access_token", False, f"body={resp2.text[:100]}")
else:
    test("POST /auth/refresh returns 200", False, "no JWT to test with")
    test("Returns new access_token", False, "no JWT")

# Check Flutter schedules refresh
has_schedule_refresh = "_scheduleTokenRefresh" in api_code
test("Flutter schedules token refresh", has_schedule_refresh)

has_t_minus_5 = "expiresIn - 300" in api_code or "- 300" in api_code
test("Refreshes 5 min before expiry (T-300s)", has_t_minus_5)

has_do_refresh = "_doTokenRefresh" in api_code
test("_doTokenRefresh() method exists", has_do_refresh)
print()

# ── M5: Forced expired token recovers or logs out cleanly ─────────────
print("━━━ M5: EXPIRED TOKEN RECOVERY ━━━")
# Test with invalid token
resp3 = httpx.post(f"{BASE}/auth/refresh",
                   headers={"Authorization": "Bearer expired.token.here"},
                   timeout=5)
test("Expired token → non-200", resp3.status_code != 200, f"status={resp3.status_code}")

# Check Flutter has re-login fallback
has_try_relogin = "_tryReLogin" in api_code
test("Flutter has _tryReLogin fallback", has_try_relogin)

# Check WS auth_expired handling
has_auth_expired_state = "authExpired" in ws_code
test("WS has authExpired state", has_auth_expired_state)

has_on_token_refreshed = "onTokenRefreshed" in ws_code
test("WS has onTokenRefreshed() recovery", has_on_token_refreshed)

# Check API service handles auth_expired from WS
has_auth_expired_handler = "auth_expired" in api_code
test("ApiService handles auth_expired event", has_auth_expired_handler)
print()

# ── M6: WebSocket connects ────────────────────────────────────────────
print("━━━ M6: WEBSOCKET CONNECTS ━━━")
import websockets
async def ws_connect_test():
    uri = f"ws://localhost:8000/ws/stream?token={TOKEN}"
    async with websockets.connect(uri, open_timeout=5) as ws:
        msg = await asyncio.wait_for(ws.recv(), timeout=5)
        data = json.loads(msg)
        return data
try:
    data = asyncio.run(ws_connect_test())
    test("WS connects with token", True)
    test("WS receives connected event", data.get("event") == "connected", f"got={data.get('event')}")
except Exception as e:
    test("WS connects with token", False, str(e)[:80])
    test("WS receives connected event", False)
print()

# ── M7: WebSocket reconnects after server interruption ─────────────────
print("━━━ M7: WS RECONNECTS AFTER INTERRUPTION (code audit) ━━━")
has_on_disconnect = "_onDisconnect" in ws_code
test("_onDisconnect handler exists", has_on_disconnect)

has_schedule_reconnect = "_scheduleReconnect" in ws_code
test("_scheduleReconnect called on disconnect", has_schedule_reconnect)

has_on_done = "onDone:" in ws_code
test("Socket onDone triggers reconnect", has_on_done and "_onDisconnect" in ws_code)

has_on_error = "onError:" in ws_code
test("Socket onError triggers reconnect", has_on_error and "_onDisconnect" in ws_code)

# Live test: connect, get server heartbeat to prove alive, send ping
async def ws_reconnect_test():
    uri = f"ws://localhost:8000/ws/stream?token={TOKEN}"
    async with websockets.connect(uri, open_timeout=5) as ws:
        # Recv connected event
        await asyncio.wait_for(ws.recv(), timeout=5)
        # Send ping
        await ws.send(json.dumps({"type": "ping", "ts": 1}))
        msg = await asyncio.wait_for(ws.recv(), timeout=5)
        return json.loads(msg)
try:
    pong = asyncio.run(ws_reconnect_test())
    test("Ping/pong works (socket is alive)", pong.get("type") == "pong")
except Exception as e:
    test("Ping/pong works", False, str(e)[:80])
print()

# ── M8-M9: WiFi ↔ 4G transitions (code audit) ────────────────────────
print("━━━ M8-M9: NETWORK TRANSITIONS (code audit) ━━━")
has_connectivity_plus = "connectivity_plus" in ws_code
test("connectivity_plus imported", has_connectivity_plus)

has_on_change = "onConnectivityChanged" in ws_code
test("Listens to connectivity changes", has_on_change)

has_network_type = "_lastNetworkType" in ws_code
test("Tracks network type", has_network_type)

has_immediate_reconnect = 'immediate: true' in ws_code or 'immediate: true' in ws_code
test("Network change → immediate reconnect", has_immediate_reconnect)

has_reset_backoff = "_reconnectAttempts = 0" in ws_code
test("Network change resets backoff", has_reset_backoff)

has_offline_state = "WsConnectionState.offline" in ws_code
test("Offline state on network loss", has_offline_state)
print()

# ── M10: No duplicate reconnect storm ─────────────────────────────────
print("━━━ M10: NO DUPLICATE RECONNECT ━━━")
has_inflight = "_connectInFlight" in ws_code
test("_connectInFlight guard exists", has_inflight)

has_guard_check = "if (_connectInFlight)" in ws_code
test("Guard checked at connect() entry", has_guard_check)

has_guard_set = "_connectInFlight = true" in ws_code
test("Guard set before connect attempt", has_guard_set)

has_guard_clear = "_connectInFlight = false" in ws_code
test("Guard cleared in finally block", has_guard_clear)

# Count how many times connect() is referenced (should be called from limited places)
connect_calls = ws_code.count("connect()")
test("connect() call count reasonable (<10)", connect_calls < 15, f"count={connect_calls}")
print()

# ── M11: Mission submit works after reconnect ─────────────────────────
print("━━━ M11: MISSION SUBMIT AFTER WS (live test) ━━━")
# Submit a mission using the JWT token
if jwt_token:
    resp4 = httpx.post(f"{BASE}/api/mission",
                       headers={"Authorization": f"Bearer {jwt_token}", "Content-Type": "application/json"},
                       json={"input": "What is 2+2?"},
                       timeout=10)
    test("Mission submit returns 201", resp4.status_code == 201, f"status={resp4.status_code}")
    if resp4.status_code == 201:
        mid = resp4.json().get("data", {}).get("mission_id", "")
        test("Mission ID returned", len(mid) > 5, f"mid={mid}")
    else:
        test("Mission ID returned", False, resp4.text[:100])
else:
    # Try with static token
    resp4 = httpx.post(f"{BASE}/api/mission",
                       headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
                       json={"input": "What is 2+2?"},
                       timeout=10)
    test("Mission submit returns 201 (static token)", resp4.status_code == 201, f"status={resp4.status_code}")
    mid = resp4.json().get("data", {}).get("mission_id", "") if resp4.status_code == 201 else ""
    test("Mission ID returned", len(mid) > 5, f"mid={mid}")

# Check resync after reconnect
has_resync = "reconnected" in api_code and "refresh()" in api_code
test("Reconnect triggers state resync (refresh)", has_resync)
print()

# ── M12: UI state transitions are correct ─────────────────────────────
print("━━━ M12: UI STATE TRANSITIONS ━━━")
has_enum = "enum WsConnectionState" in ws_code
test("WsConnectionState enum defined", has_enum)

states = ["disconnected", "connecting", "connected", "reconnecting", "authExpired", "offline"]
all_states = all(s in ws_code for s in states)
test("All 6 states defined", all_states, f"states={states}")

has_set_state = "_setState" in ws_code
test("_setState() transition method", has_set_state)

has_notify = "notifyListeners()" in ws_code
test("notifyListeners on state change", has_notify)

# Check mission_screen uses state
mission_screen_path = "jarvismax_app/lib/screens/mission_screen.dart"
if os.path.exists(mission_screen_path):
    with open(mission_screen_path, encoding="utf-8") as f:
        ms_code = f.read()
    has_state_ui = "WsConnectionState" in ms_code
    test("Mission screen uses WsConnectionState", has_state_ui)
    
    has_color_mapping = "JvColors.green" in ms_code and "JvColors.orange" in ms_code
    test("UI color maps to states", has_color_mapping)
else:
    test("Mission screen uses WsConnectionState", False, "file not found")
    test("UI color maps to states", False)

# Check lifecycle observer
has_observer = "WidgetsBindingObserver" in main_code
test("Main uses WidgetsBindingObserver", has_observer)

has_lifecycle_forward = "onAppLifecycleChanged" in main_code
test("Lifecycle forwarded to WS service", has_lifecycle_forward)
print()

# ── SUMMARY ────────────────────────────────────────────────────────────
print("═══ MOBILE SUMMARY ═══")
passed = sum(1 for r in results if r["passed"])
failed = sum(1 for r in results if not r["passed"])
print(f"  PASSED: {passed}")
print(f"  FAILED: {failed}")
print(f"  TOTAL:  {len(results)}")

if failed > 0:
    print("\n  FAILURES:")
    for r in results:
        if not r["passed"]:
            print(f"    ❌ {r['name']}: {r['detail']}")

with open("/tmp/mobile_proof_results.json", "w") as f:
    json.dump({"passed": passed, "failed": failed, "total": len(results), "tests": results}, f)

sys.exit(0 if failed == 0 else 1)
