"""Runtime contract for OrchestratorV2._critic_pass.

Exercises the real _critic_pass flow in isolation with boundary fakes only:
natural rerun, forced low-viability rerun, no rerun, good work under low
viability, and budget failure during rerun.
"""
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Callable

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core.improvement_memory as improvement_memory
import core.orchestrator_v2 as ov2
import core.self_critic as self_critic


@dataclass
class _Scores:
    overall: float


@dataclass
class _CriticReport:
    overall: float
    rerun_count: int = 0
    feedback: str = "feedback"
    suggestions: list[str] | None = None
    task_hash: str = "task-hash"

    @property
    def scores(self) -> _Scores:
        return _Scores(self.overall)

    def __post_init__(self) -> None:
        if self.suggestions is None:
            self.suggestions = ["suggestion"]


class _FakeCritic:
    def __init__(self, *, should: bool, before: float, after: float, rerun_count: int = 0) -> None:
        self.should = should
        self.before = before
        self.after = after
        self.rerun_count = rerun_count
        self.evaluate_calls = 0
        self.increment_calls = 0
        self.prompts: list[str] = []

    async def evaluate(self, session_id: str, agent_name: str, task: str, report: str) -> _CriticReport:
        self.evaluate_calls += 1
        if self.evaluate_calls == 1:
            return _CriticReport(overall=self.before, rerun_count=self.rerun_count)
        return _CriticReport(overall=self.after, rerun_count=self.rerun_count)

    def should_rerun(self, report: _CriticReport) -> bool:
        return self.should

    def build_rerun_prompt(
        self,
        task: str,
        report: str,
        feedback: str,
        suggestions: list[str] | None,
    ) -> str:
        prompt = f"rerun::{task}::{feedback}::{','.join(suggestions or [])}"
        self.prompts.append(prompt)
        return prompt

    def increment_rerun(self, task_hash: str) -> None:
        self.increment_calls += 1


class _FakeInner:
    def __init__(self, final_report: str = "improved report") -> None:
        self.final_report = final_report
        self.run_calls = 0
        self.last_user_input: str | None = None

    async def run(self, *, user_input: str, mode: str, session_id: str):
        self.run_calls += 1
        self.last_user_input = user_input
        return SimpleNamespace(final_report=self.final_report)


class _FakeGuard:
    def __init__(self, *, fail_on_charge: int | None = None) -> None:
        self.fail_on_charge = fail_on_charge
        self.calls = 0

    def charge(self, value: str) -> None:
        self.calls += 1
        if self.fail_on_charge is not None and self.calls == self.fail_on_charge:
            raise ov2.BudgetExceeded("budget exceeded in test")


class _FakeHomeostasis:
    def __init__(self, value: float) -> None:
        self.value = value
        self.calls = 0

    def viability(self) -> float:
        self.calls += 1
        return self.value


class _FakeAffect:
    def render_guidance(self) -> str:
        return ""


class _FakeMemory:
    async def record_improvement(self, **kwargs) -> None:
        return None


class _FakeHub:
    def __init__(self) -> None:
        self.calls = 0

    async def emit_agent_thinking(self, *args, **kwargs) -> None:
        self.calls += 1


def _run(coro):
    return asyncio.run(coro)


def _with_patches(critic: _FakeCritic, emitted: list[dict], fn: Callable[[], str]) -> str:
    old_get_critic = self_critic.get_critic
    old_get_improvement_memory = improvement_memory.get_improvement_memory
    old_emit = ov2.emit
    old_ws_module = sys.modules.get("api.ws_hub")
    had_ws_module = "api.ws_hub" in sys.modules
    try:
        self_critic.get_critic = lambda settings: critic
        improvement_memory.get_improvement_memory = lambda settings: _FakeMemory()

        def capture_emit(**kwargs):
            emitted.append(kwargs)
            return SimpleNamespace(event_id="captured")

        ov2.emit = capture_emit

        ws_module = ModuleType("api.ws_hub")
        ws_module.get_hub = lambda: _FakeHub()
        sys.modules["api.ws_hub"] = ws_module

        return fn()
    finally:
        self_critic.get_critic = old_get_critic
        improvement_memory.get_improvement_memory = old_get_improvement_memory
        ov2.emit = old_emit
        if had_ws_module:
            sys.modules["api.ws_hub"] = old_ws_module
        else:
            sys.modules.pop("api.ws_hub", None)


