#!/usr/bin/env python3
"""
Ratchet -- mission_id propagation audit for ToolExecutor.execute() call sites.

Verifies that runtime call sites of core ToolExecutor.execute() (or
get_tool_executor().execute()) propagate a mission_id so PolicyEngine session
limits can be enforced.

Strategy: targeted text-search on known ToolExecutor import patterns.
Executors that are NOT the core ToolExecutor (SafeExecutor, SupervisedExecutor,
sandbox executor, etc.) are excluded by allowlist.

Exit codes:
  0 -- all call sites are documented (OK or allowlisted)
  1 -- at least one undocumented runtime call site found without mission_id

Usage:
  python scripts/check_tool_executor_mission_id.py
  python scripts/check_tool_executor_mission_id.py --verbose
"""
from __future__ import annotations

import re
import sys
import pathlib
import argparse

REPO_ROOT = pathlib.Path(__file__).parent.parent

# -- Runtime directories to scan (non-test, non-script) -----------------------
RUNTIME_DIRS = ["core", "api", "agents", "kernel", "executor"]

# -- Files confirmed safe or not applicable -----------------------------------
# Format: "relative/path/from/repo/root" -> reason tag string
ALLOWLIST: dict[str, str] = {
    # StepExecutor._execute_with_tools -- dead code path, MissionEngine is never
    # instantiated in production; uses wrong kwarg ("parameters") so would fail
    # before reaching policy. Context has mission_id anyway via _build_step_context.
    "core/business/mission_runner.py": "LEGACY_TODO:MissionEngine_not_used_in_prod",

    # RecoveryEngine.execute_recovery -- only called from within ToolExecutor's
    # own exception handler, where the outer execute() already tracked mission_id.
    "core/resilience/recovery_engine.py": "DOCUMENT_AS_SAFE:called_only_from_tool_executor_retry",

    # tool_pipeline_tool propagates mission_id via kwarg (patched in this audit).
    "core/tools/tool_pipeline_tool.py": "OK:mission_id_propagated_via_kwarg",

    # Self-improvement executors (SafeExecutor, sandbox) operate on improvement
    # candidates, not on tool/mission sessions. They are gated by the improvement
    # kernel gate instead of the PolicyEngine session limits.
    "core/self_improvement/engine.py": "DOCUMENT_AS_SAFE:SafeExecutor_not_ToolExecutor",
    "core/self_improvement/promotion_pipeline.py": "DOCUMENT_AS_SAFE:sandbox_executor_not_ToolExecutor",
    "core/self_improvement/research_loop.py": "DOCUMENT_AS_SAFE:research_executor_not_ToolExecutor",
    "api/routes/self_improvement.py": "DOCUMENT_AS_SAFE:SafeExecutor_not_ToolExecutor",

    # SupervisedExecutor is a different class with its own session_id tracking.
    # It is NOT core ToolExecutor and is not subject to this policy audit.
    "executor/supervised_executor.py": "DOCUMENT_AS_SAFE:SupervisedExecutor_not_ToolExecutor",

    # Debug/test endpoint: /api/v2/tools/test passes the caller's params dict.
    # Callers can include mission_id in params. Low-priority dev tool (P2).
    "api/routes/system_v2.py": "LEGACY_TODO:debug_endpoint_params_caller_controlled",

    # execution_engine.py: execute_tool_intelligently() injects mission_id into
    # current_params at line ~419 BEFORE calling executor.execute(). The grep
    # window misses the injection because it is ~10 lines above the call.
    # Lines 428/469 both use current_params which already carries mission_id.
    # Line 19 is a docstring reference, not an actual call.
    "core/execution_engine.py": "OK:mission_id_injected_into_current_params_above_call",
}

# Regex to find ToolExecutor.execute() call sites via known import patterns.
_EXEC_RE = re.compile(
    # Direct get_tool_executor() call chain
    r"get_tool_executor\s*\(\s*\)\s*\.execute\s*\("
    # ToolExecutor() instantiation then .execute
    r"|ToolExecutor\s*\(\s*\)\s*\.execute\s*\("
    # Assignment: executor = get_tool_executor() (then executor.execute is nearby)
    r"|executor\s*=\s*get_tool_executor\s*\(\s*\)"
    # Direct _tool_executor attribute call
    r"|_tool_executor\s*\.execute\s*\("
)

# Within a window after the match, mission_id must appear in some form.
# Matches: mission_id=, mission_id,, setdefault("mission_id",, "mission_id": value
_MISSION_ID_RE = re.compile(r'mission_id\s*[=,]|["\']mission_id["\']')


def _lines_around(text: str, match_start: int, before: int = 50, after: int = 500) -> str:
    start = max(0, match_start - before)
    end = min(len(text), match_start + after)
    return text[start:end]


def scan() -> list[dict]:
    """Return list of findings for all runtime ToolExecutor.execute() call sites."""
    findings = []

    for dir_name in RUNTIME_DIRS:
        scan_dir = REPO_ROOT / dir_name
        if not scan_dir.is_dir():
            continue
        for py_file in sorted(scan_dir.rglob("*.py")):
            if "__pycache__" in py_file.parts:
                continue

            rel = py_file.relative_to(REPO_ROOT).as_posix()

            try:
                text = py_file.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            for m in _EXEC_RE.finditer(text):
                snippet = _lines_around(text, m.start())
                line_no = text[: m.start()].count("\n") + 1
                has_mission_id = bool(_MISSION_ID_RE.search(snippet))

                if rel in ALLOWLIST:
                    verdict = ALLOWLIST[rel]
                elif has_mission_id:
                    verdict = "OK"
                else:
                    verdict = "PATCH_NEEDED"

                findings.append({
                    "file": rel,
                    "line": line_no,
                    "has_mission_id": has_mission_id,
                    "verdict": verdict,
                    "snippet": snippet[:200].replace("\n", " ").strip(),
                })

    return findings


def _safe_write(s: str) -> None:
    """Write to stdout, replacing unencodable chars."""
    sys.stdout.buffer.write(s.encode(sys.stdout.encoding or "utf-8", errors="replace"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Print all findings, not just failures")
    args = parser.parse_args(argv)

    findings = scan()
    failures = [f for f in findings if f["verdict"] == "PATCH_NEEDED"]
    ok_count = len(findings) - len(failures)

    sep = "=" * 70
    if args.verbose or failures:
        _safe_write(f"\n{sep}\n")
        _safe_write(
            f"  mission_id propagation ratchet -- {len(findings)} call sites found\n"
        )
        _safe_write(f"{sep}\n")

    for f in findings:
        if args.verbose or f["verdict"] == "PATCH_NEEDED":
            status = "FAIL" if f["verdict"] == "PATCH_NEEDED" else "OK  "
            mid = "has_mission_id" if f["has_mission_id"] else "NO_mission_id"
            _safe_write(
                f"  [{status}] {f['file']}:{f['line']}  [{mid}]  {f['verdict']}\n"
            )
            if args.verbose:
                _safe_write(f"         {f['snippet'][:120]}\n")

    _safe_write("\n")
    if failures:
        _safe_write(
            f"FAIL: {len(failures)} runtime call site(s) without mission_id:\n"
        )
        for f in failures:
            _safe_write(f"  - {f['file']}:{f['line']}\n")
        _safe_write("\n")
        _safe_write(
            "  Fix: inject params.setdefault('mission_id', mission_id) "
            "before executor.execute()\n"
        )
        _safe_write(
            "  Or add the file to ALLOWLIST in this script with a justification.\n"
        )
        return 1

    _safe_write(f"PASS: {ok_count} call site(s) audited, 0 unresolved gaps.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
