# ruff: noqa: T201
"""Local validation gate used by the coding-agent quality plan.

Cross-platform Python replacement for ``scripts/validate_local.ps1``.
The PowerShell script remains available for manual Windows hooks, but the
agent-facing gate uses this wrapper so the command is portable.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _run(name: str, cmd: list[str], *, cwd: Path = PROJECT_ROOT) -> int:
    print("=" * 60)
    print(f">> {name}")
    print("=" * 60)
    proc = subprocess.run(cmd, cwd=str(cwd))
    if proc.returncode == 0:
        print(f"[OK] {name} passed")
    else:
        print(f"[FAIL] {name} (exit {proc.returncode})")
    return proc.returncode


def _skip(name: str, reason: str) -> None:
    print("=" * 60)
    print(f"[SKIP] {name} : {reason}")
    print("=" * 60)


def _has_module(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def main() -> int:
    failures: list[str] = []
    skips: list[str] = []

    # Lock-drift check must be first (mirrors CI order: step 1 before ruff)
    if _run(
        "lock-drift",
        [sys.executable, "scripts/check_requirements_lock.py", "requirements.txt", "requirements.lock"],
    ) != 0:
        failures.append("lock-drift")

    if _run("ruff", [sys.executable, "-m", "ruff", "check", "."]) != 0:
        failures.append("ruff")

    if _run(
        "kernel-import-boundaries",
        [sys.executable, "scripts/check_kernel_import_boundaries.py"],
    ) != 0:
        failures.append("kernel-import-boundaries")

    security_type_files = [
        "api/auth.py",
        "api/routes/auth.py",
        "kernel/convergence/event_bridge.py",
    ]
    if _run(
        "security-strict-mypy",
        [
            sys.executable,
            "-m",
            "mypy",
            *security_type_files,
            "--strict",
            "--follow-imports=skip",
            "--ignore-missing-imports",
            "--show-error-codes",
        ],
    ) != 0:
        failures.append("security-strict-mypy")

    hardening_tests = [
        "tests/test_jwt_v2.py",
        "tests/test_auth_routes_v2_flag.py",
        "tests/test_auth_coverage.py",
        "tests/test_logging_helpers.py",
        "tests/test_architecture_size_gate.py",
        "tests/architecture/test_kernel_import_boundaries.py",
        "tests/test_no_new_silent_swallows.py",
        "tests/test_p1_hardening.py",
        "tests/test_legacy_verify_token_revokes_v2.py",
        "tests/test_metric_naming_gate.py",
        "tests/test_log_event_name_convention.py",
        "tests/test_jwt_v2_metrics.py",
        "tests/self_improvement/test_pr_only_policy.py",
        "tests/self_improvement/test_patch_signing.py",
        "tests/test_major_quality_gates.py",
        "tests/test_minor_quality_gates.py",
    ]
    if _run("pytest-hardening", [sys.executable, "-m", "pytest", "-m", "not quarantine", *hardening_tests, "--no-header", "-q"]) != 0:
        failures.append("pytest-hardening")

    _run(
        "pytest-quarantine",
        [sys.executable, "-m", "pytest", "-m", "quarantine", "--no-header", "-q"],
    )

    if _has_module("mypy"):
        report = Path(os.environ.get("TEMP", os.environ.get("TMP", str(PROJECT_ROOT / ".tmp")))) / "mypy-report.txt"
        report.parent.mkdir(parents=True, exist_ok=True)
        with report.open("w", encoding="utf-8") as fh:
            proc = subprocess.run(
                [sys.executable, "-m", "mypy", "core", "api", "kernel", "--ignore-missing-imports", "--show-error-codes"],
                cwd=str(PROJECT_ROOT),
                stdout=fh,
                stderr=subprocess.STDOUT,
            )
        if proc.returncode not in (0, 1):
            failures.append("mypy")
        elif _run("mypy-delta-gate", [sys.executable, "scripts/check_mypy_baseline.py", str(report), "quality/mypy-baseline.json"]) != 0:
            failures.append("mypy-delta-gate")
    else:
        _skip("mypy", "not installed")
        skips.append("mypy")

    if _has_module("bandit"):
        report = Path(os.environ.get("TEMP", os.environ.get("TMP", str(PROJECT_ROOT / ".tmp")))) / "bandit-report.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [sys.executable, "-m", "bandit", "-r", "api", "core", "kernel", "-f", "json", "-o", str(report), "--exit-zero", "--skip", "B101"],
            cwd=str(PROJECT_ROOT),
            check=False,
        )
        if _run("bandit-delta-gate", [sys.executable, "scripts/check_bandit_baseline.py", str(report), "quality/bandit-baseline.json"]) != 0:
            failures.append("bandit-delta-gate")
    else:
        _skip("bandit", "not installed")
        skips.append("bandit")

    if _has_module("pip_audit"):
        report = Path(os.environ.get("TEMP", os.environ.get("TMP", str(PROJECT_ROOT / ".tmp")))) / "audit.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [sys.executable, "-m", "pip_audit", "-r", "requirements.txt", "--format", "json", "--output", str(report), "--strict"],
            cwd=str(PROJECT_ROOT),
            check=False,
        )
        if _run("pip-audit-delta-gate", [sys.executable, "scripts/check_pip_audit_baseline.py", str(report), "quality/pip-audit-baseline.json"]) != 0:
            failures.append("pip-audit-delta-gate")
    else:
        _skip("pip-audit", "not installed")
        skips.append("pip-audit")

    if _run("silent-swallow-baseline", [sys.executable, "scripts/generate_silent_swallow_baseline.py"]) == 0:
        diff = subprocess.run(
            ["git", "diff", "--quiet", "quality/legacy_silent_swallows.json"],
            cwd=str(PROJECT_ROOT),
            check=False,
        )
        if diff.returncode != 0:
            print("[WARN] silent-swallow baseline drifted - review and commit quality/legacy_silent_swallows.json")
    else:
        failures.append("silent-swallow-baseline")

    print()
    print("=" * 60)
    print("VALIDATION SUMMARY")
    print("=" * 60)

    if skips:
        print("Skipped:")
        for name in skips:
            print(f"  - {name}")

    if failures:
        print()
        print(f"FAILED ({len(failures)}):")
        for name in failures:
            print(f"  - {name}")
        return 1

    print()
    print("[OK] All checks passed - safe to push")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
