from types import SimpleNamespace

from core.orchestrator_v2 import (
    _MAX_RERUNS,
    _critic_rerun_log_context,
    _should_force_low_viability_rerun,
)
from core.self_critic import CRITIC_OVERALL_PASS_THRESHOLD


def _report(overall: float, rerun_count: int):
    return SimpleNamespace(overall=overall, rerun_count=rerun_count)


def test_low_viability_forces_marginal_report():
    assert _should_force_low_viability_rerun(
        natural_should_rerun=False,
        viability=0.2,
        report=_report(CRITIC_OVERALL_PASS_THRESHOLD + 0.5, 0),
    )


def test_high_viability_does_not_force():
    assert not _should_force_low_viability_rerun(
        natural_should_rerun=False,
        viability=0.9,
        report=_report(CRITIC_OVERALL_PASS_THRESHOLD + 0.5, 0),
    )


def test_already_good_work_does_not_force():
    assert not _should_force_low_viability_rerun(
        natural_should_rerun=False,
        viability=0.2,
        report=_report(8.0, 0),
    )


def test_natural_should_rerun_stays_natural():
    assert not _should_force_low_viability_rerun(
        natural_should_rerun=True,
        viability=0.2,
        report=_report(4.9, 0),
    )


def test_max_reruns_blocks_forcing():
    assert not _should_force_low_viability_rerun(
        natural_should_rerun=False,
        viability=0.2,
        report=_report(CRITIC_OVERALL_PASS_THRESHOLD + 0.5, _MAX_RERUNS),
    )


def test_critic_rerun_log_context_includes_forced_flag_and_delta():
    payload = _critic_rerun_log_context(
        agent_name="agent-a",
        before=5.5,
        after=6.25,
        forced=True,
    )

    assert payload["agent"] == "agent-a"
    assert payload["before"] == 5.5
    assert payload["after"] == 6.25
    assert payload["delta"] == 0.75
    assert payload["forced"] is True


def test_critic_rerun_log_context_keeps_forced_false():
    payload = _critic_rerun_log_context(
        agent_name="agent-a",
        before=7.0,
        after=7.25,
        forced=False,
    )

    assert payload["forced"] is False


def test_critic_overall_threshold_source_of_truth():
    assert CRITIC_OVERALL_PASS_THRESHOLD == 6.0
