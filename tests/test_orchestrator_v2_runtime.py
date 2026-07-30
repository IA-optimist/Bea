from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.orchestrator_v2 import OrchestratorV2
from config.settings import get_settings


def test_get_inner_does_not_raise_module_not_found():
    """Regression: OrchestratorV2 must not crash on a missing legacy module."""
    v2 = OrchestratorV2(get_settings())
    inner = v2._get_inner()
    assert inner is not None
    assert type(inner).__name__ == "BeaOrchestrator"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("rerun_score", "expected"),
    [(4.0, "original"), (7.0, "improved")],
)
async def test_compatibility_critic_returns_only_a_strictly_better_rerun(
    monkeypatch,
    rerun_score: float,
    expected: str,
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
        async def run(self, **kwargs):
            return SimpleNamespace(final_report="improved")

    class _Hub:
        async def emit_agent_thinking(self, *args, **kwargs):
            return None

    monkeypatch.setattr("core.self_critic.get_critic", lambda settings=None: _Critic())
    monkeypatch.setattr("api.ws_hub.get_hub", lambda: _Hub())

    v2 = OrchestratorV2(get_settings())
    monkeypatch.setattr(v2, "_get_inner", lambda: _Inner())
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
