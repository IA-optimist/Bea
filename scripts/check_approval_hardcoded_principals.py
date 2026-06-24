#!/usr/bin/env python3
"""
Ratchet: no hardcoded 'human'/'admin'/'system'/'unknown' as approved_by or rejected_by.

Exit 1 if violations found; exit 0 with "0 violations" if clean.
Excludes: build/, .git/, tests/ (tests may legitimately check for these values).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PATTERNS = [
    re.compile(r"""approved_by\s*=\s*["'](human|admin|system|unknown)["']"""),
    re.compile(r"""rejected_by\s*=\s*["'](human|admin|system|unknown)["']"""),
]

EXCLUDE_DIRS = {"build", ".git", "__pycache__", ".venv", "node_modules"}

violations: list[str] = []

for path in ROOT.rglob("*.py"):
    parts = set(path.parts)
    if parts & {str(ROOT / d) for d in EXCLUDE_DIRS}:
        continue
    # skip by path component
    if any(d in path.parts for d in EXCLUDE_DIRS):
        continue
    # skip test files — they may assert on these values
    if "/tests/" in path.as_posix() or "\\tests\\" in str(path):
        continue

    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        continue

    for lineno, line in enumerate(text.splitlines(), 1):
        for pat in PATTERNS:
            if pat.search(line):
                violations.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()}")

if violations:
    sys.stderr.write(f"[FAIL] {len(violations)} hardcoded principal violation(s):\n")
    for v in violations:
        sys.stderr.write(f"  {v}\n")
    sys.exit(1)

sys.stdout.write("[OK] 0 violations — no hardcoded approved_by/rejected_by principals found.\n")
sys.exit(0)
