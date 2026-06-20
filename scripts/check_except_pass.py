"""Gate CI : détecte les bare-except et except-pass dans api/core/kernel.

Usage : python scripts/check_except_pass.py quality/except-pass-baseline.json
Exit 0 si count <= baseline, 1 sinon.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path


def scan(roots: list[Path]) -> list[str]:
    hits: list[str] = []
    for root in roots:
        for f in root.rglob("*.py"):
            if "__pycache__" in f.parts:
                continue
            try:
                src = f.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(src, filename=str(f))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ExceptHandler):
                    continue
                # bare except (no type annotation)
                if node.type is None:
                    hits.append(f"{f}:{node.lineno}: bare except")
                    continue
                # except with body = only Pass / string literal (i.e. silent swallow)
                body = node.body
                if all(
                    isinstance(s, ast.Pass)
                    or (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))
                    for s in body
                ):
                    hits.append(f"{f}:{node.lineno}: except-pass")
    return hits


def main() -> int:
    if len(sys.argv) != 2:
        sys.stderr.write("usage: check_except_pass.py <baseline.json>\n")
        return 2

    baseline_path = Path(sys.argv[1])
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    max_count = int(baseline["max_count"])

    repo_root = Path(__file__).parent.parent
    hits = scan([repo_root / d for d in ("api", "core", "kernel")])
    count = len(hits)

    for h in hits:
        sys.stdout.write(f"  {h}\n")

    if count > max_count:
        sys.stderr.write(
            f"except-pass gate exceeded: {count} occurrences > baseline {max_count}.\n"
            "Fix bare-except / silent swallow, or update quality/except-pass-baseline.json"
            " with justification.\n"
        )
        return 1

    sys.stdout.write(f"except-pass gate OK: {count} occurrences <= baseline {max_count}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
