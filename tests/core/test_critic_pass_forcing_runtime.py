import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from core.orchestrator_v2 import OrchestratorV2
import core.orchestrator_v2 as orchestrator_v2
import core.self_critic as self_critic
from core.resource_guard import SystemStatus


class _FakeGuard:
    def __init__(self, status):
        self._status = status
        self.charges = []

    def get_status(self):
        return SimpleNamespace(status=self._status)

    def charge(self, text, model="default"):
        self.charges.append(text)


class _FakeCritic:
    def __init__(self, should_rerun_value):
        self._should_rerun_value = should_rerun_value
        self.increment_calls = 0
        self.evaluate_calls = 0

    async def evaluate(self, session_id, agent_name, task, output):
        self.evaluate_calls += 1
        if self.evaluate_calls == 1:
            return SimpleNamespace(
                overall=6.5,
                rerun_count=0,
                task_hash="task-hash",
                feedback="needs more work",
                suggestions=["tighten"],
            )
        return SimpleNamespace(
            overall=7.5,
            rerun_count=1,
            task_hash="task-hash",
            feedback="",
            suggestions=[],
        )

    def should_rerun(self, report):
        return self._should_rerun_value

    def build_rerun_prompt(self, task, report, feedback, suggestions):
        return "rerun prompt"

    def increment_rerun(self, task_hash):
        self.increment_calls += 1
        return self.increment_calls


class _FakeInner:
    def __init__(self):
        self.calls = []

    async def run(self, user_input, mode, session_id):
        self.calls.append((user_input, mode, session_id))
        return SimpleNamespace(final_report="improved report")


def _make_orchestrator():
    orch = OrchestratorV2.__new__(OrchestratorV2)
    orch.s = SimpleNamespace()
    orch._get_inner = lambda: _FakeInner()
    return orch


def _run(coro):
    return asyncio.run(coro)


def test_critic_pass_forces_low_viability_rerun(monkeypatch):
    orch = _make_orchestrator()
    fake_inner = _FakeInner()
    fake_critic = _FakeCritic(False)
    fake_guard = _FakeGuard(SystemStatus.SAFE)
    events = []
    fake_mem = SimpleNamespace(record_improvement=AsyncMock())
    fake_hub = SimpleNamespace(
        emit_agent_thinking=AsyncMock(),
    )

    monkeypatch.setattr(orchestrator_v2, "get_resource_guard", lambda settings=None: fake_guard)
    monkeypatch.setattr(orch, "_get_inner", lambda: fake_inner)
    monkeypatch.setattr(self_critic, "get_critic", lambda settings=None: fake_critic)
    monkeypatch.setattr("core.improvement_memory.get_improvement_memory", lambda settings=None: fake_mem)
    monkeypatch.setattr("api.ws_hub.get_hub", lambda: fake_hub)
    monkeypatch.setattr(
        orchestrator_v2.log,
        "info",
        lambda event, **kw: events.append((event, kw)),
    )

    result = _run(orch._critic_pass("sess", "agent", "task", "report", "mode", fake_guard))

    assert result == "improved report"
    assert fake_critic.increment_calls == 1
    assert events[0][0] == "critic_rerun_complete"
    payload = events[0][1]
    assert payload["agent"] == "agent"
    assert payload["before"] == 6.5
    assert payload["after"] == 7.5
    assert payload["delta"] == 1.0
    assert payload["forced"] is True


def test_critic_pass_natural_rerun_keeps_forced_false(monkeypatch):
    orch = _make_orchestrator()
    fake_inner = _FakeInner()
    fake_critic = _FakeCritic(True)
    fake_guard = _FakeGuard(SystemStatus.NORMAL)
    events = []
    fake_mem = SimpleNamespace(record_improvement=AsyncMock())
    fake_hub = SimpleNamespace(
        emit_agent_thinking=AsyncMock(),
    )

    monkeypatch.setattr(orchestrator_v2, "get_resource_guard", lambda settings=None: fake_guard)
    monkeypatch.setattr(orch, "_get_inner", lambda: fake_inner)
    monkeypatch.setattr(self_critic, "get_critic", lambda settings=None: fake_critic)
    monkeypatch.setattr("core.improvement_memory.get_improvement_memory", lambda settings=None: fake_mem)
    monkeypatch.setattr("api.ws_hub.get_hub", lambda: fake_hub)
    monkeypatch.setattr(
        orchestrator_v2.log,
        "info",
        lambda event, **kw: events.append((event, kw)),
    )

    result = _run(orch._critic_pass("sess", "agent", "task", "report", "mode", fake_guard))

    assert result == "improved report"
    assert fake_critic.increment_calls == 1
    assert events[0][0] == "critic_rerun_complete"
    assert events[0][1]["forced"] is False
