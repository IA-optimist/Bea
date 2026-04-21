"""Tests for core/execution_policy.py — deterministic action approval."""


def test_import():
    pass


def test_manual_always_requires_approval():
    from core.execution_policy import ExecutionPolicy, ActionContext
    ep = ExecutionPolicy()
    ctx = ActionContext(
        mission_type="coding_task", risk_score=0, complexity="low",
        agent="forge-builder", action_type="read", estimated_impact="low",
        mode="MANUAL",
    )
    result = ep.evaluate(ctx)
    assert not result.approved
    assert result.decision == "REQUIRES_APPROVAL"


def test_supervised_safe_action_low_risk_approved():
    from core.execution_policy import ExecutionPolicy, ActionContext
    ep = ExecutionPolicy()
    for action in ["read", "write", "execute"]:
        ctx = ActionContext(
            mission_type="coding_task", risk_score=2, complexity="low",
            agent="test", action_type=action, estimated_impact="low",
            mode="SUPERVISED",
        )
        result = ep.evaluate(ctx)
        assert result.approved, f"{action} with risk=2 should be auto-approved in SUPERVISED"
        assert result.decision == "AUTO_APPROVED"


def test_supervised_high_risk_requires_approval():
    from core.execution_policy import ExecutionPolicy, ActionContext
    ep = ExecutionPolicy()
    ctx = ActionContext(
        mission_type="coding_task", risk_score=5, complexity="medium",
        agent="test", action_type="write", estimated_impact="medium",
        mode="SUPERVISED",
    )
    result = ep.evaluate(ctx)
    assert not result.approved
    assert result.decision == "REQUIRES_APPROVAL"


def test_auto_critical_actions_blocked():
    from core.execution_policy import ExecutionPolicy, ActionContext
    ep = ExecutionPolicy()
    for action in ["self_modify", "modify_config", "install", "network", "restart_service"]:
        ctx = ActionContext(
            mission_type="system_task", risk_score=1, complexity="low",
            agent="test", action_type=action, estimated_impact="low",
            mode="AUTO",
        )
        result = ep.evaluate(ctx)
        assert not result.approved, f"{action} should be blocked in AUTO"
        assert result.decision == "BLOCKED"


def test_auto_low_risk_read_approved():
    from core.execution_policy import ExecutionPolicy, ActionContext
    ep = ExecutionPolicy()
    ctx = ActionContext(
        mission_type="research_task", risk_score=1, complexity="low",
        agent="test", action_type="read", estimated_impact="low",
        mode="AUTO",
    )
    result = ep.evaluate(ctx)
    assert result.approved
    assert result.decision == "AUTO_APPROVED"


def test_auto_high_impact_requires_approval():
    from core.execution_policy import ExecutionPolicy, ActionContext
    ep = ExecutionPolicy()
    ctx = ActionContext(
        mission_type="coding_task", risk_score=2, complexity="low",
        agent="test", action_type="write", estimated_impact="high",
        mode="AUTO",
    )
    result = ep.evaluate(ctx)
    assert not result.approved
    assert result.decision == "REQUIRES_APPROVAL"


def test_auto_risk_exceeds_threshold():
    from core.execution_policy import ExecutionPolicy, ActionContext
    ep = ExecutionPolicy()
    ctx = ActionContext(
        mission_type="coding_task", risk_score=8, complexity="high",
        agent="test", action_type="write", estimated_impact="medium",
        mode="AUTO",
    )
    result = ep.evaluate(ctx)
    assert not result.approved


def test_unknown_mode_requires_approval():
    from core.execution_policy import ExecutionPolicy, ActionContext
    ep = ExecutionPolicy()
    ctx = ActionContext(
        mission_type="coding_task", risk_score=1, complexity="low",
        agent="test", action_type="read", estimated_impact="low",
        mode="UNKNOWN_MODE",
    )
    result = ep.evaluate(ctx)
    assert not result.approved
    assert result.decision == "REQUIRES_APPROVAL"


def test_unknown_action_type_defaults_to_execute():
    from core.execution_policy import ExecutionPolicy, ActionContext
    ep = ExecutionPolicy()
    ctx = ActionContext(
        mission_type="coding_task", risk_score=3, complexity="low",
        agent="test", action_type="nonexistent_action", estimated_impact="low",
        mode="AUTO",
    )
    result = ep.evaluate(ctx)
    assert result.action_type == "execute"


def test_singleton():
    from core.execution_policy import get_execution_policy
    ep1 = get_execution_policy()
    ep2 = get_execution_policy()
    assert ep1 is ep2
