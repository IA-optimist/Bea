#!/usr/bin/env python3
"""Check that no active /api/v1 calls remain in beamax_app/lib/."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
LIB_DIR = ROOT / "beamax_app" / "lib"
EXEMPT_PATTERNS = ("allowlist", "_V1_ALLOWLIST", "// ")


def check() -> int:
    if not LIB_DIR.exists():
        print(f"[SKIP] {LIB_DIR} not found — beamax_app not present in this checkout")
        return 0

    hits: list[str] = []
    for dart_file in sorted(LIB_DIR.rglob("*.dart")):
        for lineno, line in enumerate(dart_file.read_text(encoding="utf-8").splitlines(), 1):
            if "/api/v1" in line and not any(p in line for p in EXEMPT_PATTERNS):
                rel = dart_file.relative_to(ROOT)
                hits.append(f"  {rel}:{lineno}: {line.strip()}")

    if hits:
        print(f"ERROR: {len(hits)} active /api/v1 call(s) found in Flutter client:")
        print("\n".join(hits))
        print("\nFlutter must use /api/v3. See docs/API_VERSIONING.md for migration status.")
        return 1

    print(f"[OK] {LIB_DIR.relative_to(ROOT)} — 0 active /api/v1 calls (Flutter uses /api/v3)")
    return 0


if __name__ == "__main__":
    sys.exit(check())
