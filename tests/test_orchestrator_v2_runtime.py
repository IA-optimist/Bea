from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.orchestrator_v2 import OrchestratorV2
from core.resource_guard import SystemStatus
from config.settings import get_settings


def test_get_inner_does_not_raise_module_not_found():
    """Regression: OrchestratorV2 must not crash on a missing legacy module."""
    v2 = OrchestratorV2(get_settings())
    inner = v2._get_inner()
    assert inner is not None
    assert type(inner).__name__ == "BeaOrchestrator"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("rerun_score", "resource_status", "expected", "expected_runs"),
    [
        (4.0, SystemStatus.NORMAL, "original", 1),
        (7.0, SystemStatus.SOFT_WARN, "improved", 1),
        (7.0, SystemStatus.BLOCKED, "original", 0),
    ],
)
async def test_compatibility_critic_returns_only_a_strictly_better_rerun(
    monkeypatch,
    rerun_score: float,
    resource_status: SystemStatus,
    expected: str,
    expected_runs: int,
) -> None:
    initial = SimpleNamespace(
        overall=5.0,
        rerun_count=0,
        feedback="improve evidence",
        suggestions=[],
    )
    rerun = SimpleNamespace(overall=rerun_score)

    class _Critic:
        def __init__(self):
            self.reports = [initial, rerun]

        async def evaluate(self, *args):
            return self.reports.pop(0)

        def should_rerun(self, report):
            return True

        def build_rerun_prompt(self, *args):
            return "augmented"

        def reserve_rerun(self, report):
            return True

    class _Inner:
        def __init__(self):
            self.calls = 0

        async def run(self, **kwargs):
            self.calls += 1
            return SimpleNamespace(final_report="improved")

    class _Hub:
        async def emit_agent_thinking(self, *args, **kwargs):
            return None

    class _Resources:
        def __init__(self):
            self.acquire_calls = 0
            self.release_calls = 0

        def get_status(self):
            return SimpleNamespace(status=resource_status)

        def acquire_slot(self, *args, **kwargs):
            self.acquire_calls += 1
            return True

        def release_slot(self, *args, **kwargs):
            self.release_calls += 1

    monkeypatch.setattr("core.self_critic.get_critic", lambda settings=None: _Critic())
    resources = _Resources()
    monkeypatch.setattr(
        "core.resource_guard.get_resource_guard",
        lambda settings=None: resources,
    )
    monkeypatch.setattr("api.ws_hub.get_hub", lambda: _Hub())

    v2 = OrchestratorV2(get_settings())
    inner = _Inner()
    monkeypatch.setattr(v2, "_get_inner", lambda: inner)
    guard = SimpleNamespace(charge=lambda value: None)

    result = await v2._critic_pass(
        "mission-internal",
        "agent",
        "task",
        "original",
        "auto",
        guard,
    )

    assert result == expected
    assert inner.calls == expected_runs
    assert resources.acquire_calls == expected_runs
    assert resources.release_calls == expected_runs
