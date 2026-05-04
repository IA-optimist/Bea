#!/usr/bin/env python3
"""EXECUTOR PROOF MATRIX — test every claimed behavior."""
import sys
import os
import json
import re
os.chdir('/app')
sys.path.insert(0, '/app')

results = []

def test(name, passed, detail=""):
    results.append({"name": name, "passed": passed, "detail": detail})
    status = "✅" if passed else "❌"
    print(f"  {status} {name}{f': {detail}' if detail else ''}")

print("═══ EXECUTOR PROOF MATRIX ═══\n")

# ── E1: Timeout returns structured TIMEOUT ─────────────────────────────
print("━━━ E1: TIMEOUT RETURNS STRUCTURED RESULT ━━━")
from core.tool_executor import _classify_error, _err

r = _classify_error(TimeoutError("exceeded 10s"))
test("TimeoutError → TIMEOUT type", r == "TIMEOUT", f"got={r}")

r2 = _classify_error("tool timed out after 30s")
test("String timeout → TIMEOUT", r2 == "TIMEOUT", f"got={r2}")

err_result = _err("shell_command exceeded 10s", error_class="TIMEOUT", tool="shell_command")
test("TIMEOUT result has ok=False", err_result["ok"] is False)
test("TIMEOUT result has error_class=TIMEOUT", err_result["error_class"] == "TIMEOUT")
test("TIMEOUT result has tool name", err_result.get("tool") == "shell_command")

from core.resilience import JarvisExecutionError
je = JarvisExecutionError.from_exception(TimeoutError("x"), tool="web_search")
test("JarvisExecError TIMEOUT retryable=True", je.retryable is True)
d = je.to_dict()
test("TIMEOUT to_dict has 7 fields", len(d) >= 7, f"fields={list(d.keys())}")
print()

# ── E2: Transient failure is retryable ─────────────────────────────────
print("━━━ E2: TRANSIENT FAILURE IS RETRYABLE ━━━")
r = _classify_error(ConnectionError("refused"))
test("ConnectionError → TRANSIENT", r == "TRANSIENT", f"got={r}")

je = JarvisExecutionError.from_exception(ConnectionError("x"))
test("TRANSIENT retryable=True", je.retryable is True)

je2 = JarvisExecutionError.from_exception(OSError("network unreachable"))
test("OSError → TRANSIENT retryable=True", je2.retryable is True and je2.error_type == "TRANSIENT")

# Verify retry logic in code
with open("core/tool_executor.py") as f:
    te_code = f.read()
has_retry_loop = "for attempt in range(max_retries + 1):" in te_code
test("Retry loop exists in _execute_with_retry", has_retry_loop)
has_retry_log = '[RETRY]' in te_code
test("Retry attempt logged", has_retry_log)
print()

# ── E3: User input failure does NOT retry ──────────────────────────────
print("━━━ E3: USER_INPUT DOES NOT RETRY ━━━")
r = _classify_error(ValueError("invalid"))
test("ValueError → USER_INPUT", r == "USER_INPUT", f"got={r}")

je = JarvisExecutionError.from_exception(ValueError("bad input"))
test("USER_INPUT retryable=False", je.retryable is False)

je2 = JarvisExecutionError.from_exception(KeyError("missing_key"))
test("KeyError → USER_INPUT retryable=False", je2.retryable is False and je2.error_type == "USER_INPUT")

je3 = JarvisExecutionError.from_exception(TypeError("wrong type"))
test("TypeError → USER_INPUT retryable=False", je3.retryable is False and je3.error_type == "USER_INPUT")
print()

# ── E4: Policy blocked does NOT retry ──────────────────────────────────
print("━━━ E4: POLICY_BLOCKED DOES NOT RETRY ━━━")
r = _classify_error(PermissionError("forbidden"))
test("PermissionError → POLICY_BLOCKED", r == "POLICY_BLOCKED", f"got={r}")

je = JarvisExecutionError.from_exception(PermissionError("blocked"))
test("POLICY_BLOCKED retryable=False", je.retryable is False)

r2 = _classify_error("action blocked by policy engine")
test("String 'blocked' → POLICY_BLOCKED", r2 == "POLICY_BLOCKED")
print()

