from core.orchestrator_v2 import _critic_rerun_log_context


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
