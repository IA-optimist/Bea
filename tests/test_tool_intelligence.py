"""Tests Tool Intelligence Layer V1 — fail-open partout."""
import pytest
pytestmark = pytest.mark.integration


# ── Helpers ────────────────────────────────────────────────────────────────────

def _obs(**kwargs):
    defaults = dict(tool_name="test_tool", success=True, execution_time=1.0,
                    retry_count=0, rollback_triggered=False, error_type="",
                    objective_id="obj1", task_id="t1", sequence_position=0,
                    difficulty_label="LOW", output_quality=0.8)
    defaults.update(kwargs)
    return defaults

# ── Test 1 ─────────────────────────────────────────────────────────────────────

def test_tool_observation_records_usage(tmp_path, monkeypatch):
    from core.tool_intelligence import tool_observer
    monkeypatch.setattr(tool_observer, "_OBS_PATH", tmp_path / "obs.json")
    entry = tool_observer.record_tool_call("shell", success=True, execution_time=0.5)
    assert entry.get("tool_name") == "shell"
    assert entry.get("success") is True

# ── Test 2 ─────────────────────────────────────────────────────────────────────

def test_tool_scoring_updates(tmp_path, monkeypatch):
    from core.tool_intelligence import tool_observer, tool_scorer
    monkeypatch.setattr(tool_observer, "_OBS_PATH", tmp_path / "obs.json")
    tool_scorer._SCORE_CACHE.clear()
    for _ in range(10):
        tool_observer.record_tool_call("python_tool", success=True, execution_time=2.0)
    score = tool_scorer.compute_tool_score("python_tool")
    assert 0.0 <= score["tool_score"] <= 1.0
    assert score["confidence"] > 0

# ── Test 3 ─────────────────────────────────────────────────────────────────────

def test_tool_sequence_pattern_detected(tmp_path, monkeypatch):
    from core.tool_intelligence import tool_observer
    monkeypatch.setattr(tool_observer, "_OBS_PATH", tmp_path / "obs.json")
    for i, t in enumerate(["vector_search", "python_tool", "file_write"]):
        tool_observer.record_tool_call(t, success=True, sequence_position=i, task_id="seq1")
    obs = tool_observer.get_observations()
    tools_in_order = [o["tool_name"] for o in obs if o.get("task_id") == "seq1"]
    assert tools_in_order == ["vector_search", "python_tool", "file_write"]

# ── Test 4 ─────────────────────────────────────────────────────────────────────

def test_tool_loop_detected():
    from core.tool_intelligence.anti_spam import check_tool_allowed, _task_tool_history
    _task_tool_history["loop_task"] = ["python_tool"] * 4
    result = check_tool_allowed("python_tool", task_id="loop_task")
    assert result["allowed"] is False
    assert "streak" in result["reason"]

# ── Test 5 ─────────────────────────────────────────────────────────────────────

def test_tool_retry_limit_triggered():
    from core.tool_intelligence.anti_spam import check_tool_allowed, _objective_tool_counts
    _objective_tool_counts["heavy_obj"] = 30
    result = check_tool_allowed("any_tool", objective_id="heavy_obj")
    assert result["allowed"] is False
    assert result["action"] in ("request_validation", "stop")

# ── Test 6 ─────────────────────────────────────────────────────────────────────

def test_tool_hint_injected(tmp_path, monkeypatch):
    from core.tool_intelligence import tool_observer, tool_scorer
    monkeypatch.setattr(tool_observer, "_OBS_PATH", tmp_path / "obs.json")
    tool_scorer._SCORE_CACHE.clear()
    for _ in range(20):
        tool_observer.record_tool_call("good_tool", success=True, execution_time=0.5)
    for _ in range(20):
        tool_observer.record_tool_call("bad_tool", success=False, execution_time=25.0)
    tool_scorer._SCORE_CACHE.clear()
    hints = tool_scorer.get_tool_hints(["good_tool", "bad_tool"])
    assert isinstance(hints["preferred_tools"], list)
    assert isinstance(hints["tools_to_avoid"], list)

# ── Test 7 ─────────────────────────────────────────────────────────────────────

def test_fail_open_if_module_missing():
    from core.tool_intelligence.planner_hints import get_hints_for_planner
    # Should never raise, even with garbage input
    result = get_hints_for_planner(available_tools=None, objective="")
    assert isinstance(result, dict)

# ── Test 8 ─────────────────────────────────────────────────────────────────────

def test_planner_behavior_unchanged_when_disabled(monkeypatch):
    monkeypatch.setenv("USE_TOOL_INTELLIGENCE", "false")
    from core.tool_intelligence.planner_hints import get_hints_for_planner
    hints = get_hints_for_planner(["tool_a"], "some objective")
    assert hints == {}  # disabled → empty

# ── Test 9 ─────────────────────────────────────────────────────────────────────

def test_json_fallback_if_qdrant_missing(tmp_path, monkeypatch):
    from core.tool_intelligence import tool_observer
    monkeypatch.setattr(tool_observer, "_OBS_PATH", tmp_path / "sub" / "obs.json")
    entry = tool_observer.record_tool_call("vector_search", success=False, error_type="qdrant_unavailable")
    assert entry.get("tool_name") == "vector_search"
    obs = tool_observer.get_observations("vector_search")
    assert len(obs) >= 1

# ── Test 10 ────────────────────────────────────────────────────────────────────

def test_no_duplicate_logging(tmp_path, monkeypatch):
    from core.tool_intelligence import tool_observer
    monkeypatch.setattr(tool_observer, "_OBS_PATH", tmp_path / "obs.json")
    tool_observer.record_tool_call("tool_x", success=True)
    tool_observer.record_tool_call("tool_x", success=True)
    obs = tool_observer.get_observations("tool_x")
    assert len(obs) == 2  # 2 calls = 2 entries, no dedup (dedup is not the goal)

# ── Test 11 ────────────────────────────────────────────────────────────────────

def test_tool_confidence_updates_over_time(tmp_path, monkeypatch):
    from core.tool_intelligence import tool_observer, tool_scorer
    monkeypatch.setattr(tool_observer, "_OBS_PATH", tmp_path / "obs.json")
    tool_scorer._SCORE_CACHE.clear()
    # With 0 data → confidence 0
    score_empty = tool_scorer.compute_tool_score("brand_new_tool")
    assert score_empty["confidence"] == 0.0
    # With 50 data → confidence 1.0
    for _ in range(50):
        tool_observer.record_tool_call("brand_new_tool", success=True)
    tool_scorer._SCORE_CACHE.clear()
    score_full = tool_scorer.compute_tool_score("brand_new_tool")
    assert score_full["confidence"] >= 0.9

# ── Test 12 ────────────────────────────────────────────────────────────────────

def test_tool_hints_receive_available_tools():
    """Tool hints doivent accepter une liste d'outils sans lever d'exception."""
    from core.tool_intelligence.planner_hints import get_hints_for_planner
    hints = get_hints_for_planner(
        available_tools=["shell_execution", "python_execution", "vector_search"],
        objective="run a python script"
    )
    assert isinstance(hints, dict)
    from core.tool_intelligence import is_enabled
    if is_enabled():
        assert "preferred_tools" in hints
        assert "tools_to_avoid" in hints
