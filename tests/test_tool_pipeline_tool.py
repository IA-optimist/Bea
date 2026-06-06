"""Tests pour core.tools.tool_pipeline_tool — ToolExecutor mocké."""
from __future__ import annotations

import core.tools.tool_pipeline_tool as tp


class _FakeExecutor:
    def __init__(self, script):
        # script: dict tool_name -> dict résultat
        self.script = script
        self.calls = []

    def execute(self, tool_name, params, approval_mode="SUPERVISED"):
        self.calls.append((tool_name, params, approval_mode))
        return self.script.get(tool_name, {"ok": True, "result": "ok"})


def _patch(monkeypatch, script):
    fake = _FakeExecutor(script)
    monkeypatch.setattr(tp, "_get_executor", lambda: fake)
    return fake


def test_empty_steps():
    res = tp.tool_pipeline([])
    assert res["ok"] is False and res["error"] == "empty_steps"


def test_sequential_success(monkeypatch):
    fake = _patch(monkeypatch, {"http_get": {"ok": True, "result": "200"}})
    res = tp.tool_pipeline([
        {"tool": "http_get", "params": {"url": "x"}},
        {"tool": "http_get", "params": {"url": "y"}},
    ])
    assert res["ok"] is True
    assert "2/2" in res["output"]
    assert len(fake.calls) == 2


def test_stop_on_error(monkeypatch):
    _patch(monkeypatch, {"bad": {"ok": False, "error": "boom"}})
    res = tp.tool_pipeline([
        {"tool": "bad", "params": {}},
        {"tool": "http_get", "params": {}},
    ])
    assert res["ok"] is False
    assert "step 0" in res["error"]
    assert len(res["logs"]) == 1  # arrêté après l'échec


def test_continue_on_error(monkeypatch):
    _patch(monkeypatch, {"bad": {"ok": False, "error": "boom"}})
    res = tp.tool_pipeline(
        [{"tool": "bad", "params": {}}, {"tool": "ok_tool", "params": {}}],
        stop_on_error=False,
    )
    assert res["ok"] is True  # pipeline complété
    assert "1/2" in res["output"]


def test_recursion_blocked(monkeypatch):
    _patch(monkeypatch, {})
    res = tp.tool_pipeline([{"tool": "tool_pipeline", "params": {}}])
    assert res["ok"] is False
    assert "récursion" in res["error"]


def test_invalid_step(monkeypatch):
    _patch(monkeypatch, {})
    res = tp.tool_pipeline([{"params": {}}])  # pas de 'tool'
    assert res["ok"] is False
    assert "invalid" in res["error"]
