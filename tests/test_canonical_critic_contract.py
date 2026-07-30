"""Canonical contract for critic decisions and bounded rerun reservations.

These tests intentionally describe the target API before its implementation.
They exercise only deterministic, in-memory behavior.
"""

from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from core.orchestration.critic_policy import (
    CriticAction,
    CriticDecision,
    decide_critic_action,
)
from core.resource_guard import SystemStatus
from core.self_critic import CriticAgent, CriticReport, CriticScores
from kernel.evaluation.scorer import (
    CRITIC_OVERALL_PASS_THRESHOLD,
    PASS_THRESHOLD,
    KernelEvaluator,
    KernelScore,
)


def _kernel_score(
    score: float,
    *,
    passed: bool,
    retry_recommended: bool = False,
    weaknesses: list[str] | None = None,
    verdict: str = "accept",
    confidence: float = 0.7,
) -> KernelScore:
    return KernelScore(
        score=score,
        passed=passed,
        confidence=confidence,
        retry_recommended=retry_recommended,
        weaknesses=weaknesses or [],
        verdict=verdict,
    )


def _decision(
    kernel_score: KernelScore,
    resource_status: SystemStatus = SystemStatus.NORMAL,
    **kwargs,
) -> CriticDecision:
    decision = decide_critic_action(
        kernel_score,
        resource_status,
        **kwargs,
    )
    assert isinstance(decision, CriticDecision)
    return decision


def _report(
    *,
    session_id: str = "session-a",
    agent_name: str = "agent-a",
    task: str = "same task",
) -> CriticReport:
    return CriticReport(
        session_id=session_id,
        agent_name=agent_name,
        task=task,
        task_hash="deliberately-shared-hash",
        scores=CriticScores(),
    )


def test_canonical_thresholds_are_single_source_of_truth():
    assert CRITIC_OVERALL_PASS_THRESHOLD == 6.0
    assert PASS_THRESHOLD == 0.6
    assert KernelEvaluator.PASS_THRESHOLD == PASS_THRESHOLD


@pytest.mark.parametrize(
    "kernel_score",
    [
        _kernel_score(0.59, passed=True),
        _kernel_score(0.80, passed=False),
        _kernel_score(0.80, passed=True, retry_recommended=True),
    ],
    ids=["below-threshold", "not-passed", "retry-recommended"],
)
def test_natural_rerun_follows_every_kernel_failure_signal(kernel_score):
    decision = _decision(kernel_score)
    assert decision.action is CriticAction.NATURAL_RERUN


def test_naturally_passing_score_is_accepted_without_forcing():
    decision = _decision(_kernel_score(0.60, passed=True))
    assert decision.action is CriticAction.ACCEPT


@pytest.mark.parametrize(
    "resource_status",
    [SystemStatus.NORMAL, SystemStatus.SOFT_WARN],
)
def test_natural_rerun_is_permitted_when_resources_allow_it(resource_status):
    decision = _decision(
        _kernel_score(0.59, passed=False),
        resource_status,
    )
    assert decision.action is CriticAction.NATURAL_RERUN


@pytest.mark.parametrize(
    "resource_status",
    [SystemStatus.SAFE, SystemStatus.BLOCKED, SystemStatus.UNKNOWN],
)
def test_natural_rerun_is_blocked_when_resources_are_not_available(resource_status):
    decision = _decision(
        _kernel_score(0.59, passed=False),
        resource_status,
    )
    assert decision.action is CriticAction.BLOCKED


@pytest.mark.parametrize(
    "kernel_score",
    [
        _kernel_score(0.65, passed=True, weaknesses=["missing evidence"]),
        _kernel_score(0.90, passed=True, verdict="low_confidence"),
    ],
    ids=["explicit-weakness", "low-confidence-verdict"],
)
def test_forced_rerun_requires_an_explicit_server_side_quality_signal(kernel_score):
    decision = _decision(
        kernel_score,
        forced_enabled=True,
        goal_length=81,
    )
    assert decision.action is CriticAction.FORCED_RERUN


def test_forcing_gate_does_not_rerun_a_clean_pass():
    decision = _decision(
        _kernel_score(0.60, passed=True),
        forced_enabled=True,
        goal_length=200,
    )
    assert decision.action is CriticAction.ACCEPT


def test_explicit_quality_signal_does_not_force_when_server_gate_is_disabled():
    decision = _decision(
        _kernel_score(0.65, passed=True, weaknesses=["missing evidence"]),
        forced_enabled=False,
        goal_length=200,
    )
    assert decision.action is CriticAction.ACCEPT


@pytest.mark.parametrize(
    ("already_reran", "execution_retries", "goal_length"),
    [
        (True, 0, 200),
        (False, 1, 200),
        (False, 0, 80),
    ],
    ids=["already-reran", "execution-retry-exists", "goal-not-long-enough"],
)
def test_forced_rerun_is_bounded(
    already_reran,
    execution_retries,
    goal_length,
):
    decision = _decision(
        _kernel_score(0.65, passed=True, weaknesses=["missing evidence"]),
        forced_enabled=True,
        already_reran=already_reran,
        execution_retries=execution_retries,
        goal_length=goal_length,
    )
    assert decision.action is CriticAction.ACCEPT


