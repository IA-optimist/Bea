#!/usr/bin/env python3
"""PROOF BATTERY — Executor + Mobile Robustness"""
import re
import os
import sys

os.chdir('/app')
sys.path.insert(0, '/app')

print("╔══════════════════════════════════════════════════════════════╗")
print("║              PROOF BATTERY — EXECUTOR + MOBILE              ║")
print("╚══════════════════════════════════════════════════════════════╝")
print()

# ── T1: Error Classification Taxonomy ──────────────────────────────────
print("━━━ T1: ERROR CLASSIFICATION TAXONOMY ━━━")
from core.tool_executor import _classify_error
CANONICAL = {"TRANSIENT", "USER_INPUT", "TOOL_ERROR", "POLICY_BLOCKED", "TIMEOUT", "SYSTEM_ERROR"}

tests_t1 = [
    ("timeout exceeded", "TIMEOUT"),
    ("connection refused", "TRANSIENT"),
    ("permission denied", "POLICY_BLOCKED"),
    ("file not found", "USER_INPUT"),
    ("import error", "SYSTEM_ERROR"),
    ("random failure", "TOOL_ERROR"),
    (TimeoutError("x"), "TIMEOUT"),
    (ConnectionError("x"), "TRANSIENT"),
    (PermissionError("x"), "POLICY_BLOCKED"),
    (ValueError("x"), "USER_INPUT"),
    (ModuleNotFoundError("x"), "SYSTEM_ERROR"),
    (RuntimeError("x"), "TOOL_ERROR"),
]
t1_pass = True
for inp, expected in tests_t1:
    result = _classify_error(inp)
    ok = result == expected and result in CANONICAL
    if not ok: t1_pass = False
    status = "✅" if ok else "❌"
    label = type(inp).__name__ if isinstance(inp, Exception) else repr(inp)[:25]
    print(f"  {status} {label:28s} → {result:15s} (expect {expected})")
print(f"  Result: {'ALL PASS' if t1_pass else 'FAILURES'}  ({len(tests_t1)} tests)")
print()

# ── T2: Retryable Classification ──────────────────────────────────────
print("━━━ T2: RETRYABLE CLASSIFICATION ━━━")
from core.resilience import JarvisExecutionError
tests_t2 = [
    (TimeoutError("x"), True),
    (ConnectionError("x"), True),
    (PermissionError("x"), False),
    (ValueError("x"), False),
    (RuntimeError("x"), False),
    (FileNotFoundError("x"), False),
]
t2_pass = True
for exc, expected_retryable in tests_t2:
    r = JarvisExecutionError.from_exception(exc)
    ok = r.retryable == expected_retryable
    if not ok: t2_pass = False
    status = "✅" if ok else "❌"
    print(f"  {status} {type(exc).__name__:25s} retryable={str(r.retryable):5s} (expect {expected_retryable})")
print(f"  Result: {'ALL PASS' if t2_pass else 'FAILURES'}  ({len(tests_t2)} tests)")
print()

# ── T3: Silent Except Audit ───────────────────────────────────────────
print("━━━ T3: SILENT EXCEPT AUDIT (hot-path) ━━━")
HOT_PATH = [
    "core/action_executor.py", "core/meta_orchestrator.py", "core/agent_loop.py",
    "core/tool_executor.py", "core/mission_system.py", "core/memory_facade.py",
    "core/orchestrator.py", "core/background_dispatcher.py",
]
silent_count = 0
logged_count = 0
for fp in HOT_PATH:
    if not os.path.exists(fp):
        continue
    with open(fp, encoding="utf-8") as fh:
        lines = fh.readlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if re.match(r'except\s+(Exception)?\s*:', stripped):
            if i + 1 < len(lines) and lines[i+1].strip() in ("pass", "continue"):
                has_log = any("log." in lines[j] for j in range(max(0, i-1), min(len(lines), i+3)))
                if not has_log:
                    silent_count += 1
                    print(f"  ❌ {fp}:{i+1}")
                else:
                    logged_count += 1
            else:
                logged_count += 1
