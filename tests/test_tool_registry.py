"""Tests for core/tool_registry.py — tool definitions and scoring."""


def test_import():
    pass


def test_registry_has_base_tools():
    from core.tool_registry import get_tool_registry
    reg = get_tool_registry()
    tools = reg.list_tools()
    assert len(tools) >= 7  # base tools
    names = [t.name for t in tools]
    assert "read_file" in names
    assert "write_file" in names
    assert "list_directory" in names


def test_get_tool_by_name():
    from core.tool_registry import get_tool_registry
    reg = get_tool_registry()
    tool = reg.get_tool("read_file")
    assert tool is not None
    assert tool.risk_level == "low"
    assert tool.idempotent is True


def test_get_tool_nonexistent():
    from core.tool_registry import get_tool_registry
    reg = get_tool_registry()
    assert reg.get_tool("nonexistent_tool") is None


def test_get_tools_for_mission_type():
    from core.tool_registry import get_tool_registry
    reg = get_tool_registry()
    coding_tools = reg.get_tools_for_mission_type("coding_task")
    names = [t.name for t in coding_tools]
    assert "write_file" in names


def test_get_tools_for_unknown_mission():
    from core.tool_registry import get_tool_registry
    reg = get_tool_registry()
    tools = reg.get_tools_for_mission_type("nonexistent_mission")
    assert tools == []


def test_safe_tools_manual_returns_empty():
    from core.tool_registry import get_tool_registry
    reg = get_tool_registry()
    assert reg.get_safe_tools("MANUAL") == []


def test_safe_tools_supervised():
    from core.tool_registry import get_tool_registry
    reg = get_tool_registry()
    safe = reg.get_safe_tools("SUPERVISED")
    for t in safe:
        assert t.risk_level == "low"


def test_summary_format():
    from core.tool_registry import get_tool_registry
    reg = get_tool_registry()
    summary = reg.summary()
    assert isinstance(summary, list)
    if summary:
        assert "name" in summary[0]
        assert "risk" in summary[0]


# ── Scoring ───────────────────────────────────────────────────

def test_score_returns_float():
    from core.tool_registry import score_tool_relevance
    score = score_tool_relevance("read a file from disk", "read_file")
    assert isinstance(score, float)
    assert 0.0 <= score <= 1.0


def test_rank_tools():
    from core.tool_registry import rank_tools_for_task
    ranked = rank_tools_for_task("search for pattern in files", top_k=3)
    assert isinstance(ranked, list)
    assert len(ranked) <= 3
    if ranked:
        assert "name" in ranked[0]
        assert "score" in ranked[0]


def test_should_create_tool():
    from core.tool_registry import should_create_tool
    result = should_create_tool("read a file")
    assert isinstance(result, dict)
    assert "should_create" in result
    assert "reason" in result


def test_list_all_tools():
    from core.tool_registry import list_all_tools
    tools = list_all_tools()
    assert isinstance(tools, list)
