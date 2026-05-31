"""Generic migrator for the legacy `_silent_log.debug('suppressed_exception')`
pattern → modern `log.warning('swallowed_exception', action=..., ...)`.

Usage:
  python scripts/migrate_silent_swallows.py <file.py> action1 action2 ...

Each action label maps positionally to the silent-swallow site in the file
(in source order). The script:

  1. Verifies that the number of action labels matches the number of
     `_silent_log.debug("suppressed_exception", src='*.py')` lines.
  2. Replaces `except Exception:` immediately preceding each site with
     `except Exception as _exc:`.
  3. Replaces the silent line with:
         log.warning("swallowed_exception", action="<action>",
                     exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
  4. Drops the orphaned `_silent_log = ...` declaration at the top if
     present, replacing it with a canonical
     `log = structlog.get_logger(__name__)` if not already defined.

Idempotent if rerun with the same args (no double-migration: the script
checks the actual silent pattern before replacing).

The script does NOT modify files that mention the pattern in a STRING
(e.g. itself, or scripts/generate_silent_swallow_baseline.py).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


_SILENT_RE = re.compile(
    r'_silent_log\.debug\("suppressed_exception", src=\'[^\']+\.py\'\)'
)
_EXCEPT_RE = re.compile(r"^(\s*)except Exception:\s*$")


def main(argv: list[str] | None = None) -> int:
    args = argv or sys.argv[1:]
    if len(args) < 2:
        sys.stderr.write(
            "usage: migrate_silent_swallows.py <file.py> action1 [action2 ...]\n"
        )
        return 2
    target = Path(args[0])
    actions = args[1:]

    if not target.exists():
        sys.stderr.write(f"file not found: {target}\n")
        return 2

    text = target.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)

    # Find sites in source order.
    hits = [i for i, ln in enumerate(lines) if _SILENT_RE.search(ln)]
    if len(hits) != len(actions):
        sys.stderr.write(
            f"expected {len(actions)} silent sites, found {len(hits)} in {target}\n"
        )
        return 1

    # Replace from the bottom so line indices stay stable.
    for hit, action in zip(reversed(hits), reversed(actions)):
        prev = lines[hit - 1] if hit > 0 else ""
        m = _EXCEPT_RE.match(prev)
        if not m:
            sys.stderr.write(
                f"warn: line {hit} silent site without matching `except Exception:` "
                f"on the line above. Got: {prev!r}\n"
            )
            continue
        indent_except = m.group(1)
        # Compute indent of the silent line so the replacement keeps it.
        silent_line = lines[hit]
        indent_silent = silent_line[: len(silent_line) - len(silent_line.lstrip())]

        lines[hit - 1] = f"{indent_except}except Exception as _exc:\n"
        lines[hit] = (
            f"{indent_silent}log.warning(\"swallowed_exception\", "
            f"action=\"{action}\", "
            f"exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])\n"
        )

    # Replace the legacy `_silent_log = __import__("structlog")...` declaration
    # if present. Insert a canonical `log = ...` if no `log` is already defined.
    new_text = "".join(lines)

    # Drop the orphan _silent_log declaration.
    new_text = re.sub(
        r'^_silent_log = __import__\("structlog"\)\.get_logger\(__name__\)\n',
        '',
        new_text,
        flags=re.MULTILINE,
    )

    # Ensure `log = structlog.get_logger(__name__)` exists.
    has_log = re.search(r'^log = structlog\.get_logger\(', new_text, flags=re.MULTILINE)
    has_structlog_import = re.search(r'^import structlog\b', new_text, flags=re.MULTILINE)
    if not has_log:
        # Insert after the structlog import (or after `from __future__`/first
        # blank line if no import yet).
        if has_structlog_import:
            new_text = re.sub(
                r'(^import structlog\n)',
                r'\1\nlog = structlog.get_logger(__name__)\n',
                new_text,
                count=1,
                flags=re.MULTILINE,
            )
        else:
            sys.stderr.write(
                "warn: no `import structlog` found ; couldn't inject canonical log. "
                "Add it manually.\n"
            )

    target.write_text(new_text, encoding="utf-8")
    sys.stdout.write(f"Migrated {len(actions)} sites in {target}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
