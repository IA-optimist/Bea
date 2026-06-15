"""
core/security/code_guard.py — AST-based Python code safety checker.

Replaces substring denylist checks with proper AST analysis that cannot be
bypassed by whitespace tricks, string encoding, or comment injection.
"""
from __future__ import annotations

import ast
from typing import Sequence

# Modules whose import at any level is considered dangerous
_BLOCKED_MODULES: frozenset[str] = frozenset({
    "os", "sys", "subprocess", "shutil", "socket",
    "ctypes", "pickle", "importlib", "pty", "signal",
    "multiprocessing", "threading", "concurrent",
    "pathlib",  # allowed in trusted code; blocked in generated snippets
    "tempfile",
})

# Bare names whose use as a Call is considered dangerous
_BLOCKED_CALLS: frozenset[str] = frozenset({
    "eval", "exec", "__import__", "compile",
    "open", "breakpoint", "input",
})

# Subset that is only dangerous as a BARE (non-attribute) call.
# e.g. compile() is the dangerous builtin; re.compile() is fine.
# eval/exec are dangerous in all forms (obj.eval is sketchy too).
_BLOCKED_BARE_ONLY: frozenset[str] = frozenset({
    "compile", "open", "breakpoint", "input",
})


def check_code_safety(source: str) -> list[str]:
    """
    Parse *source* as Python and return a list of violation strings.
    Empty list = safe.  Non-empty = blocked.

    Detects:
    - Import of blocked modules (import os / from os import … / import os.path)
    - Direct calls to blocked builtins (eval, exec, __import__, compile, open …)
    - Attribute calls to blocked builtins (builtins.eval, __builtins__['exec'] …)
    """
    violations: list[str] = []

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"syntax_error: {exc}"]

    for node in ast.walk(tree):
        # --- Import checks ---
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in _BLOCKED_MODULES:
                    violations.append(f"blocked_import: {alias.name}")

        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root = node.module.split(".")[0]
                if root in _BLOCKED_MODULES:
                    violations.append(f"blocked_import: {node.module}")

        # --- Call checks ---
        elif isinstance(node, ast.Call):
            func = node.func

            # eval(...) / exec(...) / open(...)  — bare name
            if isinstance(func, ast.Name) and func.id in _BLOCKED_CALLS:
                violations.append(f"blocked_call: {func.id}")

            # builtins.eval(...) — attribute call; skip compile/open (too many false positives)
            elif isinstance(func, ast.Attribute) and func.attr in (_BLOCKED_CALLS - _BLOCKED_BARE_ONLY):
                violations.append(f"blocked_call: *.{func.attr}")

            # __import__('os') via subscript: __builtins__['__import__']('os')
            elif isinstance(func, ast.Subscript):
                if isinstance(func.slice, ast.Constant) and func.slice.value in _BLOCKED_CALLS:
                    violations.append(f"blocked_call: subscript[{func.slice.value!r}]")

    return violations


def is_code_safe(source: str) -> bool:
    """Return True if *source* passes all safety checks."""
    return len(check_code_safety(source)) == 0


def assert_code_safe(source: str, context: str = "") -> None:
    """Raise ValueError with violation details if *source* is unsafe."""
    violations = check_code_safety(source)
    if violations:
        prefix = f"[{context}] " if context else ""
        raise ValueError(f"{prefix}unsafe code: {'; '.join(violations)}")


# Convenience: list of blocked module names for shell/non-AST callers
BLOCKED_MODULES: Sequence[str] = sorted(_BLOCKED_MODULES)
BLOCKED_CALLS: Sequence[str] = sorted(_BLOCKED_CALLS)