def _invoke(
    *,
    homeostasis: _FakeHomeostasis,
    inner: _FakeInner,
    guard: _FakeGuard,
    report: str = "initial report",
) -> str:
    fake_self = SimpleNamespace(
        s=SimpleNamespace(),
        homeostasis=homeostasis,
        affect=_FakeAffect(),
        _get_inner=lambda: inner,
    )
    return _run(
        ov2.OrchestratorV2._critic_pass(
            fake_self,
            "session-test",
            "agent-test",
            "task-test",
            report,
            "auto",
            guard,
        )
    )


def scenario_natural_rerun() -> tuple[bool, str]:
    emitted: list[dict] = []
    critic = _FakeCritic(should=True, before=4.0, after=7.25)
    homeostasis = _FakeHomeostasis(0.9)
    inner = _FakeInner()
    guard = _FakeGuard()

    result = _with_patches(
        critic,
        emitted,
        lambda: _invoke(homeostasis=homeostasis, inner=inner, guard=guard),
    )

    payload = emitted[0]["payload"] if emitted else {}
    ok = (
        result == "improved report"
        and len(emitted) == 1
        and payload.get("kind") == "critic_rerun"
        and payload.get("forced") is False
        and payload.get("floor_triggered") is False
        and payload.get("viability") is None
        and payload.get("before") == 4.0
        and payload.get("after") == 7.25
        and payload.get("delta") == 3.25
        and homeostasis.calls == 0
        and inner.run_calls == 1
        and critic.evaluate_calls == 2
        and critic.increment_calls == 1
        and guard.calls == 2
    )
    detail = (
        f"result={result!r} emits={len(emitted)} payload={payload} "
        f"viability_calls={homeostasis.calls} inner_runs={inner.run_calls} "
        f"evaluate_calls={critic.evaluate_calls} increment_calls={critic.increment_calls} "
        f"guard_calls={guard.calls}"
    )
    return ok, detail


def scenario_forced_rerun() -> tuple[bool, str]:
    emitted: list[dict] = []
    critic = _FakeCritic(should=False, before=6.5, after=7.2)
    homeostasis = _FakeHomeostasis(0.2)
    inner = _FakeInner()
    guard = _FakeGuard()

    result = _with_patches(
        critic,
        emitted,
        lambda: _invoke(homeostasis=homeostasis, inner=inner, guard=guard),
    )

    payload = emitted[0]["payload"] if emitted else {}
    ok = (
        result == "improved report"
        and len(emitted) == 1
        and payload.get("kind") == "critic_rerun"
        and payload.get("forced") is True
        and payload.get("floor_triggered") is False
        and payload.get("viability") == 0.2
        and payload.get("before") == 6.5
        and payload.get("after") == 7.2
        and payload.get("delta") == 0.7
        and homeostasis.calls == 1
        and inner.run_calls == 1
        and critic.evaluate_calls == 2
        and critic.increment_calls == 1
        and guard.calls == 2
    )
    detail = (
        f"result={result!r} emits={len(emitted)} payload={payload} "
        f"viability_calls={homeostasis.calls} inner_runs={inner.run_calls} "
        f"evaluate_calls={critic.evaluate_calls} increment_calls={critic.increment_calls} "
        f"guard_calls={guard.calls}"
    )
    return ok, detail


def scenario_rigor_floor() -> tuple[bool, str]:
    emitted: list[dict] = []
    critic = _FakeCritic(should=False, before=6.8, after=7.4)
    homeostasis = _FakeHomeostasis(0.9)
    inner = _FakeInner()
    guard = _FakeGuard()

    result = _with_patches(
        critic,
        emitted,
        lambda: _invoke(homeostasis=homeostasis, inner=inner, guard=guard),
    )

    payload = emitted[0]["payload"] if emitted else {}
    ok = (
        result == "improved report"
        and len(emitted) == 1
        and payload.get("kind") == "critic_rerun"
        and payload.get("forced") is True
        and payload.get("floor_triggered") is True
        and payload.get("viability") == 0.9
        and payload.get("before") == 6.8
        and payload.get("after") == 7.4
        and payload.get("delta") == 0.6
        and homeostasis.calls == 1
        and inner.run_calls == 1
        and critic.evaluate_calls == 2
        and critic.increment_calls == 1
        and guard.calls == 2
    )
    detail = (
        f"result={result!r} emits={len(emitted)} payload={payload} "
        f"viability_calls={homeostasis.calls} inner_runs={inner.run_calls} "
        f"evaluate_calls={critic.evaluate_calls} increment_calls={critic.increment_calls} "
        f"guard_calls={guard.calls}"
    )
    return ok, detail


