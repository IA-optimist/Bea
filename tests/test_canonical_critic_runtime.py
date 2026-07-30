"""Runtime contract for the canonical MetaOrchestrator critic gate."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.orchestration.critic_policy import (
    CriticEvaluationError,
    CriticQualityRejected,
    CriticResourceBlocked,
    CriticRerunFailed,
)
from core.orchestration.execution_supervisor import ExecutionOutcome
from core.orchestration.outcome_mixin import OutcomeMixin
from core.resource_guard import ResourceSnapshot, SystemStatus
from core.state import MissionStatus
from kernel.evaluation.scorer import KernelScore


def _score(
    value: float,
    *,
    passed: bool,
    confidence: float | None = None,
    retry_recommended: bool = False,
    weaknesses: list[str] | None = None,
    verdict: str = "accept",
    failure_class: str = "",
) -> KernelScore:
    return KernelScore(
        score=value,
        passed=passed,
        confidence=value if confidence is None else confidence,
        retry_recommended=retry_recommended,
        weaknesses=weaknesses or [],
        improvement_suggestion="add evidence" if weaknesses else "",
        verdict=verdict,
        failure_class=failure_class,
    )


class _Trace:
    def __init__(self):
        self.records: list[tuple[tuple, dict]] = []

    def record(self, *args, **kwargs) -> None:
        self.records.append((args, kwargs))


class _CircuitBreaker:
    def __init__(self):
        self.successes = 0

    def record_success(self) -> None:
        self.successes += 1


class _Delegate:
    async def run(self, **kwargs):
        return SimpleNamespace(final_report="unused")


class _Host(OutcomeMixin):
    def __init__(self, *, force: bool = False):
        self.s = SimpleNamespace(critic_force_marginal_rerun=force)
        self.bea = _Delegate()
        self._circuit_breaker = _CircuitBreaker()
        self.transitions: list[MissionStatus] = []

    def _transition(self, ctx, status, **kwargs) -> None:
        ctx.status = status
        self.transitions.append(status)

    async def _store_mission_memories(self, *args, **kwargs) -> None:
        return None

    def _emit_completion_events(self, *args, **kwargs) -> None:
        return None

    def _execute_kernel_learning(self, *args, **kwargs) -> None:
        return None

    def _record_skills(self, *args, **kwargs) -> None:
        return None

    def _store_to_memory_facade(self, *args, **kwargs) -> None:
        return None


class _ResourceGuard:
    def __init__(self, status: SystemStatus, *, acquire: bool = True):
        self.snapshot = ResourceSnapshot(
            ram_total_mb=16_384,
            ram_used_mb=6_144,
            ram_avail_mb=10_240,
            ram_pct=37.5,
            cpu_pct=25.0,
            active_agents=0,
            status=status,
        )
        self.acquire_result = acquire
        self.acquire_calls = 0
        self.release_calls = 0

    def get_status(self) -> ResourceSnapshot:
        return self.snapshot

    def acquire_slot(self, agent_name: str, timeout: float = 0.0) -> bool:
        self.acquire_calls += 1
        return self.acquire_result

    def release_slot(self, agent_name: str) -> None:
        self.release_calls += 1


class _Evaluator:
    def __init__(self, *scores: KernelScore):
        self.scores = list(scores)
        self.calls = 0

    def evaluate(self, **kwargs) -> KernelScore:
        self.calls += 1
        if not self.scores:
            raise AssertionError("unexpected critic evaluation")
        return self.scores.pop(0)


def _ctx(result: str = "original result"):
    return SimpleNamespace(
        metadata={
            "_exec_enriched_goal": "A sufficiently long canonical mission goal " * 3,
            "_exec_risk": "low",
            "_exec_delegate": _Delegate(),
            "_exec_mission_timeout": 5,
            "_exec_needs_approval": False,
            "classification": {"task_type": "analysis"},
        },
        result=result,
        status=MissionStatus.REVIEW,
        error=None,
    )


async def _run_retry(
    monkeypatch,
    initial: KernelScore,
    *,
    resource_status: SystemStatus = SystemStatus.NORMAL,
    rerun_score: KernelScore | None = None,
    rerun_result: str = "improved result",
    force: bool = False,
    already_reran: bool = False,
    execution_retries: int = 0,
    acquire_slot: bool = True,
    rerun_exception: Exception | None = None,
):
    host = _Host(force=force)
    ctx = _ctx()
    if already_reran:
        ctx.metadata["_canonical_critic_rerun_done"] = True
    trace = _Trace()
    guard = _ResourceGuard(resource_status, acquire=acquire_slot)
    evaluator = _Evaluator(*(score for score in [rerun_score] if score is not None))
    supervisor_calls: list[dict] = []

    async def _supervise(*args, **kwargs):
        supervisor_calls.append(kwargs)
        if rerun_exception is not None:
            raise rerun_exception
        return ExecutionOutcome(success=True, result=rerun_result)

    monkeypatch.setattr("core.resource_guard.get_resource_guard", lambda settings=None: guard)
    monkeypatch.setattr(
        "kernel.evaluation.scorer.get_evaluator",
        lambda: evaluator,
    )
    monkeypatch.setattr(
        "core.orchestration.execution_supervisor.supervise",
        _supervise,
    )

    result = await host._handle_kernel_retry(
        ctx=ctx,
        mid="mission-1",
        goal="A sufficiently long canonical mission goal " * 3,
        mode="auto",
        trace=trace,
        outcome=ExecutionOutcome(success=True, result=ctx.result, retries=execution_retries),
        _reasoning_result=None,
        enriched_goal="A sufficiently long canonical mission goal " * 3,
        risk="low",
        needs_approval=False,
        force_approved=False,
        callback=None,
        delegate=_Delegate(),
        _mission_timeout=5,
        result_confidence=initial.confidence,
        _shape_val="report",
        kernel_score=initial,
    )
    return host, ctx, trace, guard, evaluator, supervisor_calls, result


@pytest.mark.asyncio
async def test_natural_pass_does_not_rerun(monkeypatch) -> None:
    host, ctx, _, guard, evaluator, calls, result = await _run_retry(
        monkeypatch,
        _score(0.6, passed=True),
    )

    assert result == pytest.approx(0.6)
    assert ctx.result == "original result"
    assert ctx.metadata["critic_decision"]["action"] == "accept"
    assert guard.acquire_calls == 0
    assert evaluator.calls == 0
    assert calls == []
    assert host.transitions == []


@pytest.mark.asyncio
async def test_natural_rerun_is_resource_gated_re_evaluated_and_bounded(
    monkeypatch,
) -> None:
    host, ctx, _, guard, evaluator, calls, result = await _run_retry(
        monkeypatch,
        _score(0.4, passed=False),
        rerun_score=_score(0.8, passed=True),
        rerun_result="better result",
    )

    assert result == pytest.approx(0.8)
    assert ctx.result == "better result"
    assert ctx.metadata["_canonical_critic_rerun_done"] is True
    assert ctx.metadata["critic_rerun"] == {
        "before": 0.4,
        "after": 0.8,
        "delta": 0.4,
        "forced": False,
        "accepted": True,
    }
    assert guard.acquire_calls == 1
    assert guard.release_calls == 1
    assert evaluator.calls == 1
    assert len(calls) == 1
    assert host.transitions == [MissionStatus.RUNNING, MissionStatus.REVIEW]


@pytest.mark.asyncio
async def test_natural_rerun_selects_pass_over_higher_failed_score(
    monkeypatch,
) -> None:
    _, ctx, _, _, _, _, result = await _run_retry(
        monkeypatch,
        _score(0.9, passed=False),
        rerun_score=_score(0.8, passed=True),
        rerun_result="lower score with a passing verdict",
    )

    assert result == pytest.approx(0.8)
    assert ctx.result == "lower score with a passing verdict"
    assert ctx.metadata["critic_rerun"]["accepted"] is True


@pytest.mark.asyncio
async def test_degraded_natural_rerun_keeps_original_and_rejects_quality(
    monkeypatch,
) -> None:
    with pytest.raises(CriticQualityRejected):
        host, ctx, _, guard, _, _, _ = await _run_retry(
            monkeypatch,
            _score(0.4, passed=False),
            rerun_score=_score(0.3, passed=False),
            rerun_result="worse result",
        )


@pytest.mark.asyncio
async def test_natural_rerun_blocked_by_resource_guard_is_not_executed(
    monkeypatch,
) -> None:
    with pytest.raises(CriticResourceBlocked):
        await _run_retry(
            monkeypatch,
            _score(0.4, passed=False),
            resource_status=SystemStatus.SAFE,
        )


@pytest.mark.asyncio
async def test_natural_rerun_is_blocked_when_resource_slot_cannot_be_reserved(
    monkeypatch,
) -> None:
    with pytest.raises(CriticResourceBlocked):
        await _run_retry(
            monkeypatch,
            _score(0.4, passed=False),
            acquire_slot=False,
        )


@pytest.mark.asyncio
async def test_natural_rerun_exception_is_explicit_and_not_a_loop(
    monkeypatch,
) -> None:
    with pytest.raises(CriticRerunFailed):
        await _run_retry(
            monkeypatch,
            _score(0.4, passed=False),
            rerun_exception=RuntimeError("delegate unavailable"),
        )


@pytest.mark.asyncio
async def test_natural_rerun_limit_prevents_a_second_attempt(monkeypatch) -> None:
    with pytest.raises(CriticQualityRejected):
        await _run_retry(
            monkeypatch,
            _score(0.4, passed=False),
            already_reran=True,
        )


@pytest.mark.asyncio
async def test_invalid_critic_score_is_an_explicit_error(monkeypatch) -> None:
    with pytest.raises(CriticEvaluationError):
        await _run_retry(
            monkeypatch,
            _score(
                0.0,
                passed=False,
                failure_class="critic_invalid_score",
            ),
        )


@pytest.mark.asyncio
async def test_forced_rerun_requires_server_gate_and_keeps_best_result(
    monkeypatch,
) -> None:
    host, ctx, _, guard, _, calls, result = await _run_retry(
        monkeypatch,
        _score(0.7, passed=True, weaknesses=["missing evidence"]),
        rerun_score=_score(0.65, passed=True),
        rerun_result="longer but lower-quality result",
        force=True,
    )

    assert result == pytest.approx(0.7)
    assert ctx.result == "original result"
    assert ctx.metadata["critic_decision"]["action"] == "forced_rerun"
    assert ctx.metadata["critic_rerun"]["forced"] is True
    assert ctx.metadata["critic_rerun"]["accepted"] is False
    assert guard.acquire_calls == guard.release_calls == 1
    assert len(calls) == 1
    assert host.transitions == [MissionStatus.RUNNING, MissionStatus.REVIEW]


@pytest.mark.asyncio
async def test_forced_rerun_never_replaces_pass_with_failed_verdict(
    monkeypatch,
) -> None:
    _, ctx, _, guard, _, calls, result = await _run_retry(
        monkeypatch,
        _score(0.65, passed=True, weaknesses=["missing evidence"]),
        rerun_score=_score(
            0.8,
            passed=False,
            retry_recommended=True,
            weaknesses=["critical omission"],
        ),
        rerun_result="higher score but failed verdict",
        force=True,
    )

    assert result == pytest.approx(0.65)
    assert ctx.result == "original result"
    assert ctx.metadata["critic_rerun"] == {
        "before": 0.65,
        "after": 0.8,
        "delta": 0.15,
        "forced": True,
        "accepted": False,
    }
    assert guard.acquire_calls == guard.release_calls == 1
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_failed_canonical_critic_never_transitions_to_done(
    monkeypatch,
) -> None:
    host = _Host()
    ctx = _ctx()
    ctx.status = MissionStatus.RUNNING
    trace = _Trace()
    guard = _ResourceGuard(SystemStatus.BLOCKED)
    evaluator = _Evaluator(_score(0.4, passed=False))

    monkeypatch.setattr("core.resource_guard.get_resource_guard", lambda settings=None: guard)
    monkeypatch.setattr("kernel.evaluation.scorer.get_evaluator", lambda: evaluator)

    result = await host._handle_success_outcome(
        outcome=ExecutionOutcome(
            success=True,
            result="original result",
            retries=0,
            duration_ms=10,
        ),
        ctx=ctx,
        mid="mission-fail",
        goal="A sufficiently long canonical mission goal " * 3,
        mode="auto",
        trace=trace,
        _reasoning_result=None,
        force_approved=False,
        callback=None,
    )

    assert result == pytest.approx(0.4)
    assert ctx.status is MissionStatus.FAILED
    assert MissionStatus.DONE not in host.transitions
    assert host._circuit_breaker.successes == 0
    assert ctx.metadata["critic_terminal"]["status"] == "failed"


@pytest.mark.asyncio
async def test_critic_exception_never_transitions_to_done(monkeypatch) -> None:
    host = _Host()
    ctx = _ctx()
    ctx.status = MissionStatus.RUNNING
    trace = _Trace()

    class _RaisingEvaluator:
        def evaluate(self, **kwargs):
            raise RuntimeError("critic unavailable")

    monkeypatch.setattr(
        "kernel.evaluation.scorer.get_evaluator",
        lambda: _RaisingEvaluator(),
    )

    result = await host._handle_success_outcome(
        outcome=ExecutionOutcome(
            success=True,
            result="original result",
            retries=0,
            duration_ms=10,
        ),
        ctx=ctx,
        mid="mission-error",
        goal="A sufficiently long canonical mission goal " * 3,
        mode="auto",
        trace=trace,
        _reasoning_result=None,
        force_approved=False,
        callback=None,
    )

    assert result == 0.0
    assert ctx.status is MissionStatus.FAILED
    assert MissionStatus.DONE not in host.transitions
    assert host._circuit_breaker.successes == 0
    assert ctx.metadata["critic_terminal"]["reason"] == "critic_evaluation_failed"


@pytest.mark.asyncio
async def test_success_is_recorded_only_after_canonical_critic_passes(
    monkeypatch,
) -> None:
    host = _Host()
    ctx = _ctx()
    ctx.status = MissionStatus.RUNNING
    trace = _Trace()
    guard = _ResourceGuard(SystemStatus.UNKNOWN)
    evaluator = _Evaluator(_score(0.7, passed=True))

    monkeypatch.setattr("core.resource_guard.get_resource_guard", lambda settings=None: guard)
    monkeypatch.setattr("kernel.evaluation.scorer.get_evaluator", lambda: evaluator)
    monkeypatch.setattr(
        "core.orchestration.output_formatter.format_output",
        lambda result, **kwargs: result,
    )

    result = await host._handle_success_outcome(
        outcome=ExecutionOutcome(
            success=True,
            result="adequate result",
            retries=0,
            duration_ms=10,
        ),
        ctx=ctx,
        mid="mission-pass",
        goal="A sufficiently long canonical mission goal " * 3,
        mode="auto",
        trace=trace,
        _reasoning_result=None,
        force_approved=False,
        callback=None,
    )

    assert result == pytest.approx(0.7)
    assert ctx.status is MissionStatus.DONE
    assert host.transitions[:2] == [MissionStatus.REVIEW, MissionStatus.DONE]
    assert host._circuit_breaker.successes == 1