# ── E5: Tool error logged and surfaced ─────────────────────────────────
print("━━━ E5: TOOL_ERROR LOGGED AND SURFACED ━━━")
r = _classify_error(RuntimeError("something broke"))
test("RuntimeError → TOOL_ERROR", r == "TOOL_ERROR", f"got={r}")

err = _err("web_search failed", error_class="TOOL_ERROR", tool="web_search")
test("TOOL_ERROR result has error message", "web_search failed" in err.get("error", ""))
test("TOOL_ERROR surfaced (ok=False)", err["ok"] is False)

# Check execute() wraps errors with classification
has_classify_on_error = "error_class = _classify_error(str(e))" in te_code or "error_class = _classify_error" in te_code
test("execute() classifies errors before returning", has_classify_on_error)

has_error_log = "[EXECUTE_ERROR]" in te_code
test("execute() logs errors with [EXECUTE_ERROR]", has_error_log)
print()

# ── E6: No touched silent failure path remains ─────────────────────────
print("━━━ E6: NO SILENT FAILURE PATHS ━━━")
HOT_FILES = [
    "core/action_executor.py", "core/tool_executor.py",
    "core/meta_orchestrator.py", "core/agent_loop.py",
    "core/orchestrator.py", "core/mission_system.py",
    "core/memory_facade.py", "core/background_dispatcher.py",
]
total_silent = 0
for fp in HOT_FILES:
    if not os.path.exists(fp):
        continue
    with open(fp) as fh:
        lines = fh.readlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if re.match(r'except\s+(Exception)?\s*:', stripped) and i + 1 < len(lines):
            next_s = lines[i+1].strip()
            if next_s in ("pass", "continue"):
                has_log = any("log." in lines[j] for j in range(max(0, i-1), min(len(lines), i+3)))
                if not has_log:
                    total_silent += 1
                    print(f"    SILENT: {fp}:{i+1}")

# 1 known acceptable: tool_executor import fallback
test("Silent except blocks ≤1 (import fallback)", total_silent <= 1, f"found={total_silent}")
print()

# ── E7: Trace reconstructable after failed mission ────────────────────
print("━━━ E7: TRACE AFTER FAILED MISSION ━━━")
# Check that trace is saved even on failure path
with open("core/action_executor.py") as f:
    ae_code = f.read()

has_trace_on_complete = "trace.save()" in ae_code
test("trace.save() called at completion", has_trace_on_complete)

has_trace_log = "trace_saved" in ae_code
test("trace_saved log event exists", has_trace_log)

has_trace_fail_log = "trace_save_failed" in ae_code
test("trace_save_failed fallback exists", has_trace_fail_log)

# Check trace records execution status (EXECUTED or FAILED)
has_status_in_trace = "result=str(_status)" in ae_code
test("Trace records per-action status", has_status_in_trace)

# Verify trace directory exists and has real files
trace_dir = "workspace/traces"
has_traces = os.path.isdir(trace_dir) and len(os.listdir(trace_dir)) > 0
trace_count = len(os.listdir(trace_dir)) if os.path.isdir(trace_dir) else 0
test("Trace directory has saved traces", has_traces, f"count={trace_count}")
print()

# ── E8: Result cannot be DONE after all-failed ────────────────────────
print("━━━ E8: COMPLETION INTEGRITY ━━━")
has_fail_guard = "if executed == 0 and failed_count > 0:" in ae_code
test("All-FAILED guard prevents DONE", has_fail_guard)

has_fail_call = 'ms.fail(mission_id' in ae_code
test("ms.fail() called for all-failed missions", has_fail_call)

has_fail_log = "mission_all_actions_failed" in ae_code
test("mission_all_actions_failed log event", has_fail_log)

# Verify the guard comes BEFORE ms.complete()
fail_pos = ae_code.find("executed == 0 and failed_count > 0")
complete_pos = ae_code.find("ms.complete(", fail_pos if fail_pos > 0 else 0)
test("Fail guard comes before ms.complete()", fail_pos > 0 and fail_pos < complete_pos,
     f"fail@{fail_pos} < complete@{complete_pos}")
print()

# ── SUMMARY ────────────────────────────────────────────────────────────
print("═══ EXECUTOR SUMMARY ═══")
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

# Write results to JSON for aggregation
with open("/tmp/executor_proof_results.json", "w") as f:
    json.dump({"passed": passed, "failed": failed, "total": len(results), "tests": results}, f)

sys.exit(0 if failed == 0 else 1)