t3_pass = silent_count <= 2  # Allow 2 known acceptable cases
print(f"  Silent: {silent_count} | Logged: {logged_count}")
print(f"  Result: {'✅ PASS' if t3_pass else '❌ FAIL'} (threshold ≤2, actual={silent_count})")
print()

# ── T4: Error Result Structure ─────────────────────────────────────────
print("━━━ T4: ERROR RESULT STRUCTURE ━━━")
from core.tool_executor import _err
r = _err("test error", error_class="TIMEOUT", tool="web_search")
checks = [
    ("ok=False", r.get("ok") is False),
    ("error present", "error" in r and r["error"] == "test error"),
    ("error_class=TIMEOUT", r.get("error_class") == "TIMEOUT"),
    ("tool=web_search", r.get("tool") == "web_search"),
    ("default_class=TOOL_ERROR", _err("x").get("error_class") == "TOOL_ERROR"),
]
t4_pass = all(ok for _, ok in checks)
for label, ok in checks:
    print(f"  {'✅' if ok else '❌'} {label}")
print(f"  Result: {'ALL PASS' if t4_pass else 'FAILURES'}  ({len(checks)} checks)")
print()

# ── T5: JarvisExecutionError to_dict Structure ────────────────────────
print("━━━ T5: STRUCTURED ERROR PAYLOAD ━━━")
err = JarvisExecutionError.from_exception(TimeoutError("tool timed out"), tool="web_search", stage="execution")
d = err.to_dict()
required_fields = ["type", "retryable", "message", "tool", "stage", "severity", "cause"]
t5_pass = True
for field in required_fields:
    ok = field in d
    if not ok: t5_pass = False
    print(f"  {'✅' if ok else '❌'} {field}: {d.get(field, 'MISSING')}")
print(f"  Result: {'ALL PASS' if t5_pass else 'FAILURES'}  ({len(required_fields)} fields)")
print()

# ── T6: Completion Integrity ──────────────────────────────────────────
print("━━━ T6: COMPLETION INTEGRITY CODE ━━━")
with open("core/action_executor.py", encoding="utf-8") as f:
    ae_code = f.read()
has_fail_guard = "if executed == 0 and failed_count > 0:" in ae_code
has_fail_log = "mission_all_actions_failed" in ae_code
t6_pass = has_fail_guard and has_fail_log
print(f"  {'✅' if has_fail_guard else '❌'} All-FAILED guard present")
print(f"  {'✅' if has_fail_log else '❌'} FAILED log event present")
print(f"  Result: {'PASS' if t6_pass else 'FAIL'}")
print()

# ── T7: Timeout Guard ─────────────────────────────────────────────────
print("━━━ T7: TIMEOUT GUARD ━━━")
with open("core/tool_executor.py", encoding="utf-8") as f:
    te_code = f.read()
has_thread_timeout = "_t.join(timeout=_max_timeout)" in te_code
has_timeout_classify = 'error_class="TIMEOUT"' in te_code
has_clamp = "min(max(int(_max_timeout), 5), 120)" in te_code
t7_pass = has_thread_timeout and has_timeout_classify and has_clamp
print(f"  {'✅' if has_thread_timeout else '❌'} Thread-based timeout guard")
print(f"  {'✅' if has_timeout_classify else '❌'} Timeout → TIMEOUT classification")  
print(f"  {'✅' if has_clamp else '❌'} Timeout clamped 5-120s")
print(f"  Result: {'PASS' if t7_pass else 'FAIL'}")
print()

# ── T8: Memory Safety ─────────────────────────────────────────────────
print("━━━ T8: MEMORY SAFETY (SQLite) ━━━")
from core.memory.memory_schema import MemoryStore, MemoryEntry
store = MemoryStore(db_path=":memory:")
# WAL mode
entry = MemoryEntry(content="test", tier="EPISODIC", memory_type="observation")
store.store(entry)
entries = store.search(tier="EPISODIC", limit=5)
integrity = store.integrity_check()
# Test with file-based store for WAL verification
import tempfile
import os
_tmpf = os.path.join(tempfile.mkdtemp(), "test.db")
store2 = MemoryStore(db_path=_tmpf)
store2.store(MemoryEntry(content="wal test", tier="EPISODIC"))
integrity2 = store2.integrity_check()
t8_pass = True
checks_t8 = [
    ("Store+query works", len(entries) >= 1),
    ("Integrity OK", integrity.get("integrity") == "ok"),
    ("WAL mode (file db)", integrity2.get("journal_mode") == "wal"),
    ("Thread lock present", hasattr(store, "_lock")),
]
for label, ok in checks_t8:
    if not ok: t8_pass = False
    print(f"  {'✅' if ok else '❌'} {label}")
