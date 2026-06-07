"""
BEA MAX — Test Runner (production-grade CI-in-the-loop)
=============================================================
Runs pytest + syntax + linter on patches, parses results,
computes regression score, and produces structured validation reports.

Capabilities:
1. Run pytest on specific files or full suite
2. Parse results → pass/fail/error/skip counts + failure details
3. Baseline vs candidate regression detection
4. Structured ValidationReport with PROMOTE/REJECT/REVIEW decision
5. Affected test discovery from changed file list

Safety:
- Read-only test execution via SandboxExecutor
- Never modifies files
- Fail closed: if tests can't run → REJECT (not false success)
"""
from __future__ import annotations

import ast
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from core.self_improvement.sandbox_executor import SandboxExecutor, SandboxResult


@dataclass
class SuiteResult:
    """Parsed test results."""
    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    duration_s: float = 0
    failure_details: list[dict] = field(default_factory=list)
    raw_output: str = ""
    exit_code: int = -1
    validation_level: str = ""  # full, subprocess, syntax, blocked

    @property
    def success_rate(self) -> float:
        if self.total == 0:
            return 1.0
        return self.passed / self.total

    @property
    def all_passed(self) -> bool:
        return self.failed == 0 and self.errors == 0 and self.total > 0

    def to_dict(self) -> dict:
        return {
            "total": self.total, "passed": self.passed,
            "failed": self.failed, "errors": self.errors,
            "skipped": self.skipped, "duration_s": round(self.duration_s, 2),
            "success_rate": round(self.success_rate, 3),
            "all_passed": self.all_passed,
            "validation_level": self.validation_level,
            "failures": self.failure_details[:10],
        }


@dataclass
class RegressionReport:
    """Baseline vs candidate test comparison."""
    baseline: SuiteResult
    candidate: SuiteResult
    new_failures: int = 0
    fixed_failures: int = 0
    regression_detected: bool = False

    @property
    def recommendation(self) -> str:
        """ROLLBACK if regression detected, PROMOTE otherwise."""
        return "ROLLBACK" if self.regression_detected else "PROMOTE"

    def to_dict(self) -> dict:
        return {
            "baseline": self.baseline.to_dict(),
            "candidate": self.candidate.to_dict(),
            "new_failures": self.new_failures,
            "fixed": self.fixed_failures,
            "regression": self.regression_detected,
        }


@dataclass
class ValidationReport:
    """Complete validation report for a patch."""
    patch_id: str
    decision: str = ""          # PROMOTE, REJECT, REVIEW
    reason: str = ""
    syntax_ok: bool = False
    tests: SuiteResult | None = None
    regression: RegressionReport | None = None
    lint_ok: bool = True
    lint_output: str = ""
    lint_executed: bool = False       # True only if ruff actually ran
    typecheck_ok: bool = True
    typecheck_output: str = ""
    typecheck_executed: bool = False   # True only if mypy actually ran
    validation_level: str = ""  # full, subprocess, syntax, blocked
    rollback_instructions: str = ""
    unified_diff: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "patch_id": self.patch_id,
            "decision": self.decision,
            "reason": self.reason,
            "syntax_ok": self.syntax_ok,
            "tests": self.tests.to_dict() if self.tests else None,
            "regression": self.regression.to_dict() if self.regression else None,
            "lint_ok": self.lint_ok,
            "lint_output": self.lint_output[:200],
            "typecheck_ok": self.typecheck_ok,
            "typecheck_output": self.typecheck_output[:200],
            "validation_level": self.validation_level,
            "rollback": self.rollback_instructions[:200],
            "diff_preview": self.unified_diff[:1000],
        }


