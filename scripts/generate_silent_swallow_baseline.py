"""Generate the legacy silent-swallow baseline.

Scans the repo for occurrences of the deprecated pattern

    _silent_log.debug("suppressed_exception", ...)

and writes a per-file count map to ``quality/legacy_silent_swallows.json``.

This baseline is consumed by ``tests/test_no_new_silent_swallows.py`` to
enforce a ratchet rule: existing files may keep their current count or
lower it ; new files must stay at zero ; no file may regress upward.

Run once when adding a new legacy file to the budget, or after a cleanup
pass that fixes some occurrences::

    python scripts/generate_silent_swallow_baseline.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = REPO_ROOT / "quality" / "legacy_silent_swallows.json"
PATTERN = re.compile(r"_silent_log\.debug\(['\"]suppressed_exception")
# Files where the pattern appears in a docstring / data context (not as
# actual silent-swallow code). Excluded from the scan.
EXCLUDE_FILES = {
    "core/_logging_helpers.py",  # docstring "before" example
}

EXCLUDE_DIRS = {"__pycache__", ".git", ".venv", ".venv-c4-prep", "venv", "node_modules",
                ".claude", "build", "dist", "snapshots",
                # Tests legitimately mention the pattern as data (gates,
                # documentation strings). Only runtime code is scanned.
                "tests",
                # The migration script itself contains the pattern as a
                # string literal so it can detect and replace it. Don't
                # count its own grammar against the baseline.
                "scripts"}


def _iter_python_files(root: Path):
    for path in root.rglob("*.py"):
        if any(part in EXCLUDE_DIRS for part in path.parts):
            continue
        yield path


def main() -> int:
    counts: dict[str, int] = {}
    for py in _iter_python_files(REPO_ROOT):
        try:
            text = py.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rel = py.relative_to(REPO_ROOT).as_posix()
        if rel in EXCLUDE_FILES:
            continue
        n = len(PATTERN.findall(text))
        if n > 0:
            counts[rel] = n

    counts = dict(sorted(counts.items()))
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(
        json.dumps(counts, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    total_files = len(counts)
    total_hits = sum(counts.values())
    sys.stdout.write(
        f"Wrote {BASELINE_PATH.relative_to(REPO_ROOT)}: "
        f"{total_files} files, {total_hits} occurrences.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
