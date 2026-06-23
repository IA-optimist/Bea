"""AST-based import audit ratchet for internal namespaces.

Scans all .py files in the repo and reports:
  - broken_unprotected: imports of non-existent internal modules, naked or
    inside try blocks whose except handlers don't catch import errors.
  - broken_protected:   same but inside a guarded try/except block.
  - ignored_tests:      imports in test files (ignored for exit-code purposes).

Exit codes:
  0 — no broken_unprotected entries (or --strict not set and no broken_protected)
  1 — broken_unprotected entries found (or --strict and any broken entries found)

Usage:
  python scripts/check_internal_imports.py
  python scripts/check_internal_imports.py --output report.json
  python scripts/check_internal_imports.py --root /path/to/repo
  python scripts/check_internal_imports.py --strict
  python scripts/check_internal_imports.py --summary
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Internal namespaces to audit
# ---------------------------------------------------------------------------
INTERNAL_NAMESPACES: frozenset[str] = frozenset(
    {
        "core",
        "api",
        "agents",
        "executor",
        "kernel",
        "risk",
        "tools",
        "plugins",
        "mcp",
        "config",
        "scripts",
    }
)

# ---------------------------------------------------------------------------
# Directory / file exclusion helpers
# ---------------------------------------------------------------------------
EXCLUDED_DIR_NAMES: frozenset[str] = frozenset(
    {
        "__pycache__",
        "build",
        "dist",
        "node_modules",
    }
)

EXCLUDED_DIR_PREFIXES: tuple[str, ...] = (
    "venv",
    ".venv",
    "_archive",
    "_bak",
    "legacy_",
)

EXCLUDED_EGG_SUFFIX = ".egg-info"


def _is_excluded_dir(dir_path: Path, repo_root: Path) -> bool:
    """Return True if this directory should be skipped entirely."""
    name = dir_path.name
    if name in EXCLUDED_DIR_NAMES:
        return True
    if name.endswith(EXCLUDED_EGG_SUFFIX):
        return True
    for prefix in EXCLUDED_DIR_PREFIXES:
        if name.startswith(prefix):
            return True
    return False


def _is_test_file(rel_path: Path) -> bool:
    """Return True for files that live under tests/ or whose name starts with test_."""
    parts = rel_path.parts
    if "tests" in parts:
        return True
    if rel_path.name.startswith("test_"):
        return True
    return False


# ---------------------------------------------------------------------------
# Module existence check
# ---------------------------------------------------------------------------

def _module_exists(module_name: str, repo_root: Path) -> bool:
    """Return True if the module exists on the filesystem relative to repo_root.

    Purely filesystem-based — we do NOT use importlib.util.find_spec() to avoid
    importing project packages (which would cause side effects such as log output).
    """
    parts = module_name.split(".")
    if not parts:
        return False

    # Could be a package: namespace/a/b/__init__.py
    package_path = repo_root.joinpath(*parts) / "__init__.py"
    if package_path.exists():
        return True
    # Could be a module: namespace/a/b.py
    module_path = repo_root.joinpath(*parts[:-1]) / (parts[-1] + ".py")
    if module_path.exists():
        return True
    # Single-segment name: namespace.py at root
    if len(parts) == 1:
        single = repo_root / (parts[0] + ".py")
        if single.exists():
            return True

    return False


# ---------------------------------------------------------------------------
# AST helpers — location and protection detection
# ---------------------------------------------------------------------------

def _is_top_level(node: ast.stmt, tree: ast.Module) -> bool:
    """Return True if node is a direct child of the Module body."""
    return node in tree.body  # type: ignore[operator]


# Exception types that count as "guarding" an import
_IMPORT_GUARD_EXCEPTIONS: frozenset[str] = frozenset(
    {"ImportError", "ModuleNotFoundError", "Exception"}
)


def _try_is_protected(try_node: ast.Try) -> bool:
    """Return True if any handler of a Try block catches import-related errors."""
    for handler in try_node.handlers:
        # bare except:
        if handler.type is None:
            return True
        # except SomeType or except (A, B):
        caught_names: list[str] = []
        if isinstance(handler.type, ast.Tuple):
            for elt in handler.type.elts:
                if isinstance(elt, ast.Name):
                    caught_names.append(elt.id)
                elif isinstance(elt, ast.Attribute):
                    caught_names.append(elt.attr)
        elif isinstance(handler.type, ast.Name):
            caught_names.append(handler.type.id)
        elif isinstance(handler.type, ast.Attribute):
            caught_names.append(handler.type.attr)

        for name in caught_names:
            if name in _IMPORT_GUARD_EXCEPTIONS:
                return True
    return False


# ---------------------------------------------------------------------------
# Per-file scanning
# ---------------------------------------------------------------------------

def _import_str(node: ast.Import | ast.ImportFrom) -> str:
    if isinstance(node, ast.ImportFrom):
        module = node.module or ""
        names = ", ".join(
            (f"{a.name} as {a.asname}" if a.asname else a.name) for a in node.names
        )
        level_dots = "." * (node.level or 0)
        return f"from {level_dots}{module} import {names}"
    else:
        return "import " + ", ".join(
            (f"{a.name} as {a.asname}" if a.asname else a.name) for a in node.names
        )


def _module_name(node: ast.Import | ast.ImportFrom) -> str | None:
    """Return the top-level module name for internal checks, or None for relative imports."""
    if isinstance(node, ast.ImportFrom):
        if (node.level or 0) > 0:
            return None  # relative import, skip
        return node.module or ""
    else:
        # For `import a, b`, check each name; we'll return the first internal one.
        # Caller will call us once per node, so just return the first name.
        return node.names[0].name if node.names else None


def _top_level_name(module: str) -> str:
    return module.split(".")[0] if module else ""


# ---------------------------------------------------------------------------
# Walk the AST keeping track of which Try blocks each node is inside
# ---------------------------------------------------------------------------

def _collect_imports(
    tree: ast.Module,
) -> list[tuple[ast.Import | ast.ImportFrom, bool, bool]]:
    """
    Collect all import nodes with metadata.

    Returns list of (import_node, is_top_level, is_protected).
    """
    # Map node id → whether this node is top-level (direct child of Module body)
    top_level_set: set[int] = {id(n) for n in tree.body}

    results: list[tuple[ast.Import | ast.ImportFrom, bool, bool]] = []

    # We do a recursive walk tracking open Try blocks.
    # walk() processes `node` itself (not its parent), then recurses into children.
    def walk(node: ast.AST, inside_protected_try: bool) -> None:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            is_tl = id(node) in top_level_set
            results.append((node, is_tl, inside_protected_try))
            # No need to recurse into alias children
            return

        if isinstance(node, ast.Try):
            protected = _try_is_protected(node)
            new_flag = inside_protected_try or protected
            # Walk the try body with updated protection flag
            for body_child in node.body:
                walk(body_child, new_flag)
            # Walk handlers, orelse, finalbody — protection only applies to try body
            for handler in node.handlers:
                walk(handler, inside_protected_try)
            for else_child in node.orelse:
                walk(else_child, inside_protected_try)
            for final_child in node.finalbody:
                walk(final_child, inside_protected_try)
            return

        # For all other nodes, recurse into children
        for child in ast.iter_child_nodes(node):
            walk(child, inside_protected_try)

    # Start from the module itself — walk will process all its children
    walk(tree, False)
    return results


def scan_file(
    pyfile: Path,
    repo_root: Path,
    rel_path: Path,
) -> dict[str, Any]:
    """Scan a single file; return dict with lists broken_unprotected, broken_protected, ignored_tests."""
    result: dict[str, list[dict[str, Any]]] = {
        "broken_unprotected": [],
        "broken_protected": [],
        "ignored_tests": [],
    }

    is_test = _is_test_file(rel_path)

    try:
        source = pyfile.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(pyfile))
    except SyntaxError:
        return result  # unparseable files are silently skipped

    collected = _collect_imports(tree)

    for node, is_top_level, is_protected in collected:
        # For `import a, b, c` we check each alias separately
        if isinstance(node, ast.Import):
            import_nodes_to_check: list[tuple[ast.Import | ast.ImportFrom, str]] = []
            for alias in node.names:
                import_nodes_to_check.append((node, alias.name))
        else:
            mod = node.module if node.module else ""
            if (node.level or 0) > 0:
                continue  # relative import, skip
            import_nodes_to_check = [(node, mod)]

        for check_node, module_str in import_nodes_to_check:
            top_name = _top_level_name(module_str)
            if top_name not in INTERNAL_NAMESPACES:
                continue
            # It's an internal import — check if module exists
            if _module_exists(module_str, repo_root):
                continue
            # Module doesn't exist — classify it
            entry: dict[str, Any] = {
                "file": str(rel_path).replace("\\", "/"),
                "line": check_node.lineno,
                "import_str": _import_str(check_node),
                "module": module_str,
                "location": "top_level" if is_top_level else "in_function",
                "protected": is_protected,
            }
            if is_test:
                entry["reason"] = "test file"
                result["ignored_tests"].append(entry)
            elif is_protected:
                result["broken_protected"].append(entry)
            else:
                result["broken_unprotected"].append(entry)

    return result


# ---------------------------------------------------------------------------
# Repo walking
# ---------------------------------------------------------------------------

def collect_py_files(repo_root: Path) -> list[Path]:
    """Recursively collect .py files, respecting exclusions."""
    files: list[Path] = []

    def _walk(directory: Path) -> None:
        try:
            entries = sorted(directory.iterdir())
        except PermissionError:
            return
        for entry in entries:
            if entry.is_symlink():
                continue
            if entry.is_dir():
                if not _is_excluded_dir(entry, repo_root):
                    _walk(entry)
            elif entry.is_file() and entry.suffix == ".py":
                files.append(entry)

    _walk(repo_root)
    return files


# ---------------------------------------------------------------------------
# Main audit runner
# ---------------------------------------------------------------------------

def run_audit(repo_root: Path) -> dict[str, Any]:
    """Run the full audit and return the report dict."""
    py_files = collect_py_files(repo_root)

    all_broken_unprotected: list[dict[str, Any]] = []
    all_broken_protected: list[dict[str, Any]] = []
    all_ignored_tests: list[dict[str, Any]] = []
    total_imports = 0

    for pyfile in py_files:
        rel = pyfile.relative_to(repo_root)
        file_result = scan_file(pyfile, repo_root, rel)
        all_broken_unprotected.extend(file_result["broken_unprotected"])
        all_broken_protected.extend(file_result["broken_protected"])
        all_ignored_tests.extend(file_result["ignored_tests"])
        total_imports += (
            len(file_result["broken_unprotected"])
            + len(file_result["broken_protected"])
            + len(file_result["ignored_tests"])
        )

    # Count total internal imports found (broken ones only, since we don't count clean ones)
    # Adjust: total_imports here counts only broken/ignored.
    # The summary says "total_imports_found" which we interpret as all broken+ignored detected.

    report: dict[str, Any] = {
        "summary": {
            "total_files_scanned": len(py_files),
            "total_imports_found": total_imports,
            "broken_unprotected_count": len(all_broken_unprotected),
            "broken_protected_count": len(all_broken_protected),
            "ignored_test_count": len(all_ignored_tests),
        },
        "broken_unprotected": all_broken_unprotected,
        "broken_protected": all_broken_protected,
        "ignored_tests": all_ignored_tests,
    }
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _detect_repo_root() -> Path:
    """Auto-detect repo root from script location (scripts/ lives directly under root)."""
    # This file is at <root>/scripts/check_internal_imports.py
    script_dir = Path(__file__).resolve().parent
    candidate = script_dir.parent
    if (candidate / "pyproject.toml").exists() or (candidate / "setup.py").exists():
        return candidate
    # Fallback: use the parent of scripts/ unconditionally
    return candidate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="AST-based internal import audit ratchet"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Repository root (default: auto-detect from script location)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write JSON report to this file instead of stdout",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Also exit 1 if broken_protected is non-empty",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print human-readable summary instead of JSON",
    )
    args = parser.parse_args(argv)

    repo_root = args.root.resolve() if args.root else _detect_repo_root()

    report = run_audit(repo_root)

    if args.summary:
        s = report["summary"]
        print(f"[check_internal_imports] Repo: {repo_root}")
        print(f"  Files scanned         : {s['total_files_scanned']}")
        print(f"  Internal imports found: {s['total_imports_found']}")
        print(f"  Broken unprotected    : {s['broken_unprotected_count']}")
        print(f"  Broken protected      : {s['broken_protected_count']}")
        print(f"  Ignored (test files)  : {s['ignored_test_count']}")
        if report["broken_unprotected"]:
            print("\nBROKEN UNPROTECTED imports:")
            for entry in report["broken_unprotected"]:
                print(
                    f"  [{entry['location']}] {entry['file']}:{entry['line']}"
                    f"  =>  {entry['import_str']}"
                )
        if report["broken_protected"]:
            print("\nBROKEN PROTECTED imports (try/except guarded -- exit 0 unless --strict):")
            for entry in report["broken_protected"]:
                print(
                    f"  [{entry['location']}] {entry['file']}:{entry['line']}"
                    f"  =>  {entry['import_str']}"
                )
    else:
        json_str = json.dumps(report, indent=2, ensure_ascii=False)
        if args.output:
            args.output.write_text(json_str, encoding="utf-8")
        else:
            print(json_str)

    # Exit code
    if report["broken_unprotected"]:
        return 1
    if args.strict and report["broken_protected"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
