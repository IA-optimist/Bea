"""Ratchet gate for silent ``except: pass`` style handlers.

Existing debt is allowed through ``quality/silent-except-baseline.json``.
The gate fails only when a file has more silent handlers than its baseline.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = PROJECT_ROOT / "quality" / "silent-except-baseline.json"
EXCLUDE_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".venv-c4-prep",
    "__pycache__",
    "beamax_app",
    "build",
    "dist",
    "frontend",
    "mobile",
    "node_modules",
    "orchestrate-mobile",
    "snapshots",
    "subprojects",
    "venv",
}


def _is_exception_type(node: ast.expr | None) -> bool:
    if node is None:
        return True
    if isinstance(node, ast.Name):
        return node.id in {"Exception", "BaseException"}
    if isinstance(node, ast.Attribute):
        return node.attr in {"Exception", "BaseException"}
    if isinstance(node, ast.Tuple):
        return any(_is_exception_type(elt) for elt in node.elts)
    return False


def _is_silent_body(body: list[ast.stmt]) -> bool:
    if not body:
        return True
    for stmt in body:
        if isinstance(stmt, ast.Pass):
            continue
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and stmt.value.value is Ellipsis:
            continue
        return False
    return True


def _iter_python_files(root: Path):
    for path in root.rglob("*.py"):
        rel_parts = path.relative_to(root).parts
        if any(part in EXCLUDE_DIRS for part in rel_parts):
            continue
        yield path


def count_silent_except_handlers(path: Path) -> int:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, OSError, UnicodeDecodeError):
        return 0

    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and _is_exception_type(node.type) and _is_silent_body(node.body):
            count += 1
    return count


def scan_silent_except_counts(root: Path = PROJECT_ROOT) -> dict[str, int]:
    counts: dict[str, int] = {}
    for py_file in _iter_python_files(root):
        count = count_silent_except_handlers(py_file)
        if count:
            counts[py_file.relative_to(root).as_posix()] = count
    return dict(sorted(counts.items()))


def compare_to_baseline(actual: dict[str, int], baseline: dict[str, Any]) -> list[tuple[str, int, int]]:
    budget = baseline.get("files", baseline)
    regressions: list[tuple[str, int, int]] = []
    for path, actual_count in sorted(actual.items()):
        baseline_count = int(budget.get(path, 0))
        if actual_count > baseline_count:
            regressions.append((path, baseline_count, actual_count))
    return regressions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--report-json", type=Path)
    args = parser.parse_args(argv)

    if not args.baseline.exists():
        sys.stderr.write(f"baseline not found: {args.baseline}\n")
        return 2

    actual = scan_silent_except_counts(args.root)
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    regressions = compare_to_baseline(actual, baseline)
    total = sum(actual.values())

    report = {
        "total": total,
        "files": actual,
        "regressions": [
            {"path": path, "baseline": baseline_count, "actual": actual_count}
            for path, baseline_count, actual_count in regressions
        ],
    }
    if args.report_json:
        args.report_json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    sys.stdout.write(f"except/pass ratchet: {len(actual)} files, {total} occurrences\n")
    if not regressions:
        sys.stdout.write("except/pass ratchet OK\n")
        return 0

    sys.stderr.write("silent except/pass debt increased:\n")
    for path, baseline_count, actual_count in regressions:
        sys.stderr.write(f"  {path}: baseline={baseline_count}, actual={actual_count}\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