def scenario_no_rerun_above_floor() -> tuple[bool, str]:
    emitted: list[dict] = []
    critic = _FakeCritic(should=False, before=7.2, after=7.8)
    homeostasis = _FakeHomeostasis(0.9)
    inner = _FakeInner()
    guard = _FakeGuard()

    result = _with_patches(
        critic,
        emitted,
        lambda: _invoke(homeostasis=homeostasis, inner=inner, guard=guard),
    )

    ok = (
        result == "initial report"
        and len(emitted) == 0
        and inner.run_calls == 0
        and homeostasis.calls == 1
        and critic.evaluate_calls == 1
        and critic.increment_calls == 0
        and guard.calls == 0
    )
    detail = (
        f"result={result!r} emits={len(emitted)} viability_calls={homeostasis.calls} "
        f"inner_runs={inner.run_calls} evaluate_calls={critic.evaluate_calls} "
        f"increment_calls={critic.increment_calls} guard_calls={guard.calls}"
    )
    return ok, detail


def scenario_low_viability_good_work() -> tuple[bool, str]:
    emitted: list[dict] = []
    critic = _FakeCritic(should=False, before=8.0, after=8.5)
    homeostasis = _FakeHomeostasis(0.2)
    inner = _FakeInner()
    guard = _FakeGuard()

    result = _with_patches(
        critic,
        emitted,
        lambda: _invoke(homeostasis=homeostasis, inner=inner, guard=guard),
    )

    ok = (
        result == "initial report"
        and len(emitted) == 0
        and inner.run_calls == 0
        and homeostasis.calls == 1
        and critic.evaluate_calls == 1
        and critic.increment_calls == 0
        and guard.calls == 0
    )
    detail = (
        f"result={result!r} emits={len(emitted)} viability_calls={homeostasis.calls} "
        f"inner_runs={inner.run_calls} evaluate_calls={critic.evaluate_calls} "
        f"increment_calls={critic.increment_calls} guard_calls={guard.calls}"
    )
    return ok, detail


def scenario_budget_exceeded_no_emit() -> tuple[bool, str]:
    emitted: list[dict] = []
    critic = _FakeCritic(should=False, before=6.5, after=7.2)
    homeostasis = _FakeHomeostasis(0.2)
    inner = _FakeInner()
    guard = _FakeGuard(fail_on_charge=1)

    result = _with_patches(
        critic,
        emitted,
        lambda: _invoke(homeostasis=homeostasis, inner=inner, guard=guard),
    )

    ok = (
        result == "initial report"
        and len(emitted) == 0
        and inner.run_calls == 0
        and guard.calls == 1
        and homeostasis.calls == 1
        and critic.evaluate_calls == 1
        and critic.increment_calls == 0
    )
    detail = (
        f"result={result!r} emits={len(emitted)} guard_calls={guard.calls} "
        f"inner_runs={inner.run_calls} viability_calls={homeostasis.calls} "
        f"evaluate_calls={critic.evaluate_calls} increment_calls={critic.increment_calls}"
    )
    return ok, detail


def _assert_ok(result: tuple[bool, str]) -> None:
    ok, detail = result
    assert ok, detail


def test_natural_rerun_contract() -> None:
    _assert_ok(scenario_natural_rerun())


def test_forced_rerun_contract() -> None:
    _assert_ok(scenario_forced_rerun())


def test_rigor_floor_contract() -> None:
    _assert_ok(scenario_rigor_floor())


def test_no_rerun_above_floor_contract() -> None:
    _assert_ok(scenario_no_rerun_above_floor())


def test_low_viability_good_work_contract() -> None:
    _assert_ok(scenario_low_viability_good_work())


def test_budget_exceeded_no_emit_contract() -> None:
    _assert_ok(scenario_budget_exceeded_no_emit())


def report(name: str, result: tuple[bool, str]) -> bool:
    ok, detail = result
    print(f"{name}: {'PASS' if ok else 'FAIL'}  {detail}")
    return ok


def main() -> None:
    print("# Critic rerun runtime contract")
    print("Teste _critic_pass en isolation, mocks aux frontieres.")

    results = [
        report("natural_rerun", scenario_natural_rerun()),
        report("forced_rerun", scenario_forced_rerun()),
        report("rigor_floor", scenario_rigor_floor()),
        report("no_rerun_above_floor", scenario_no_rerun_above_floor()),
        report("low_viability_good_work", scenario_low_viability_good_work()),
        report("budget_exceeded_no_emit", scenario_budget_exceeded_no_emit()),
    ]

    ok = all(results)
    print(f"overall: {'PASS' if ok else 'FAIL'}")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
