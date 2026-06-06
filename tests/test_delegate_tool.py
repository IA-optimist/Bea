"""Tests pour core.tools.delegate_tool (Axe 3) — agent mocké, sans LLM."""
from __future__ import annotations

import asyncio

import core.tools.delegate_tool as dt


def test_empty_task_returns_error():
    res = dt.delegate("   ")
    assert res["ok"] is False
    assert res["error"] == "empty_task"


def test_successful_delegation(monkeypatch):
    async def _fake(task, role, timeout):
        return f"done:{task}:{role}"
    monkeypatch.setattr(dt, "_adelegate", _fake)
    res = dt.delegate("analyse X", role="research")
    assert res["ok"] is True
    assert res["output"] == "done:analyse X:research"


def test_invalid_role_falls_back_to_default(monkeypatch):
    seen = {}
    async def _fake(task, role, timeout):
        seen["role"] = role
        return "ok"
    monkeypatch.setattr(dt, "_adelegate", _fake)
    dt.delegate("t", role="not_a_role")
    assert seen["role"] == "default"


def test_timeout_clamped(monkeypatch):
    seen = {}
    async def _fake(task, role, timeout):
        seen["timeout"] = timeout
        return "ok"
    monkeypatch.setattr(dt, "_adelegate", _fake)
    dt.delegate("t", timeout=999999)
    assert seen["timeout"] == dt._MAX_TIMEOUT


def test_agent_error_is_fail_closed(monkeypatch):
    async def _boom(task, role, timeout):
        raise RuntimeError("llm down")
    monkeypatch.setattr(dt, "_adelegate", _boom)
    res = dt.delegate("t")
    assert res["ok"] is False
    assert "llm down" in res["error"]


def test_run_coro_works_inside_running_loop():
    # _run_coro doit fonctionner même si une boucle asyncio tourne déjà.
    async def _outer():
        async def _inner():
            return 7
        return dt._run_coro(_inner())
    assert asyncio.run(_outer()) == 7
