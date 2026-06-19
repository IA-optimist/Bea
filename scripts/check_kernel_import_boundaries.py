"""AST-based import boundary check for kernel/.

Kernel modules may not import upward into core/api/agents/tools.
This script is shared by local validation and CI to keep the rule
mechanical instead of advisory.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
KERNEL_ROOT = PROJECT_ROOT / "kernel"
FORBIDDEN_ROOTS = ("core", "api", "agents", "tools")


def _scan_file(pyfile: Path) -> list[str]:
    violations: list[str] = []
    tree = ast.parse(pyfile.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if getattr(node, "col_offset", 1) != 0:
            continue
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for banned in FORBIDDEN_ROOTS:
                if module == banned or module.startswith(f"{banned}."):
                    violations.append(f"{pyfile}:{node.lineno}: from {module}")
        else:
            for alias in node.names:
                for banned in FORBIDDEN_ROOTS:
                    if alias.name == banned or alias.name.startswith(f"{banned}."):
                        violations.append(f"{pyfile}:{node.lineno}: import {alias.name}")
    return violations


def main() -> int:
    if not KERNEL_ROOT.exists():
        sys.stderr.write(f"kernel root not found: {KERNEL_ROOT}\n")
        return 1

    violations: list[str] = []
    scanned = 0
    for pyfile in KERNEL_ROOT.rglob("*.py"):
        scanned += 1
        try:
            violations.extend(_scan_file(pyfile))
        except SyntaxError as exc:
            sys.stderr.write(f"SYNTAX_ERROR: {pyfile}: {exc}\n")
            return 1

    if violations:
        sys.stdout.write(f"kernel import boundary violations ({len(violations)}):\n")
        for violation in violations:
            sys.stdout.write(f"  {violation}\n")
        return 1

    sys.stdout.write(f"kernel import boundaries clean: {scanned} files scanned\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
