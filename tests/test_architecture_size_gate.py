"""Architecture size gate — enforce the ratchet rule from MAJOR_DEBT_MAP.md.

Audit follow-up (item 8): docs/architecture/MAJOR_DEBT_MAP.md declares
> No new file in `api/` or `core/` should exceed 800 lines without an
> architecture note.

This test makes the rule binding. It scans `api/`, `core/`, `kernel/` for
any *.py file over the line threshold and asserts each such file is either:

  a) explicitly referenced in MAJOR_DEBT_MAP.md (acknowledged debt), OR
  b) listed in the explicit `_ALLOWED_LARGE_FILES` allowlist below.

To add a new large file legitimately:
  1. Document it under `## M1 Monoliths To Split First` in MAJOR_DEBT_MAP.md,
     OR add a justification + entry to `_ALLOWED_LARGE_FILES` here.
  2. Re-run this test.

The threshold mirrors the debt map (800 lines). Bump downward over time.
"""
from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEBT_MAP = _REPO_ROOT / "docs" / "architecture" / "MAJOR_DEBT_MAP.md"
_SCAN_ROOTS = ("api", "core", "kernel")
_THRESHOLD_LINES = 800

# Files that are large but intentionally so (e.g. generated, vendored, or
# unavoidable). Each entry MUST be justified by a comment. Empty for now.
_ALLOWED_LARGE_FILES: set[str] = set()


def _iter_python_files(root: Path) -> list[Path]:
    return [
        p for p in root.rglob("*.py")
        if "__pycache__" not in p.parts
        and "_legacy" not in p.parts
    ]


def _count_lines(path: Path) -> int:
    with path.open("r", encoding="utf-8") as fh:
        return sum(1 for _ in fh)


def test_debt_map_exists():
    assert _DEBT_MAP.exists(), (
        f"MAJOR_DEBT_MAP.md not found at {_DEBT_MAP}. "
        "Architecture debt must be tracked there."
    )


def test_no_undocumented_large_files():
    debt_map_text = _DEBT_MAP.read_text(encoding="utf-8")

    offenders: list[tuple[str, int]] = []
    for root_name in _SCAN_ROOTS:
        root = _REPO_ROOT / root_name
        if not root.exists():
            continue
        for py in _iter_python_files(root):
            n = _count_lines(py)
            if n <= _THRESHOLD_LINES:
                continue
            # POSIX-style path used by the debt map.
            rel = py.relative_to(_REPO_ROOT).as_posix()
            if rel in _ALLOWED_LARGE_FILES:
                continue
            if rel in debt_map_text:
                continue
            offenders.append((rel, n))

    assert not offenders, (
        f"{len(offenders)} file(s) over {_THRESHOLD_LINES} lines are not "
        f"documented in MAJOR_DEBT_MAP.md and not in the allowlist:\n"
        + "\n".join(f"  {rel}  ({n} lines)" for rel, n in sorted(offenders, key=lambda x: -x[1]))
        + "\n\nAdd them to docs/architecture/MAJOR_DEBT_MAP.md (preferred) "
        "or to _ALLOWED_LARGE_FILES in this file with a written justification."
    )
