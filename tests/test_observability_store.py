from __future__ import annotations


def test_observability_store_persists_and_replays(tmp_path) -> None:
    from core.observability.store import MissionMetrics, ObservabilityStore

    path = tmp_path / "observability_missions.jsonl"
    store = ObservabilityStore(storage_path=path)
    store.record(
        MissionMetrics(
            mission_id="m-1",
            mission_type="analysis",
            selected_agents=["scout", "builder"],
            execution_policy_decision="AUTO_APPROVED",
            fallback_level_used=0,
            confidence_score=0.91,
            duration_ms=123,
            tools_used=["memory_search"],
        )
    )

    assert store.verify_chain() is True
    assert len(store.get_recent()) == 1
    assert len(store.replay()) == 1

    reloaded = ObservabilityStore(storage_path=path)
    assert len(reloaded.get_recent()) == 1
    assert reloaded.verify_chain() is True


def test_observability_store_clear_removes_persisted_state(tmp_path) -> None:
    from core.observability.store import MissionMetrics, ObservabilityStore

    path = tmp_path / "observability_missions.jsonl"
    store = ObservabilityStore(storage_path=path)
    store.record(
        MissionMetrics(
            mission_id="m-2",
            mission_type="analysis",
            selected_agents=["reviewer"],
            execution_policy_decision="REQUIRES_APPROVAL",
            fallback_level_used=1,
            confidence_score=0.42,
            duration_ms=456,
            tools_used=["audit"],
        )
    )

    assert path.exists()
    store.clear()
    assert not path.exists()
    assert store.get_recent() == []
    assert store.replay() == []