@dataclass
class ExperimentReport:
    """Structured report for one self-improvement experiment."""
    experiment_id: str = ""
    hypothesis: str = ""
    changed_files: list[str] = field(default_factory=list)
    diff_summary: str = ""
    validation_summary: dict = field(default_factory=dict)
    score: float = 0.0
    decision: str = ""          # PROMOTE, REJECT, REVIEW
    rollback_instructions: str = ""
    lesson_recorded: bool = False
    policy_blocks: list[str] = field(default_factory=list)
    protected_path_hits: list[str] = field(default_factory=list)
    duration_ms: float = 0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "experiment_id": self.experiment_id,
            "hypothesis": self.hypothesis[:300],
            "changed_files": self.changed_files,
            "diff_summary": self.diff_summary[:500],
            "validation": self.validation_summary,
            "score": round(self.score, 3),
            "decision": self.decision,
            "rollback": self.rollback_instructions[:200],
            "lesson_recorded": self.lesson_recorded,
            "policy_blocks": self.policy_blocks,
            "protected_hits": self.protected_path_hits,
            "duration_ms": round(self.duration_ms, 1),
        }


class PatchRunner:
    """
    Runs tests and produces validation reports for the improvement loop.

    Delegates execution to SandboxExecutor for isolation.
    Fail closed: if sandbox is blocked, decision = REJECT.
    """

    def __init__(self, repo_root: str | Path = ".", sandbox: SandboxExecutor | None = None):
        self._root = Path(repo_root)
        self._sandbox = sandbox or SandboxExecutor()

    # ── Test execution ──

    def run_in_sandbox(self, sandbox_path: str,
                        test_targets: list[str] | None = None,
                        timeout: int = 120) -> SuiteResult:
        """Run tests in sandbox, parse results."""
        result = self._sandbox.run_tests(sandbox_path, test_targets, timeout)
        return self._parse_sandbox_result(result)

    def run_affected(self, sandbox_path: str, changed_files: list[str],
                      timeout: int = 120) -> SuiteResult:
        """Run only tests affected by changed files."""
        test_files = self._find_affected_tests(changed_files)
        if test_files:
            return self.run_in_sandbox(sandbox_path, test_files, timeout)
        # No specific tests found → run full suite
        return self.run_in_sandbox(sandbox_path, None, timeout)

    def syntax_check(self, file_path: str, sandbox_path: str = "") -> tuple[bool, str]:
        """Check Python syntax of a file."""
        base = Path(sandbox_path) if sandbox_path else self._root
        full = base / file_path
        if not full.exists():
            return False, "File not found"
        try:
            ast.parse(full.read_text(encoding="utf-8"))
            return True, "OK"
        except SyntaxError as e:
            return False, f"Line {e.lineno}: {e.msg}"

    # ── Lint / Typecheck ──

    def run_lint(self, sandbox_path: str, files: list[str]) -> tuple[bool, str]:
        """
        Run ruff linter on changed files.
        
        Returns (True, "") if:
          - No Python files to lint
          - Tool unavailable (infra_unavailable) — NOT a lint failure
          - All files pass
        Returns (False, details) only if ruff ran and found real issues.
        """
        py_files = [f for f in files if f.endswith(".py")]
        if not py_files:
            return True, ""
        result = self._sandbox.run_linter(sandbox_path, py_files)
        # Tool not installed is not a lint failure
        if result.is_blocked or "not found" in (result.stderr + result.error).lower():
            return True, "[lint skipped: ruff not available]"
        return result.success, result.stdout[:500] + result.stderr[:500]

    def run_typecheck(self, sandbox_path: str, files: list[str]) -> tuple[bool, str]:
        """
        Run mypy type check on changed files (best-effort).
        
        Returns (True, "") if:
          - No Python files to check
          - Tool unavailable — NOT a type error
          - All files pass
        Returns (False, details) only if mypy ran and found real issues.
        """
        py_files = [f for f in files if f.endswith(".py")]
        if not py_files:
            return True, ""
        # mypy is in the allowlist
        file_args = " ".join(py_files)
        cmd = f"mypy {file_args}"
        if self._sandbox._check_docker():
            result = self._sandbox._run_docker_cmd(cmd, mount_dir=sandbox_path)
        else:
            result = self._sandbox._run_subprocess_cmd(cmd, cwd=sandbox_path)
        # Tool not installed is not a type error
        if result.is_blocked or "not found" in (result.stderr + result.error).lower():
            return True, "[typecheck skipped: mypy not available]"
        return result.success, result.stdout[:500] + result.stderr[:500]

    def run_py_compile(self, sandbox_path: str, files: list[str]) -> tuple[bool, str]:
        """Run py_compile for touched files (fast syntax check)."""
        errors = []
        for f in files:
            if not f.endswith(".py"):
                continue
            full = Path(sandbox_path) / f
            if not full.exists():
                continue
            try:
                import py_compile
                py_compile.compile(str(full), doraise=True)
            except py_compile.PyCompileError as e:
                errors.append(str(e)[:100])
        return len(errors) == 0, "\n".join(errors)

    # ── Regression detection ──

    def check_regression(self, baseline: SuiteResult,
                          candidate: SuiteResult) -> RegressionReport:
        """Compare baseline vs candidate results."""
        new_failures = max(0, candidate.failed - baseline.failed)
        fixed = max(0, baseline.failed - candidate.failed)
        regression = new_failures > 0

        return RegressionReport(
            baseline=baseline,
            candidate=candidate,
            new_failures=new_failures,
            fixed_failures=fixed,
            regression_detected=regression,
        )

    # ── Full validation ──

    def validate(
        self,
        patch_id: str,
        sandbox_path: str,
        changed_files: list[str],
        baseline: SuiteResult | None = None,
        rollback_instructions: str = "",
        unified_diff: str = "",
    ) -> ValidationReport:
        """
        Full validation pipeline: syntax → tests → regression → decision.
        
        Returns PROMOTE, REJECT, or REVIEW with evidence.
        """
        report = ValidationReport(
            patch_id=patch_id,
            rollback_instructions=rollback_instructions,
            unified_diff=unified_diff,
        )

        # 1. Syntax check
        for f in changed_files:
            if f.endswith(".py"):
                ok, err = self.syntax_check(f, sandbox_path)
                if not ok:
                    report.syntax_ok = False
                    report.decision = "REJECT"
                    report.reason = f"Syntax error: {err}"
                    report.validation_level = "syntax"
                    return report

        report.syntax_ok = True

        # 2. Run lint (best-effort, non-blocking)
        lint_ok, lint_out = self.run_lint(sandbox_path, changed_files)
        report.lint_ok = lint_ok
        report.lint_output = lint_out
        report.lint_executed = "skipped" not in lint_out.lower()

        # 3. Run typecheck (best-effort, non-blocking)
        tc_ok, tc_out = self.run_typecheck(sandbox_path, changed_files)
        report.typecheck_ok = tc_ok
        report.typecheck_output = tc_out
        report.typecheck_executed = "skipped" not in tc_out.lower()

        # 4. Run tests
        test_result = self.run_affected(sandbox_path, changed_files)
        report.tests = test_result
        report.validation_level = test_result.validation_level

        # Blocked → REJECT (fail closed)
        if test_result.validation_level == "blocked":
            report.decision = "REJECT"
            report.reason = "Test execution blocked (no Docker, no subprocess)"
            return report

        # 5. Regression check
        if baseline:
            regression = self.check_regression(baseline, test_result)
            report.regression = regression

            if regression.regression_detected:
                report.decision = "REJECT"
                report.reason = f"Regression: {regression.new_failures} new failure(s)"
                return report

            if regression.fixed_failures > 0:
                report.decision = "PROMOTE"
                report.reason = f"Fixed {regression.fixed_failures} failure(s), no regression"
                return report

        # 4. Decision based on test results
        if test_result.all_passed:
            report.decision = "PROMOTE"
            report.reason = f"All {test_result.total} tests pass"
        elif test_result.total == 0:
            # No tests ran — syntax-only
            report.decision = "REVIEW"
            report.reason = "No tests executed — manual review required"
        elif test_result.failed > 0:
            report.decision = "REJECT"
            report.reason = f"{test_result.failed} test failure(s)"
        else:
            report.decision = "REVIEW"
            report.reason = "Inconclusive test results"

        return report

    # ── Internal ──

    def _parse_output(self, output: str, result: SuiteResult) -> SuiteResult:
        """Parse raw pytest output string into SuiteResult in-place."""
        passed_m = re.search(r"(\d+) passed", output)
        failed_m = re.search(r"(\d+) failed", output)
        error_m = re.search(r"(\d+) error", output)
        skipped_m = re.search(r"(\d+) skipped", output)
        if passed_m:
            result.passed = int(passed_m.group(1))
        if failed_m:
            result.failed = int(failed_m.group(1))
        if error_m:
            result.errors = int(error_m.group(1))
        if skipped_m:
            result.skipped = int(skipped_m.group(1))
        result.total = result.passed + result.failed + result.errors
        for fb in re.findall(r"FAILED (.+?)(?:\n|$)", output):
            result.failure_details.append({"test": fb.strip()})
        return result

    def _parse_sandbox_result(self, sandbox: SandboxResult) -> SuiteResult:
        """Parse SandboxResult into SuiteResult."""
        result = SuiteResult(
            exit_code=sandbox.exit_code,
            raw_output=sandbox.stdout + sandbox.stderr,
            duration_s=sandbox.duration_ms / 1000,
            validation_level=sandbox.validation_level or sandbox.method,
        )

        if sandbox.is_blocked:
            result.validation_level = "blocked"
            return result

        output = sandbox.stdout + sandbox.stderr

        # Parse pytest summary: "X passed, Y failed, Z errors, W skipped"
        passed_m = re.search(r"(\d+) passed", output)
        failed_m = re.search(r"(\d+) failed", output)
        error_m = re.search(r"(\d+) error", output)
        skipped_m = re.search(r"(\d+) skipped", output)

        if passed_m:
            result.passed = int(passed_m.group(1))
        if failed_m:
            result.failed = int(failed_m.group(1))
        if error_m:
            result.errors = int(error_m.group(1))
        if skipped_m:
            result.skipped = int(skipped_m.group(1))

        result.total = result.passed + result.failed + result.errors

        # Extract failure details
        for fb in re.findall(r"FAILED (.+?)(?:\n|$)", output):
            result.failure_details.append({"test": fb.strip()})

        return result

    def _find_affected_tests(self, changed_files: list[str]) -> list[str]:
        """
        Find test files affected by changed source files.
        
        Priority order:
        1. Direct file-mapped tests (core/foo.py → tests/test_foo.py)
        2. Directory-level tests (core/business/x.py → tests/test_business_*.py)
        3. Returns empty if no mapping found (caller runs full suite)
        """
        test_files = []
        seen = set()

        for f in changed_files:
            p = Path(f)
            name = p.stem

            # 1. Direct mapped test
            candidate = self._root / "tests" / f"test_{name}.py"
            if candidate.exists() and str(candidate) not in seen:
                test_files.append(f"tests/test_{name}.py")
                seen.add(str(candidate))
                continue

            # 2. Directory-level tests
            # core/business/mission_engine.py → tests/test_mission_engine.py
            # Also try: core/business/*.py → tests/test_business_*.py pattern
            if len(p.parts) >= 2:
                dir_name = p.parts[-2]  # e.g. "business"
                dir_tests = list(self._root.glob(f"tests/test_{dir_name}*.py"))
                for dt in dir_tests:
                    rel = str(dt.relative_to(self._root))
                    if rel not in seen:
                        test_files.append(rel)
                        seen.add(rel)

        return test_files
