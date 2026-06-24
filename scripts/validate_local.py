# ruff: noqa: T201
"""Local validation gate used by the coding-agent quality plan.

Cross-platform Python replacement for ``scripts/validate_local.ps1``.
The PowerShell script remains available for manual Windows hooks, but the
agent-facing gate uses this wrapper so the command is portable.
"""
from __future__ import annotations

import argparse
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


def _record(results: list[tuple[str, str]], failures: list[str], name: str, rc: int, *, blocking: bool = True) -> None:
    status = "PASS" if rc == 0 else "FAIL"
    results.append((name, status))
    if blocking and rc != 0:
        failures.append(name)


def _record_skip(results: list[tuple[str, str]], skips: list[str], name: str, reason: str) -> None:
    _skip(name, reason)
    results.append((name, "SKIP"))
    skips.append(name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--quick", action="store_true", help="Run lint, critical tests, and static ratchets.")
    mode.add_argument("--full", action="store_true", help="Run the full local validation lane.")
    args = parser.parse_args(argv)
    quick = args.quick

    failures: list[str] = []
    skips: list[str] = []
    results: list[tuple[str, str]] = []

    # Lock-drift check must be first (mirrors CI order: step 1 before ruff)
    if _run(
        "lock-drift",
        [sys.executable, "scripts/check_requirements_lock.py", "requirements.txt", "requirements.lock"],
    ) != 0:
        failures.append("lock-drift")

    _record(results, failures, "ruff", _run("ruff", [sys.executable, "-m", "ruff", "check", "."]))

    _record(
        results,
        failures,
        "kernel boundaries",
        _run(
            "kernel-import-boundaries",
            [sys.executable, "scripts/check_kernel_import_boundaries.py"],
        ),
    )

    _record(
        results,
        failures,
        "coverage threshold",
        _run("coverage-threshold", [sys.executable, "scripts/check_coverage_threshold.py"]),
    )

    _record(
        results,
        failures,
        "except/pass ratchet",
        _run("except-pass-ratchet", [sys.executable, "scripts/check_silent_except_baseline.py"]),
    )

    _record(
        results,
        failures,
        "internal-import-ratchet",
        _run(
            "internal-import-ratchet",
            [sys.executable, "scripts/check_internal_imports.py", "--summary"],
        ),
    )

    _record(
        results,
        failures,
        "test marker ratchet",
        _run("test-marker-ratchet", [sys.executable, "scripts/check_test_marker_baseline.py"]),
    )

    _record(
        results,
        failures,
        "mission_id propagation ratchet",
        _run(
            "mission_id propagation ratchet",
            [sys.executable, "scripts/check_tool_executor_mission_id.py", "--summary"],
        ),
    )

    _record(
        results,
        failures,
        "principal binding ratchet",
        _run(
            "principal binding ratchet",
            [sys.executable, "scripts/check_policy_principal_binding.py", "--summary"],
        ),
    )
    _record(
        results,
        failures,
        "approval hardcoded principals ratchet",
        _run(
            "approval hardcoded principals ratchet",
            [sys.executable, "scripts/check_approval_hardcoded_principals.py"],
        ),
    )

    security_type_files = [
        "api/auth.py",
        "api/routes/auth.py",
        "kernel/convergence/event_bridge.py",
    ]
    _record(
        results,
        failures,
        "security strict mypy",
        _run(
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
        ),
    )

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
        "tests/quality/test_quality_gate_scripts.py",
    ]
    _record(
        results,
        failures,
        "pytest critical",
        _run("pytest-hardening", [sys.executable, "-m", "pytest", "-m", "not quarantine", *hardening_tests, "--no-header", "-q"]),
    )

    if not quick:
        _record(
            results,
            failures,
            "pytest quarantine",
            _run(
                "pytest-quarantine",
                [sys.executable, "-m", "pytest", "-m", "quarantine", "--no-header", "-q"],
            ),
            blocking=False,
        )

    if _has_module("mypy"):
        report = Path(os.environ.get("TEMP", os.environ.get("TMP", str(PROJECT_ROOT / ".tmp")))) / f"mypy-report-{os.getpid()}.txt"
        report.parent.mkdir(parents=True, exist_ok=True)
        with report.open("w", encoding="utf-8") as fh:
            proc = subprocess.run(
                [sys.executable, "-m", "mypy", "core", "api", "kernel", "--ignore-missing-imports", "--show-error-codes"],
                cwd=str(PROJECT_ROOT),
                stdout=fh,
                stderr=subprocess.STDOUT,
            )
        if proc.returncode not in (0, 1):
            _record(results, failures, "mypy ratchet", proc.returncode)
        else:
            _record(
                results,
                failures,
                "mypy ratchet",
                _run("mypy-delta-gate", [sys.executable, "scripts/check_mypy_baseline.py", str(report), "quality/mypy-baseline.json"]),
            )
    else:
        _record_skip(results, skips, "mypy ratchet", "not installed")

    if not quick and _has_module("bandit"):
        report = Path(os.environ.get("TEMP", os.environ.get("TMP", str(PROJECT_ROOT / ".tmp")))) / f"bandit-report-{os.getpid()}.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [sys.executable, "-m", "bandit", "-r", "api", "core", "kernel", "-f", "json", "-o", str(report), "--exit-zero", "--skip", "B101"],
            cwd=str(PROJECT_ROOT),
            check=False,
        )
        _record(
            results,
            failures,
            "bandit ratchet",
            _run("bandit-delta-gate", [sys.executable, "scripts/check_bandit_baseline.py", str(report), "quality/bandit-baseline.json"]),
        )
    elif not quick:
        _record_skip(results, skips, "bandit ratchet", "not installed")

    if not quick and _has_module("pip_audit"):
        report = Path(os.environ.get("TEMP", os.environ.get("TMP", str(PROJECT_ROOT / ".tmp")))) / f"audit-{os.getpid()}.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [sys.executable, "-m", "pip_audit", "-r", "requirements.txt", "--format", "json", "--output", str(report), "--strict"],
            cwd=str(PROJECT_ROOT),
            check=False,
        )
        _record(
            results,
            failures,
            "pip-audit ratchet",
            _run("pip-audit-delta-gate", [sys.executable, "scripts/check_pip_audit_baseline.py", str(report), "quality/pip-audit-baseline.json"]),
        )
    elif not quick:
        _record_skip(results, skips, "pip-audit ratchet", "not installed")

    if not quick and _has_module("build"):
        _record(results, failures, "build wheel", _run("build wheel", [sys.executable, "-m", "build", "--wheel"]))
    elif not quick:
        _record_skip(results, skips, "build wheel", "build module not installed")

    print()
    print("=" * 60)
    print("VALIDATION SUMMARY")
    print("=" * 60)

    for name, status in results:
        print(f"{name}: {status}")

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
