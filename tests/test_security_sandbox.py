"""Security tests — code execution sandbox.

Verifies:
  1. python_snippet is completely removed (no bypass via direct import).
  2. execute_code routes to DockerSandbox (not host subprocess).
  3. Classic denylist-evasion patterns would have passed the old python_snippet
     but are now irrelevant because execute_code never touches the host Python.
"""
from __future__ import annotations

import pytest


# ── 1. python_snippet is gone ─────────────────────────────────────────────────

def test_python_snippet_not_importable():
    """execute_python_snippet must not exist in tool_executor."""
    import core.tool_executor as te_mod
    assert not hasattr(te_mod, "execute_python_snippet"), (
        "execute_python_snippet must be removed — it runs code on the host via "
        "subprocess with a bypassable denylist"
    )


def test_python_snippet_not_registered():
    """python_snippet must not appear in the ToolExecutor tool registry."""
    from core.tool_executor import get_tool_executor
    executor = get_tool_executor()
    assert "python_snippet" not in executor.list_tools(), (
        "python_snippet is still registered — remove it from _tools dict"
    )


def test_python_snippet_blocked_if_called_directly():
    """Calling python_snippet through the executor returns unknown_tool error."""
    from core.tool_executor import ToolExecutor
    result = ToolExecutor().execute("python_snippet", {"code": "print(1)"})
    assert result["ok"] is False
    err = result.get("error", "")
    assert any(p in err for p in ("unknown_tool", "unregistered_tool", "approval_required")), (
        f"Expected unknown_tool/unregistered/approval, got: {err!r}"
    )


# ── 2. Evasion patterns that bypassed old denylist ────────────────────────────
# These are documented for posterity — they prove the old denylist was
# insufficient.  execute_code does NOT run these on the host, so the tests
# verify the *old* bypass payloads are now inert (no host process launched).

_EVASION_PAYLOADS = [
    # __import__ bypass ("import os" was blocked but not __import__)
    "__import__('os').system('id')",
    # Tab escape ("import\tos" is not "import os" in Python's tokenizer)
    "import\tos; os.system('id')",
    # Attribute access on builtins via __class__.__mro__ gadget
    "().__class__.__mro__[1].__subclasses__()[104].__init__.__globals__['sys'].exit(0)",
    # exec() via string concatenation
    "e='ex'; c='ec'; getattr(__builtins__,e+c)('import os; os.system(\"id\")')",
    # eval bypass via chr() encoding
    "eval(chr(105)+chr(109)+chr(112)+chr(111)+chr(114)+chr(116)+chr(32)+chr(111)+chr(115))",
]


@pytest.mark.parametrize("payload", _EVASION_PAYLOADS)
def test_evasion_payload_not_executed_on_host(payload, monkeypatch):
    """execute_code never calls host subprocess — evasion payloads can't escape.

    We monkeypatch _get_sandbox to a fake that captures what would run and
    confirm no host subprocess.Popen/run was called.
    """
    import subprocess as _sp
    import core.tools.code_execution_tool as cet

    captured: list[dict] = []

    class _FakeSandbox:
        def __init__(self, wp): pass
        def is_available(self): return True
        def start(self): pass
        def stop(self): pass
        def execute(self, cmd: str):
            captured.append({"cmd": cmd})
            return 0, "sandboxed\n"

    monkeypatch.setattr(cet, "_get_sandbox", lambda wp: _FakeSandbox(wp))

    # Track any attempt to call host subprocess
    host_calls: list[str] = []
    _orig_run = _sp.run
    def _spy_run(args, **kw):
        host_calls.append(str(args))
        return _orig_run(args, **kw)
    monkeypatch.setattr(_sp, "run", _spy_run)

    import tempfile, os
    with tempfile.TemporaryDirectory() as tmp:
        result = cet.execute_code(payload, workspace_path=tmp)

    # The sandbox executed the command (not a host subprocess of the payload)
    assert len(captured) == 1
    assert captured[0]["cmd"].startswith("python .bea_exec_")
    # No host subprocess.run was called with the raw payload
    for call in host_calls:
        assert payload not in call, (
            f"Host subprocess called with evasion payload! call={call!r}"
        )


# ── 3. execute_code is gated (requires approval or Docker unavailable) ────────

def test_execute_code_gated_in_executor():
    """execute_code must be blocked when called without approval."""
    from core.tool_executor import ToolExecutor
    result = ToolExecutor().execute("execute_code", {"code": "print(1)"})
    assert result["ok"] is False
    err = result.get("error", "")
    # Either approval_required (registered+gated) or sandbox error (Docker absent)
    block_patterns = (
        "approval_required", "unregistered_tool", "unknown_tool",
        "capability_denied", "docker", "sandbox",
    )
    assert any(p in err.lower() for p in block_patterns), (
        f"execute_code not properly gated: {err!r}"
    )


# ── 4. execute_code in tool_permissions is high risk ─────────────────────────

def test_execute_code_has_high_permission():
    """execute_code must be declared as high-risk in tool_permissions."""
    from core.tool_permissions import get_tool_permissions
    perms = get_tool_permissions()
    perm = perms._gated_tools.get("execute_code")
    assert perm is not None, "execute_code missing from gated tools"
    assert perm.risk_level == "high", f"execute_code risk should be 'high', got {perm.risk_level!r}"
    assert perm.requires_approval is True
