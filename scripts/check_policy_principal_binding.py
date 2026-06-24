#!/usr/bin/env python3
"""
Ratchet -- authenticated principal binding audit.

Verifies that public/runtime call sites that reach PolicyEngine sessions or
ToolExecutor.execute() propagate an authenticated principal_id (validated by
the auth middleware / request context). This closes the gap where a caller
could otherwise inject a fake `principal_id` via params.

Sources considered trusted:
  - `request.state.user` via `get_authenticated_principal(request)`
  - explicit keyword `principal_id=...` passed inside a public flow
  - `_bea_principal_id` injected into params dict

Call sites in tests, dev stubs, or non-public internal paths are allowlisted.

Exit codes:
  0 -- all covered
  1 -- at least one public runtime path lacks principal binding

Usage:
  python scripts/check_policy_principal_binding.py
  python scripts/check_policy_principal_binding.py --verbose
  python scripts/check_policy_principal_binding.py --summary
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).parent.parent

RUNTIME_DIRS = ["api", "core", "interfaces", "kernel", "agents", "executor"]

ALLOWLIST: dict[str, str] = {
    # Operational tool executor has its own approval gate and no PolicyEngine
    # session. It still receives _bea_principal_id for audit/consistency.
    "api/routes/operational_tools.py": "OK:operational_tool_injects_validated_principal",

    # Health, readiness and static asset endpoints do not execute tools or
    # create PolicyEngine sessions.
    "api/routes/health.py": "DOCUMENT_AS_SAFE:readiness_no_sessions",
    "api/routes/monitoring.py": "DOCUMENT_AS_SAFE:readiness_no_sessions",
    "api/routes/auth.py": "DOCUMENT_AS_SAFE:auth_only_no_tool_execution",

    # v1 stable surface now injects validated principal before orchestrator.run().
    "api/routes/v1.py": "OK:v1_submit_injects_validated_principal",

    # WebSocket handler is authenticated at upgrade time but does not route
    # principal through PolicyEngine yet (handled by session auth, debt).
    "api/ws.py": "LEGACY_TODO:websocket_principal_binding_not_yet_enforced",

    # Internal non-public orchestrator entry points. They accept principal_id
    # as a keyword when called from public routes, but internal callers may
    # omit it.
    "api/main.py": "OK:public_run_mission_has_principal_param",
    "core/bea_executor.py": "OK:accepts_principal_id_kwarg",
    "core/meta_orchestrator.py": "OK:accepts_principal_id_kwarg",
    "interfaces/kernel_adapter.py": "OK:accepts_principal_id_kwarg",

    # Learning/memory modules do not execute tools in this audit's scope.
    "core/orchestration/learning_mixin.py": "DOCUMENT_AS_SAFE:no_tool_execution",

    # Internal autonomous/agentic runners and langgraph flow use the
    # orchestrator from a non-request context; principal binding is out of scope
    # for these internal execution paths.
    "core/autonomy/runners.py": "DOCUMENT_AS_SAFE:internal_autonomous_runner",
    "core/orchestrator_lg/langgraph_flow.py": "DOCUMENT_AS_SAFE:internal_langgraph_flow",
    "core/orchestrator_v2.py": "DOCUMENT_AS_SAFE:docstring_stub_only",
    "core/profiling.py": "DOCUMENT_AS_SAFE:profiling_docstring_only",

    # execution_engine.py wraps ToolExecutor after injecting
    # mission_id/_bea_principal_id into current_params.
    "core/execution_engine.py": "OK:principal_injected_into_current_params",

    # Sandbox/self-improvement executors are not core ToolExecutor and do not
    # participate in per-mission policy sessions.
    "core/self_improvement/engine.py": "DOCUMENT_AS_SAFE:SafeExecutor_not_ToolExecutor",
    "core/self_improvement/promotion_pipeline.py": "DOCUMENT_AS_SAFE:sandbox_executor_not_ToolExecutor",
    "core/self_improvement/research_loop.py": "DOCUMENT_AS_SAFE:research_executor_not_ToolExecutor",
    "api/routes/self_improvement.py": "DOCUMENT_AS_SAFE:SafeExecutor_not_ToolExecutor",
}

# Regex covering public/runtime paths that reach PolicyEngine/Tools.
_CALL_RE = re.compile(
    # core ToolExecutor.execute() -- must carry _bea_principal_id/mission_id
    r"get_tool_executor\s*\(\s*\)\s*\.execute\s*\("
    # Intelligent execution engine wrapper
    r"|execute_tool_intelligently\s*\("
    # Tool pipeline -- must propagate principal
    r"|tool_pipeline\s*\("
    # Pre-execution tool runner
    r"|run_tools_for_mission\s*\("
    # Kernel adapter submit (mission launch from API)
    r"|(\.|_|\b)(adapter|_adapter)\s*\.\s*submit\s*\("
    # Orchestrator run/run_mission from a route context
    r"|orch\.run\s*\(|orchestrator\.run_mission\s*\(|orchestrator\.run\s*\("
    # PolicyEngine session creation on a public path
    r"|ensure_session\s*\(",
    re.DOTALL,
)

# Evidence of principal propagation in the surrounding code.
_PRINCIPAL_RE = re.compile(r"principal_id|_bea_principal_id|get_authenticated_principal")


def _lines_around(text: str, match_start: int, before: int = 300, after: int = 500) -> str:
    start = max(0, match_start - before)
    end = min(len(text), match_start + after)
    return text[start:end]


def scan() -> list[dict]:
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

            for m in _CALL_RE.finditer(text):
                line_no = text[: m.start()].count("\n") + 1
                snippet = _lines_around(text, m.start())
                has_principal = bool(_PRINCIPAL_RE.search(snippet))
                if rel in ALLOWLIST:
                    verdict = ALLOWLIST[rel]
                elif has_principal:
                    verdict = "OK"
                else:
                    verdict = "PATCH_NEEDED"
                findings.append({
                    "file": rel,
                    "line": line_no,
                    "has_principal": has_principal,
                    "verdict": verdict,
                    "snippet": snippet[:160].replace("\n", " ").strip(),
                })
    return findings


def _safe_write(s: str) -> None:
    sys.stdout.buffer.write(s.encode(sys.stdout.encoding or "utf-8", errors="replace"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Print all findings, not just failures")
    parser.add_argument("--summary", action="store_true",
                        help="Print a concise pass/fail summary only")
    args = parser.parse_args(argv)

    findings = scan()
    failures = [f for f in findings if f["verdict"] == "PATCH_NEEDED"]
    ok_count = len(findings) - len(failures)

    if args.summary:
        status = "PASS" if not failures else "FAIL"
        _safe_write(
            f"{status}: {ok_count}/{len(findings)} principal-binding call sites audited, "
            f"{len(failures)} unresolved gap(s).\n"
        )
        return 1 if failures else 0

    sep = "=" * 70
    if args.verbose or failures:
        _safe_write(f"\n{sep}\n")
        _safe_write(f"  principal binding ratchet -- {len(findings)} call sites found\n")
        _safe_write(f"{sep}\n")

    for f in findings:
        if args.verbose or f["verdict"] == "PATCH_NEEDED":
            status = "FAIL" if f["verdict"] == "PATCH_NEEDED" else "OK  "
            p = "has_principal" if f["has_principal"] else "NO_principal"
            _safe_write(
                f"  [{status}] {f['file']}:{f['line']}  [{p}]  {f['verdict']}\n"
            )
            if args.verbose:
                _safe_write(f"         {f['snippet'][:120]}\n")

    _safe_write("\n")
    if failures:
        _safe_write(
            f"FAIL: {len(failures)} public runtime path(s) without authenticated principal:\n"
        )
        for f in failures:
            _safe_write(f"  - {f['file']}:{f['line']}\n")
        _safe_write("\n")
        _safe_write(
            "  Fix: inject _bea_principal_id into params or pass principal_id=... "
            "from get_authenticated_principal(request) before the call.\n"
        )
        _safe_write(
            "  Or add the file to ALLOWLIST with a documented justification.\n"
        )
        return 1

    _safe_write(f"PASS: {ok_count} call site(s) audited, 0 unresolved principal-binding gaps.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
