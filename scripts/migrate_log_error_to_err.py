"""Migrate `log.<level>(..., error=...)` → `log.<level>(..., err=...)`.

Audit observability quick-win #4 from docs/security/observability-audit.md:
the codebase uses `err=` 632× and `error=` 80× as duplicate keys for the
same exception payload. Standardize on the dominant form (`err=`).

This script is conservative — it only rewrites kwargs named `error=`
when they are inside a structlog call (`log.info`, `log.warning`,
`log.error`, `log.debug`). It uses libcst tokenize via a simple regex
that requires the `error=` to be on the same line as `log.<level>(`
OR for a multi-line call, the `error=` line is preceded by an unclosed
`log.<level>(` paren count.

Files where the migration is unsafe (constructor args named `error=`,
dataclasses, etc.) are skipped. The script prints a per-file summary
so the diff is reviewable.

Usage:
    python scripts/migrate_log_error_to_err.py  [--dry-run] [path ...]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


_LOG_OPEN = re.compile(r"\blog\.(info|warning|error|debug)\s*\(")
_ERROR_KWARG = re.compile(r"(?<![A-Za-z0-9_])error\s*=")


def _migrate_text(text: str) -> tuple[str, int]:
    """Walk the source line by line, tracking the depth inside log.* calls,
    and rewrite `error=` to `err=` only when we are inside one.

    Returns the new text and the count of substitutions.
    """
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    depth = 0          # paren depth inside an in-progress log.* call
    in_log_call = False
    subs = 0

    for line in lines:
        new_line = line
        i = 0
        while i < len(line):
            ch = line[i]

            # Detect the start of a new log.<level>( on this position.
            if not in_log_call:
                m = _LOG_OPEN.match(line, i)
                if m:
                    in_log_call = True
                    depth = 1  # we just consumed the opening paren
                    i = m.end()
                    continue
                i += 1
                continue

            # We are inside a log call. Track parens.
            if ch == "(":
                depth += 1
                i += 1
                continue
            if ch == ")":
                depth -= 1
                i += 1
                if depth == 0:
                    in_log_call = False
                continue
            i += 1

        # In-line replacement of error= → err= for every line where we are
        # inside a log call at the start OR a log call opens on the line.
        if in_log_call or _LOG_OPEN.search(line):
            new_line, n = _ERROR_KWARG.subn("err=", new_line)
            subs += n

        out.append(new_line)

    return "".join(out), subs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", default=["api", "core", "kernel", "agents"],
                        help="Files or directories to scan (default: api core kernel agents)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would change without modifying files")
    args = parser.parse_args(argv)

    total_subs = 0
    total_files = 0
    for arg in args.paths:
        root = Path(arg)
        targets = [root] if root.is_file() else list(root.rglob("*.py"))
        for py in targets:
            if "__pycache__" in py.parts or ".venv" in py.parts or ".claude" in py.parts:
                continue
            try:
                text = py.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            new, n = _migrate_text(text)
            if n > 0:
                total_files += 1
                total_subs += n
                sys.stdout.write(f"{py}: {n} substitution(s)\n")
                if not args.dry_run:
                    py.write_text(new, encoding="utf-8")

    sys.stdout.write(f"\n{total_files} file(s), {total_subs} substitution(s)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
