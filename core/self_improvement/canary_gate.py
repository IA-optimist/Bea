"""
core/self_improvement/canary_gate.py — Fast canary gate (T4.3).

Runs a compile-check on patched files after sandbox application,
before any PROMOTE/REVIEW decision is made.

Fail-open for infra failures (subprocess unavailable, no files) so
the caller falls through to risk-based logic — fail-closed for real
compile/syntax errors so bad patches never reach PROMOTE.
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)

_DEFAULT_TIMEOUT_S = 30


@dataclass
class CanaryResult:
    """Result of a canary gate run."""
    passed: bool
    reason: str
    stdout: str = ""
    returncode: int = 0
    skipped: bool = False   # True when infra unavailable — caller treats as pass

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "reason": self.reason,
            "returncode": self.returncode,
            "skipped": self.skipped,
        }


class CanaryGate:
    """
    Lightweight canary gate: py_compile all changed Python files
    in the sandbox after patch application.

    Why py_compile and not a full test run:
    - A full run in a tempcopy sandbox would duplicate the CI step
      and take minutes; py_compile catches the common failure class
      (syntax errors, encoding issues) in under a second.
    - A failed canary → REJECT with rollback instructions.
    - A skipped canary (infra failure, no .py files) → caller
      falls through to risk-based PROMOTE/REVIEW (fail-open).
    """

    def __init__(self, timeout_s: int = _DEFAULT_TIMEOUT_S) -> None:
        self.timeout_s = timeout_s

    def run(
        self,
        sandbox_path: "Path | None" = None,
        changed_files: "list[str] | None" = None,
    ) -> CanaryResult:
        """
        Compile-check changed Python files in the sandbox.

        Args:
            sandbox_path: Root of the sandbox where the patch was applied.
                          If None, checks against cwd-relative paths.
            changed_files: Relative paths of files changed by the patch.
                           If None or empty, returns skipped=True.

        Returns:
            CanaryResult — never raises.
        """
        root = Path(sandbox_path) if sandbox_path else Path.cwd()
        py_files: list[Path] = []

        for rel in (changed_files or []):
            candidate = root / rel
            if candidate.exists() and candidate.suffix == ".py":
                py_files.append(candidate)

        if not py_files:
            log.debug("canary_gate.skipped", reason="no_python_files")
            return CanaryResult(passed=True, reason="no_python_files", skipped=True)

        try:
            proc = subprocess.run(
                [sys.executable, "-m", "py_compile"] + [str(f) for f in py_files],
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
            )
        except subprocess.TimeoutExpired:
            log.warning("canary_gate.timeout", timeout_s=self.timeout_s, files=len(py_files))
            return CanaryResult(
                passed=False,
                reason=f"canary_timeout ({self.timeout_s}s)",
                returncode=-1,
            )
        except (FileNotFoundError, OSError) as exc:
            log.warning("canary_gate.unavailable", err=str(exc)[:80])
            return CanaryResult(passed=True, reason="canary_unavailable", skipped=True)

        if proc.returncode == 0:
            log.debug("canary_gate.compile_pass", files=len(py_files))
            return CanaryResult(passed=True, reason="compile_pass", returncode=0)

        stderr_preview = (proc.stderr or proc.stdout or "")[:300]
        log.info("canary_gate.compile_fail", rc=proc.returncode, preview=stderr_preview[:80])
        return CanaryResult(
            passed=False,
            reason=f"compile_fail (rc={proc.returncode})",
            stdout=stderr_preview,
            returncode=proc.returncode,
        )


_gate: "CanaryGate | None" = None


def get_canary_gate() -> CanaryGate:
    """Return module-level singleton."""
    global _gate
    if _gate is None:
        _gate = CanaryGate()
    return _gate
