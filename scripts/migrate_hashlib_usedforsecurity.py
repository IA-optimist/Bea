"""Add ``usedforsecurity=False`` to every ``hashlib.md5(...)`` and
``hashlib.sha1(...)`` call.

Bandit B324 fix: these weak hashes are used across the codebase to
generate short non-cryptographic IDs (`sid = f"bs-{md5...[:10]}"`,
`profile_id = ...[:8]`, content cache keys, etc.). They are NOT being
used as security primitives — same input must produce the same short
hash for caching / dedup.

The Python 3.9+ ``usedforsecurity=False`` argument signals this intent
and silences B324 with a real semantic flag instead of an annotation.

This script is conservative — it only touches calls that look like::

    hashlib.md5(<expr>)
    hashlib.md5(<expr>, ...)            (any args, no kwargs)
    hashlib.sha1(<expr>)
    hashlib.sha1(<expr>, ...)

If the call already has ``usedforsecurity=`` we leave it alone.

Usage:
    python scripts/migrate_hashlib_usedforsecurity.py [--dry-run] [path ...]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Match `hashlib.md5(` or `hashlib.sha1(` ; capture the open paren index
# so we can scan to the matching close.
_OPEN = re.compile(r"\bhashlib\.(md5|sha1)\(")


def _migrate_text(text: str) -> tuple[str, int]:
    out: list[str] = []
    i = 0
    subs = 0
    while i < len(text):
        m = _OPEN.search(text, i)
        if not m:
            out.append(text[i:])
            break
        out.append(text[i:m.start()])
        open_paren = m.end() - 1
        # Scan to the matching close paren.
        depth = 1
        j = open_paren + 1
        in_str: str | None = None
        while j < len(text) and depth > 0:
            ch = text[j]
            if in_str:
                if ch == "\\" and j + 1 < len(text):
                    j += 2
                    continue
                if ch == in_str:
                    in_str = None
                j += 1
                continue
            if ch in ("'", '"'):
                in_str = ch
                j += 1
                continue
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            j += 1
        # text[m.start():j] is the full call.
        call = text[m.start():j]
        if "usedforsecurity=" in call:
            out.append(call)
        else:
            # Insert before the closing paren.
            new_call = call[:-1].rstrip() + (", usedforsecurity=False" if call[m.end() - m.start()] != ")" else "usedforsecurity=False") + ")"
            # Simpler: if call had no args, "hashlib.md5()" we'd put `usedforsecurity=False)` ;
            # if it had args, `hashlib.md5(x, usedforsecurity=False)`.
            inner = call[m.end() - m.start():-1].strip()
            if inner:
                new_call = call[: m.end() - m.start()] + inner + ", usedforsecurity=False)"
            else:
                new_call = call[: m.end() - m.start()] + "usedforsecurity=False)"
            out.append(new_call)
            subs += 1
        i = j
    return "".join(out), subs


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("paths", nargs="*", default=["api", "core", "kernel", "agents"])
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    total_subs = 0
    total_files = 0
    for arg in args.paths:
        root = Path(arg)
        targets = [root] if root.is_file() else list(root.rglob("*.py"))
        for py in targets:
            if "__pycache__" in py.parts or ".venv" in py.parts:
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
