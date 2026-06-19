"""
T3.2 helper: add @pytest.mark.stale to tests already marked skip(stale/phantom)
or xfail(drift/removed/missing/absent/not implemented/not wired).
Does NOT modify logic — only inserts the decorator line.
"""
import re
import sys
from pathlib import Path

TESTS_DIR = Path("tests")

# Patterns that indicate a stale skip
STALE_SKIP_PATTERN = re.compile(
    r'@pytest\.mark\.skip\(reason="(?:stale:|phantom:|'
    r'[^"]*(?:removed|deleted|LEGACY|moved|changed|obsolete)[^"]*)'
)

# Patterns that indicate a stale xfail
STALE_XFAIL_PATTERN = re.compile(
    r'@pytest\.mark\.xfail\([^)]*reason="[^"]*(?:drift|removed|missing|absent|'
    r'not implemented|not wired|non-implémenté|not yet)[^"]*"[^)]*\)'
)

STALE_MARKER = "@pytest.mark.stale"

changed_files = []
total_added = 0


def process_file(path: Path) -> int:
    """Return number of stale markers added."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    new_lines = []
    added = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.rstrip("\n\r")
        # Check if this line already has stale marker on previous line
        if new_lines and new_lines[-1].rstrip("\n\r").strip() == STALE_MARKER:
            # Don't double-add
            new_lines.append(line)
            i += 1
            continue

        # Get indentation of current line
        indent = len(stripped) - len(stripped.lstrip())
        indent_str = stripped[:indent]

        match_skip = STALE_SKIP_PATTERN.search(stripped)
        match_xfail = STALE_XFAIL_PATTERN.search(stripped)

        if match_skip or match_xfail:
            # Check if stale marker already present on the previous non-empty line
            already_marked = False
            for prev in reversed(new_lines):
                ps = prev.strip()
                if ps == "":
                    continue
                if ps == STALE_MARKER:
                    already_marked = True
                break
            if not already_marked:
                # Insert stale marker with same indentation
                new_lines.append(f"{indent_str}{STALE_MARKER}\n")
                added += 1

        new_lines.append(line)
        i += 1

    if added:
        path.write_text("".join(new_lines), encoding="utf-8")
        changed_files.append((path, added))

    return added


for test_file in sorted(TESTS_DIR.rglob("test_*.py")):
    n = process_file(test_file)
    total_added += n

print(f"\nDone. {total_added} @pytest.mark.stale markers added across {len(changed_files)} files:")
for fp, n in changed_files:
    print(f"  {fp}  (+{n})")