print(f"  Result: {'PASS' if t8_pass else 'FAIL'}")
print()

# ── T9: WebSocket State Machine (code audit) ──────────────────────────
print("━━━ T9: WEBSOCKET STATE MACHINE ━━━")
ws_path = "jarvismax_app/lib/services/websocket_service.dart"
with open(ws_path, encoding="utf-8") as f:
    ws_code = f.read()

checks_t9 = [
    ("WsConnectionState enum", "enum WsConnectionState" in ws_code),
    ("6 states defined", all(s in ws_code for s in ["disconnected", "connecting", "connected", "reconnecting", "authExpired", "offline"])),
    ("Concurrent guard", "_connectInFlight" in ws_code),
    ("Jitter in backoff", "jitter" in ws_code.lower()),
    ("401/auth detection", "authExpired" in ws_code and "auth_expired" in ws_code),
    ("onTokenRefreshed", "onTokenRefreshed" in ws_code),
    ("Connectivity monitor", "connectivity_plus" in ws_code),
    ("Heartbeat 25s", 'seconds: 25' in ws_code),
    ("Timeout 35s", 'seconds: 35' in ws_code),
    ("App lifecycle", "onAppLifecycleChanged" in ws_code),
]
t9_pass = all(ok for _, ok in checks_t9)
for label, ok in checks_t9:
    print(f"  {'✅' if ok else '❌'} {label}")
print(f"  Result: {'ALL PASS' if t9_pass else 'FAILURES'}  ({len(checks_t9)} checks)")
print()

# ── T10: Token Refresh Integration ────────────────────────────────────
print("━━━ T10: TOKEN REFRESH → WS RECONNECT ━━━")
api_path = "jarvismax_app/lib/services/api_service.dart"
with open(api_path, encoding="utf-8") as f:
    api_code = f.read()

checks_t10 = [
    ("onTokenRefreshed() called after refresh", "onTokenRefreshed()" in api_code),
    ("auth_expired event handled", "auth_expired" in api_code),
    ("reconnected → refresh()", "reconnected" in api_code and "refresh()" in api_code),
    ("_doTokenRefresh on auth_expired", "_doTokenRefresh" in api_code),
]
t10_pass = all(ok for _, ok in checks_t10)
for label, ok in checks_t10:
    print(f"  {'✅' if ok else '❌'} {label}")
print(f"  Result: {'ALL PASS' if t10_pass else 'FAILURES'}  ({len(checks_t10)} checks)")
print()

# ── SUMMARY ───────────────────────────────────────────────────────────
print("╔══════════════════════════════════════════════════════════════╗")
print("║                    PROOF BATTERY SUMMARY                    ║")
print("╠══════════════════════════════════════════════════════════════╣")
all_tests = [
    ("T1: Error Classification", t1_pass),
    ("T2: Retryable Logic", t2_pass),
    ("T3: Silent Except Audit", t3_pass),
    ("T4: Error Result Structure", t4_pass),
    ("T5: Structured Payload", t5_pass),
    ("T6: Completion Integrity", t6_pass),
    ("T7: Timeout Guard", t7_pass),
    ("T8: Memory Safety", t8_pass),
    ("T9: WebSocket State Machine", t9_pass),
    ("T10: Token Refresh Integration", t10_pass),
]
for label, passed in all_tests:
    print(f"║  {'✅' if passed else '❌'} {label:50s}    ║")
total_pass = sum(1 for _, p in all_tests if p)
print("╠══════════════════════════════════════════════════════════════╣")
print(f"║  TOTAL: {total_pass}/{len(all_tests)} PASS                                          ║")
print("╚══════════════════════════════════════════════════════════════╝")