@pytest.mark.parametrize(
    "resource_status",
    [
        SystemStatus.SOFT_WARN,
        SystemStatus.SAFE,
        SystemStatus.BLOCKED,
        SystemStatus.UNKNOWN,
    ],
)
def test_forced_rerun_requires_normal_resources(resource_status):
    decision = _decision(
        _kernel_score(0.65, passed=True, weaknesses=["missing evidence"]),
        resource_status,
        forced_enabled=True,
        goal_length=200,
    )
    assert decision.action is CriticAction.ACCEPT


@pytest.mark.parametrize(
    "invalid_score",
    [
        pytest.param(float("nan"), id="nan"),
        pytest.param(float("inf"), id="positive-infinity"),
        pytest.param(float("-inf"), id="negative-infinity"),
        pytest.param(-0.01, id="below-zero"),
        pytest.param(1.01, id="above-one"),
    ],
)
def test_invalid_kernel_scores_produce_an_error_decision(invalid_score):
    decision = _decision(
        _kernel_score(invalid_score, passed=False),
    )
    assert decision.action is CriticAction.ERROR


@pytest.mark.parametrize(
    "invalid_confidence",
    [float("nan"), float("inf"), float("-inf"), -0.01, 1.01],
)
def test_invalid_kernel_confidence_produces_an_error_decision(
    invalid_confidence,
):
    decision = _decision(
        _kernel_score(
            0.8,
            passed=True,
            confidence=invalid_confidence,
        ),
    )
    assert decision.action is CriticAction.ERROR


def test_kernel_runtime_evaluation_exception_is_never_a_pass():
    from kernel.runtime.kernel import BeaKernel

    class RaisingEvaluator:
        def evaluate(self, **kwargs):
            raise RuntimeError("evaluator unavailable")

    kernel = BeaKernel()
    kernel._evaluator = RaisingEvaluator()

    score = kernel.evaluate("goal", "result")

    assert score.passed is False
    assert score.score == 0.0
    assert score.failure_class == "critic_evaluation_error"
    assert _decision(score).action is CriticAction.ERROR


def test_critic_scores_accept_inclusive_bounds():
    scores = CriticScores(
        correctness=0.0,
        completeness=10.0,
        safety=0.0,
        efficiency=10.0,
    )
    assert scores.overall == 5.0


@pytest.mark.parametrize(
    "invalid_value",
    [
        pytest.param(float("nan"), id="nan"),
        pytest.param(float("inf"), id="positive-infinity"),
        pytest.param(float("-inf"), id="negative-infinity"),
        pytest.param(-0.01, id="below-zero"),
        pytest.param(10.01, id="above-ten"),
    ],
)
def test_critic_scores_reject_non_finite_or_out_of_range_values(invalid_value):
    with pytest.raises(ValueError):
        CriticScores(correctness=invalid_value)


def test_reserve_rerun_enforces_two_attempt_cap():
    critic = CriticAgent()
    report = _report()

    assert critic.reserve_rerun(report) is True
    assert critic.reserve_rerun(report) is True
    assert critic.reserve_rerun(report) is False


def test_rerun_scope_isolated_by_session_agent_and_task():
    critic = CriticAgent()
    original = _report()

    assert critic.reserve_rerun(original) is True
    assert critic.reserve_rerun(original) is True
    assert critic.reserve_rerun(original) is False

    assert critic.reserve_rerun(_report(session_id="session-b")) is True
    assert critic.reserve_rerun(_report(agent_name="agent-b")) is True
    assert critic.reserve_rerun(_report(task="different task")) is True


def test_reserve_rerun_is_atomic_under_concurrency():
    critic = CriticAgent()
    report = _report()
    attempts = 16
    ready = threading.Barrier(attempts)

    def reserve_once() -> bool:
        ready.wait(timeout=5)
        return critic.reserve_rerun(report)

    with ThreadPoolExecutor(max_workers=attempts) as executor:
        reservations = list(executor.map(lambda _: reserve_once(), range(attempts)))

    assert sum(reservations) == 2


@pytest.mark.asyncio
async def test_compatibility_report_history_is_redacted_and_session_scoped():
    critic = CriticAgent()

    live_a = await critic.evaluate(
        "session-a",
        "agent",
        "private task a",
        "private output a",
    )
    await critic.evaluate(
        "session-b",
        "agent",
        "private task b",
        "private output b",
    )

    reports_a = critic.get_reports("session-a")
    reports_b = critic.get_reports("session-b")

    assert live_a.task == "private task a"
    assert live_a.output == "private output a"
    assert len(reports_a) == len(reports_b) == 1
    assert reports_a[0].session_id not in {"session-a", "session-b"}
    assert reports_a[0].task == ""
    assert reports_a[0].output == ""
    assert reports_a[0].feedback == ""
    assert reports_a[0].suggestions == []
    assert reports_a[0].report_id != reports_b[0].report_id
    assert critic.get_reports("missing-session") == []


def test_rerun_scope_registry_is_cardinality_bounded(monkeypatch):
    monkeypatch.setattr("core.self_critic._MAX_RERUN_SCOPES", 3)
    critic = CriticAgent()

    for index in range(5):
        assert critic.reserve_rerun(
            _report(session_id=f"session-{index}")
        ) is True

    assert len(critic._rerun_counts) == 3
