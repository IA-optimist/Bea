"""Anti-regression: forbid new uses of the legacy silent-swallow pattern.

Audit follow-up (M3 depth): the codebase historically absorbed exceptions
with::

    try:
        ...
    except Exception:
        _silent_log.debug("suppressed_exception", src=...)

This logs at DEBUG, which is invisible in production by default — bugs
disappear silently. The replacement is one of:

  - ``with core._logging_helpers.swallow(log, action="X"):``
  - explicit ``log.warning/error("X", action=..., exc_type=..., exc_msg=...)``

This test enforces a ratchet baseline at
``quality/legacy_silent_swallows.json``:

  - Files in the baseline may keep their current count or **lower** it.
  - Any other file may have **zero** occurrences.
  - No baselined file may **regress upward**.

To lower a baseline entry: fix some occurrences then re-run
``python scripts/generate_silent_swallow_baseline.py`` and commit the
shrunk JSON.

To add a brand-new occurrence in a previously-clean file: don't. Use the
``swallow()`` helper. If you genuinely have a reason, regenerate the
baseline and write the justification in your PR.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_BASELINE_PATH = _REPO_ROOT / "quality" / "legacy_silent_swallows.json"
_PATTERN = re.compile(r"_silent_log\.debug\(['\"]suppressed_exception")

_EXCLUDE_DIRS = {"__pycache__", ".git", ".venv", "venv", "node_modules",
                 ".claude", "build", "dist", "snapshots",
                 # Tests legitimately mention the pattern as data
                 # (this very file does); only runtime code is scanned.
                 "tests",
                 # scripts/migrate_silent_swallows.py contains the pattern
                 # as a string literal so it can detect and replace it.
                 "scripts"}

# Files where the pattern appears in a docstring / data context only.
_EXCLUDE_FILES = {
    "core/_logging_helpers.py",  # docstring "before" example
}


def _iter_python_files():
    for path in _REPO_ROOT.rglob("*.py"):
        if any(part in _EXCLUDE_DIRS for part in path.parts):
            continue
        yield path


def _scan_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for py in _iter_python_files():
        try:
            text = py.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rel = py.relative_to(_REPO_ROOT).as_posix()
        if rel in _EXCLUDE_FILES:
            continue
        n = len(_PATTERN.findall(text))
        if n > 0:
            counts[rel] = n
    return counts


def _load_baseline() -> dict[str, int]:
    return json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))


def test_baseline_file_exists():
    assert _BASELINE_PATH.exists(), (
        f"baseline missing at {_BASELINE_PATH}. "
        "Generate via `python scripts/generate_silent_swallow_baseline.py`."
    )


def test_no_new_silent_swallow_files():
    """Any file with the pattern must be in the baseline."""
    baseline = _load_baseline()
    actual = _scan_counts()
    new_files = sorted(set(actual) - set(baseline))
    assert not new_files, (
        f"{len(new_files)} new file(s) use the deprecated "
        "`_silent_log.debug('suppressed_exception', ...)` pattern.\n"
        "Use `core._logging_helpers.swallow()` or an explicit "
        "`log.warning('swallowed_exception', action=...)` instead.\n\n"
        "Offending files:\n"
        + "\n".join(f"  {f} ({actual[f]} hits)" for f in new_files)
    )


def test_no_baselined_file_regresses():
    """A baselined file may shrink (or be removed); it must not grow."""
    baseline = _load_baseline()
    actual = _scan_counts()
    regressions: list[tuple[str, int, int]] = []
    for path, baseline_count in baseline.items():
        actual_count = actual.get(path, 0)
        if actual_count > baseline_count:
            regressions.append((path, baseline_count, actual_count))
    assert not regressions, (
        f"{len(regressions)} baselined file(s) have MORE silent swallows "
        "than the baseline allows. Migrate them to `swallow()` or fix "
        "the new sites you introduced.\n\n"
        "Regressions:\n"
        + "\n".join(
            f"  {p}: baseline={b}, actual={a} (+{a - b})"
            for p, b, a in regressions
        )
    )


def test_baseline_does_not_track_clean_files():
    """If a baselined file reached 0 occurrences, remove it from the JSON
    so the ratchet locks the new clean state in."""
    baseline = _load_baseline()
    actual = _scan_counts()
    stale = [p for p in baseline if actual.get(p, 0) == 0]
    assert not stale, (
        f"{len(stale)} baselined file(s) now have ZERO silent swallows. "
        "Remove them from quality/legacy_silent_swallows.json so any future "
        "regression is detected. Run "
        "`python scripts/generate_silent_swallow_baseline.py` to refresh.\n\n"
        "Now-clean files:\n" + "\n".join(f"  {p}" for p in stale)
    )
