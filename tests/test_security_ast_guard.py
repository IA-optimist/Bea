"""
tests/test_security_ast_guard.py — AST-based code safety guardrail tests.

Verifies that check_code_safety() catches dangerous patterns that substring
denylists miss (whitespace tricks, encoding bypasses, attribute chains).
"""
from __future__ import annotations

import pytest
from core.security.code_guard import check_code_safety, is_code_safe, assert_code_safe


# ── Clean code — must pass ─────────────────────────────────────

SAFE_SNIPPETS = [
    "x = 1 + 2",
    "def add(a, b):\n    return a + b",
    'result = {"status": "ok", "output": 42, "error": None}',
    "import json\ndata = json.dumps({'key': 'value'})",
    "import re\npattern = re.search(r'\\d+', 'abc123')",
    "import math\nprint(math.sqrt(4))",
    "import datetime\nnow = datetime.datetime.now()",
    "import logging\nlog = logging.getLogger(__name__)",
    "from typing import Optional\ndef foo(x: Optional[int]) -> str:\n    return str(x)",
    "class Foo:\n    def bar(self) -> None:\n        pass",
]

@pytest.mark.parametrize("src", SAFE_SNIPPETS)
def test_AG01_safe_snippets_pass(src):
    violations = check_code_safety(src)
    assert violations == [], f"False positive on: {src!r} → {violations}"


# ── Direct dangerous imports ───────────────────────────────────

@pytest.mark.parametrize("src,blocked", [
    ("import os", "os"),
    ("import sys", "sys"),
    ("import subprocess", "subprocess"),
    ("import shutil", "shutil"),
    ("import socket", "socket"),
    ("import ctypes", "ctypes"),
    ("import pickle", "pickle"),
    ("import importlib", "importlib"),
    ("import pty", "pty"),
])
def test_AG02_blocked_imports(src, blocked):
    violations = check_code_safety(src)
    assert any(blocked in v for v in violations), \
        f"Expected {blocked!r} to be blocked in {src!r}, got: {violations}"


# ── from X import Y forms ──────────────────────────────────────

@pytest.mark.parametrize("src,blocked", [
    ("from os import getcwd", "os"),
    ("from os.path import join", "os"),
    ("from subprocess import run", "subprocess"),
    ("from shutil import rmtree", "shutil"),
    ("from sys import argv", "sys"),
    ("from importlib import import_module", "importlib"),
])
def test_AG03_blocked_from_imports(src, blocked):
    violations = check_code_safety(src)
    assert any(blocked in v for v in violations), \
        f"Expected {blocked!r} to be blocked in from-import {src!r}, got: {violations}"


# ── Dangerous calls ────────────────────────────────────────────

@pytest.mark.parametrize("src,blocked_call", [
    ("eval('1+1')", "eval"),
    ("exec('print(1)')", "exec"),
    ("__import__('os')", "__import__"),
    ("compile('x=1', '<string>', 'exec')", "compile"),
    ("open('/etc/passwd')", "open"),
])
def test_AG04_blocked_bare_calls(src, blocked_call):
    violations = check_code_safety(src)
    assert any(blocked_call in v for v in violations), \
        f"Expected {blocked_call!r} call to be blocked in {src!r}, got: {violations}"


# ── Evasion patterns that defeated the old substring denylist ─

def test_AG05_eval_with_leading_whitespace():
    """Old denylist matched 'eval(' exactly — whitespace in AST is irrelevant."""
    src = "x = eval  ('1+1')"
    # AST sees this as a Call to Name('eval') regardless of whitespace
    violations = check_code_safety(src)
    assert any("eval" in v for v in violations), \
        f"eval with space not caught: {violations}"


def test_AG06_import_in_nested_function():
    """Import inside a function still triggers at AST level."""
    src = "def legit():\n    import os\n    return os.getcwd()"
    violations = check_code_safety(src)
    assert any("os" in v for v in violations)


def test_AG07_import_aliased():
    """import os as o — alias doesn't matter, module name is still os."""
    src = "import os as o\nprint(o.getcwd())"
    violations = check_code_safety(src)
    assert any("os" in v for v in violations)


def test_AG08_multiline_import():
    """Multi-line import with backslash continuation."""
    src = "import \\\n    subprocess"
    violations = check_code_safety(src)
    assert any("subprocess" in v for v in violations)


def test_AG09_dynamic_call_via_attribute():
    """builtins.eval('...') — attribute access on a module."""
    src = "import builtins\nbuiltins.eval('x=1')"
    # blocked_import catches builtins (it's not in our list, but eval via .attr is caught)
    violations = check_code_safety(src)
    # Either the import of 'builtins' (not blocked by name) triggers nothing,
    # but the .eval attribute call is caught as blocked_call:*.eval
    assert any("eval" in v for v in violations)


def test_AG10_syntax_error_returns_violation():
    """Unparseable code is reported as syntax_error, not a crash."""
    violations = check_code_safety("def broken(:")
    assert len(violations) == 1
    assert violations[0].startswith("syntax_error:")


def test_AG11_empty_code_is_safe():
    violations = check_code_safety("")
    assert violations == []


# ── tool_builder_tool integration ─────────────────────────────

def test_AG12_tool_builder_uses_ast_guard():
    """validate_tool_structure must reject dangerous imports via AST guard."""
    from core.tools.tool_builder_tool import validate_tool_structure  # noqa: F811

    dangerous_code = (
        "import os\n"
        "def dangerous_tool(command: str) -> dict:\n"
        '    """Run shell."""\n'
        "    try:\n"
        "        result = os.system(command)\n"
        "        return {'status': 'ok', 'output': result, 'error': None}\n"
        "    except Exception as e:\n"
        "        return {'status': 'error', 'output': None, 'error': str(e)}\n"
    )
    result = validate_tool_structure(dangerous_code, "dangerous_tool")
    assert not result["valid"], "validator must reject code with blocked import"
    assert any("Unsafe" in issue or "blocked" in issue for issue in result["issues"])


def test_AG13_tool_builder_passes_safe_code():
    """validate_tool_structure must accept valid, safe tool code."""
    from core.tools.tool_builder_tool import validate_tool_structure  # noqa: F401 (re-import here)
    safe_code = (
        "import json\n"
        "def my_tool(data: dict) -> dict:\n"
        '    """Process data."""\n'
        "    try:\n"
        "        result = json.dumps(data)\n"
        "        return {'status': 'ok', 'output': result, 'error': None}\n"
        "    except Exception as e:\n"
        "        return {'status': 'error', 'output': None, 'error': str(e)}\n"
    )
    result = validate_tool_structure(safe_code, "my_tool")
    issues_about_safety = [i for i in result["issues"] if "Unsafe" in i or "blocked" in i]
    assert issues_about_safety == [], \
        f"False positive on safe tool code: {issues_about_safety}"


# ── assert_code_safe helper ────────────────────────────────────

def test_AG14_assert_code_safe_raises_on_danger():
    with pytest.raises(ValueError, match="unsafe code"):
        assert_code_safe("import os", context="test")


def test_AG15_assert_code_safe_passes_clean():
    assert_code_safe("x = 42")  # must not raise


# ── is_code_safe boolean helper ────────────────────────────────

def test_AG16_is_code_safe_true_for_clean():
    assert is_code_safe("x = 1 + 2") is True


def test_AG17_is_code_safe_false_for_danger():
    assert is_code_safe("import subprocess") is False
