"""Standalone CLI scanner — detect /api/v1 calls in client surfaces.

Prints all occurrences of /api/v1/* found in client surfaces (Flutter,
frontend, static HTML) and exits with a non-zero code if any are found.

Run this before a release to confirm no v1 calls remain in shipped code.
The test equivalent (pytest) is tests/test_client_v1_allowlist.py.

Usage:
    python scripts/check_client_v1_usage.py
    python scripts/check_client_v1_usage.py --json
"""
# ruff: noqa: T201
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_CLIENT_DIRS = [
    ROOT / "beamax_app",
    ROOT / "frontend",
    ROOT / "static",
    ROOT / "orchestrate-cli",
]

_EXTENSIONS = {".dart", ".ts", ".tsx", ".js", ".html", ".py"}

_SKIP_FRAGMENTS = ("__pycache__", "node_modules", ".dart_tool", "build/")

_V1_PATTERN = re.compile(r"['\"`/]/api/v1/")


def scan() -> list[dict]:
    """Return list of {path, lineno, line, is_comment} for every /api/v1 hit."""
    hits: list[dict] = []
    for surface_dir in _CLIENT_DIRS:
        if not surface_dir.exists():
            continue
        for fpath in surface_dir.rglob("*"):
            if fpath.suffix not in _EXTENSIONS:
                continue
            if any(skip in str(fpath) for skip in _SKIP_FRAGMENTS):
                continue
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                if _V1_PATTERN.search(line):
                    stripped = line.strip()
                    is_comment = stripped.startswith("//") or stripped.startswith("///") or stripped.startswith("#")
                    hits.append({
                        "path": str(fpath.relative_to(ROOT)).replace("\\", "/"),
                        "lineno": lineno,
                        "line": stripped,
                        "is_comment": is_comment,
                    })
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan client surfaces for /api/v1 calls.")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON.")
    parser.add_argument(
        "--include-comments",
        action="store_true",
        help="Include comment-only lines in the output (default: skip).",
    )
    args = parser.parse_args(argv)

    hits = scan()
    if not args.include_comments:
        hits = [h for h in hits if not h["is_comment"]]

    if args.json:
        print(json.dumps({"total": len(hits), "hits": hits}, indent=2))
        return 1 if hits else 0

    if not hits:
        print("[OK] No /api/v1 runtime calls found in client surfaces.")
        return 0

    print(f"[WARN] {len(hits)} /api/v1 call(s) found in client surfaces:\n")
    for h in hits:
        flag = "" if not h["is_comment"] else " (comment)"
        print(f"  {h['path']}:{h['lineno']}{flag}")
        print(f"    {h['line']}")
        print()
    print("To suppress: add to _V1_ALLOWLIST in tests/test_client_v1_allowlist.py.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
