from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from agent_cyber.findings import FindingStatus, SecurityFinding, Severity, VulnClass
from agent_cyber.mission_graph import (
    CyberFact,
    CyberIntent,
    CyberMissionGraph,
    FactStatus,
    IntentStatus,
)
from agent_cyber.scope import CyberScopePolicy


def _scope(**kwargs) -> CyberScopePolicy:
    return CyberScopePolicy(
        mission_id="m-graph-001",
        requested_by="test-user",
        **kwargs,
    )


def _intent(mission_id: str = "m-graph-001", **kwargs) -> CyberIntent:
    defaults = dict(
        mission_id=mission_id,
        goal="Review auth code",
        action_type="auth_review",
    )
    defaults.update(kwargs)
    return CyberIntent(**defaults)


def _graph(scope: CyberScopePolicy = None) -> CyberMissionGraph:
    s = scope or _scope()
    return CyberMissionGraph(mission_id="m-graph-001", scope=s)


def test_graph_init_empty():
    g = _graph()
    assert g.has_open_intents is False
    assert g.should_stop is True


def test_add_fact_tentative():
    g = _graph()
    fact = CyberFact(mission_id="m-graph-001", content="Input not sanitized", confidence=0.7)
    g.add_fact(fact)
    assert fact.fact_id in g.facts


def test_fact_confirmed_without_evidence_raises():
    with pytest.raises(ValueError):
        CyberFact(
            mission_id="m-001",
            content="SQL injection present",
            confidence=0.9,
            status=FactStatus.CONFIRMED,
        )


def test_fact_confirmed_with_evidence_ok():
    fact = CyberFact(
        mission_id="m-001",
        content="SQL injection present",
        confidence=0.9,
        status=FactStatus.CONFIRMED,
        evidence_refs=["ev-001"],
    )
    assert fact.status == FactStatus.CONFIRMED


def test_add_intent_open():
    g = _graph()
    intent = _intent()
    g.add_intent(intent)
    assert g.has_open_intents is True
    assert g.should_stop is False


def test_execute_intent_changes_status():
    g = _graph()
    intent = _intent()
    g.add_intent(intent)
    updated = g.execute_intent(intent.intent_id)
    assert updated.status == IntentStatus.IN_PROGRESS


def test_execute_done_intent_raises():
    g = _graph()
    intent = _intent()
    g.add_intent(intent)
    g.execute_intent(intent.intent_id)
    g.complete_intent(intent.intent_id)
    with pytest.raises(RuntimeError):
        g.execute_intent(intent.intent_id)


def test_execute_blocked_intent_raises():
    g = _graph()
    intent = _intent()
    g.add_intent(intent)
    g.block_intent(intent.intent_id, "Unauthorized")
    with pytest.raises(RuntimeError):
        g.execute_intent(intent.intent_id)


def test_complete_intent_done():
    g = _graph()
    intent = _intent()
    g.add_intent(intent)
    g.execute_intent(intent.intent_id)
    g.complete_intent(intent.intent_id, finding_ids=["f-001"])
    assert g.intents[intent.intent_id].status == IntentStatus.DONE
    assert "f-001" in g.findings


def test_block_intent():
    g = _graph()
    intent = _intent()
    g.add_intent(intent)
    g.block_intent(intent.intent_id, "No scope for this target")
    assert g.intents[intent.intent_id].status == IntentStatus.BLOCKED
    assert len(g.blockers) == 1


def test_should_stop_no_open_intents():
    g = _graph()
    intent = _intent()
    g.add_intent(intent)
    g.execute_intent(intent.intent_id)
    g.complete_intent(intent.intent_id)
    assert g.should_stop is True


def test_should_stop_expired_scope():
    scope = _scope(expires_at=datetime.utcnow() - timedelta(seconds=1))
    g = _graph(scope=scope)
    intent = _intent()
    g.add_intent(intent)
    assert g.has_open_intents is True
    assert g.should_stop is True


def test_execute_unknown_intent_raises():
    g = _graph()
    with pytest.raises(KeyError):
        g.execute_intent("nonexistent-id")


def test_multiple_intents_open_all_tracked():
    g = _graph()
    for i in range(3):
        g.add_intent(_intent(goal=f"Goal {i}"))
    assert g.has_open_intents is True
    open_count = sum(1 for i in g.intents.values() if i.status == IntentStatus.OPEN)
    assert open_count == 3
