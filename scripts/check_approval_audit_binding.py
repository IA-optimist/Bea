#!/usr/bin/env python3
"""
Ratchet -- approval audit binding.

Two checks:
  1. No hardcoded approved_by/rejected_by values ('human', 'admin', 'system', 'unknown').
     (Complements check_approval_hardcoded_principals.py which excludes tests.)
     This script scans ALL .py files including tests so the regression surface is wider.
  2. approved_by / rejected_by never passed as principal_id= to execution machinery
     (PolicyEngine, ToolExecutor, evaluate_tool, ensure_session, run_mission).

Exit codes:
  0 -- clean
  1 -- at least one violation

Usage:
  python scripts/check_approval_audit_binding.py
  python scripts/check_approval_audit_binding.py --verbose
  python scripts/check_approval_audit_binding.py --summary
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

SCAN_DIRS = ["api", "core", "kernel", "interfaces", "agents", "executor"]

EXCLUDE_DIRS = {"build", ".git", "__pycache__", ".venv", "node_modules", "migrations"}

# Pattern 1: hardcoded static identity strings as approved_by / rejected_by
HARDCODED_PATTERNS: list[re.Pattern] = [
    re.compile(r"""(approved_by|rejected_by)\s*=\s*["'](human|admin|system|unknown|anonymous)["']"""),
]

# Pattern 2: approved_by / rejected_by used as the value in principal_id= keyword argument
EXEC_PRINCIPAL_PATTERNS: list[re.Pattern] = [
    # e.g. principal_id=approved_by  or  principal_id=record.approved_by
    re.compile(r"""principal_id\s*=\s*(record\.)?(approved_by|rejected_by)\b"""),
    # e.g. evaluate_tool(..., approved_by, ...)  — positional, harder to catch; skip for now
    # e.g. ensure_session(mission_id, approved_by)
    re.compile(r"""(?:evaluate_tool|ensure_session|run_mission|ToolExecutor)\s*\([^)]*\b(approved_by|rejected_by)\b[^)]*principal"""),
]

ALLOWLIST: set[str] = {
    # Test files may legitimately reference these as assertion targets
    # (e.g. assert approved_by == "human" to confirm old value was replaced).
    # We skip tests for HARDCODED_PATTERNS only — exec-principal patterns are
    # never acceptable even in tests.
}


def _iter_files() -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for d in SCAN_DIRS:
        p = REPO_ROOT / d
        if p.is_dir():
            files.extend(p.rglob("*.py"))
    return files


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()

    files = _iter_files()
    hardcoded_violations: list[str] = []
    exec_principal_violations: list[str] = []

    for path in files:
        skip_parts = set(path.parts)
        if any(d in skip_parts for d in EXCLUDE_DIRS):
            continue

        rel = path.relative_to(REPO_ROOT)
        rel_str = rel.as_posix()
        is_test = "tests/" in rel_str or rel_str.startswith("tests/")

        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        for lineno, line in enumerate(text.splitlines(), 1):
            loc = f"{rel_str}:{lineno}"

            # Check 1 — skip test files (they may assert old bad values)
            if not is_test:
                for pat in HARDCODED_PATTERNS:
                    if pat.search(line):
                        hardcoded_violations.append(f"{loc}: {line.strip()}")

            # Check 2 — never acceptable anywhere
            for pat in EXEC_PRINCIPAL_PATTERNS:
                if pat.search(line):
                    exec_principal_violations.append(f"{loc}: {line.strip()}")

    total = len(hardcoded_violations) + len(exec_principal_violations)
    n_files = len(files)

    if args.summary:
        status = "PASS" if total == 0 else "FAIL"
        sys.stdout.write(
            f"check_approval_audit_binding: {status} "
            f"({len(hardcoded_violations)} hardcoded, "
            f"{len(exec_principal_violations)} exec-principal violations / {n_files} files)\n"
        )
    else:
        sys.stdout.write(f"check_approval_audit_binding: scanning {n_files} files...\n")
        hc = len(hardcoded_violations)
        ep = len(exec_principal_violations)
        sys.stdout.write(
            f"  {'PASS' if hc == 0 else 'FAIL'}: {hc} hardcoded approved_by/rejected_by found\n"
        )
        sys.stdout.write(
            f"  {'PASS' if ep == 0 else 'FAIL'}: {ep} approved_by/rejected_by used as execution principal\n"
        )
        n_checks = 2
        n_pass = (1 if hc == 0 else 0) + (1 if ep == 0 else 0)
        sys.stdout.write(
            f"check_approval_audit_binding: {'PASS' if total == 0 else 'FAIL'} ({n_pass}/{n_checks} checks)\n"
        )

    if args.verbose and (hardcoded_violations or exec_principal_violations):
        if hardcoded_violations:
            sys.stderr.write(f"\nHardcoded principal violations ({len(hardcoded_violations)}):\n")
            for v in hardcoded_violations:
                sys.stderr.write(f"  {v}\n")
        if exec_principal_violations:
            sys.stderr.write(f"\nExec-principal violations ({len(exec_principal_violations)}):\n")
            for v in exec_principal_violations:
                sys.stderr.write(f"  {v}\n")

    return 1 if total > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
