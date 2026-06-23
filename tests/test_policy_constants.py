from __future__ import annotations

import ast
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent


def _python_sources():
    roots = [REPO_ROOT / "core", REPO_ROOT / "executor", REPO_ROOT / "agents", REPO_ROOT / "kernel"]
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if any(part in {"__pycache__", "archive"} for part in path.parts):
                continue
            yield path


@pytest.mark.parametrize("bad_string", ["REQUIRE_APPROVAL"])
def test_no_singular_require_approval_magic_string(bad_string):
    """The ExecutionPolicy constant is REQUIRES_APPROVAL (with S), not REQUIRE_APPROVAL."""
    offenders = []
    for path in _python_sources():
        text = path.read_text(encoding="utf-8", errors="ignore")
        if bad_string in text:
            offenders.append(f"{path.relative_to(REPO_ROOT)}")
    assert not offenders, f"Found magic string {bad_string!r} in: {offenders}"


def test_decision_constants_are_used_in_tool_executor():
    """ToolExecutor must reference Decision constants, not bare strings."""
    source = REPO_ROOT / "core" / "tool_executor.py"
    text = source.read_text(encoding="utf-8")
    assert "Decision.BLOCKED" in text or "Decision.REQUIRES_APPROVAL" in text, (
        "tool_executor should use Decision constants for execution-policy comparison"
    )
    assert '"BLOCK"' not in text, 'tool_executor should not compare against bare string "BLOCK"'
    assert '"REQUIRE_APPROVAL"' not in text, 'tool_executor should not compare against bare string "REQUIRE_APPROVAL"'
