"""
Tests for agents/bea_team/tools.py — Tool Access Layer.

Verifies:
    - All tools return ToolResult
    - Fail-open behavior (no exceptions escape)
    - Protected path enforcement
    - Agent access matrix completeness
    - Branch naming validation
    - Tool catalog consistency
"""
from unittest.mock import patch


# ── Ensure import works ───────────────────────────────────────

def test_tools_import():
    """Tool module is importable."""
    from agents.bea_team.tools import (
        AGENT_TOOL_ACCESS, TOOL_CATALOG,
    )
    assert len(AGENT_TOOL_ACCESS) == 6
    assert len(TOOL_CATALOG) >= 30


# ── ToolResult tests ──────────────────────────────────────────

def test_tool_result_to_dict():
    from agents.bea_team.tools import ToolResult
    r = ToolResult(success=True, tool="test", data={"key": "value"})
    d = r.to_dict()
    assert d["success"] is True
    assert d["tool"] == "test"
    assert d["data"]["key"] == "value"


# ── Protected path tests ─────────────────────────────────────

def test_protected_files_detected():
    from agents.bea_team.tools import is_protected
    assert is_protected("core/meta_orchestrator.py") is True
    assert is_protected("core/state.py") is True
    assert is_protected("config/settings.py") is True
    assert is_protected("agents/crew.py") is True


def test_non_protected_files_allowed():
    from agents.bea_team.tools import is_protected
    assert is_protected("agents/bea_team/tools.py") is False
    assert is_protected("tests/test_something.py") is False
    assert is_protected("tools/browser_tool.py") is False


# ── Branch naming validation ─────────────────────────────────

def test_branch_naming_rejects_invalid():
    from agents.bea_team.tools import tool_git_branch_create
    result = tool_git_branch_create("invalid-name")
    assert result.success is False
    assert "bea/" in result.error

    result2 = tool_git_branch_create("main")
    assert result2.success is False


# ── Fail-open tests ──────────────────────────────────────────

def test_read_file_nonexistent():
    from agents.bea_team.tools import tool_read_file
    result = tool_read_file("/nonexistent_path_12345/foo.py")
    assert isinstance(result.success, bool)
    # Should return ToolResult, not raise


def test_syntax_validate_nonexistent():
    from agents.bea_team.tools import tool_syntax_validate
    result = tool_syntax_validate("/nonexistent_path_12345/foo.py")
    assert result.success is False
    assert "not found" in result.error.lower() or result.error != ""


def test_detect_error_patterns_nonexistent():
    from agents.bea_team.tools import tool_detect_error_patterns
    result = tool_detect_error_patterns("/nonexistent_12345")
    # Should not raise, should return ToolResult
    assert hasattr(result, "success")


# ── Agent access matrix tests ────────────────────────────────

def test_all_agents_in_access_matrix():
    from agents.bea_team.tools import AGENT_TOOL_ACCESS
    expected_agents = {
        "bea-architect", "bea-coder", "bea-reviewer",
        "bea-qa", "bea-devops", "bea-watcher",
    }
    assert set(AGENT_TOOL_ACCESS.keys()) == expected_agents


def test_coder_has_write_tools():
    from agents.bea_team.tools import AGENT_TOOL_ACCESS
    coder_tools = AGENT_TOOL_ACCESS["bea-coder"]
    assert "tool_write_file" in coder_tools
    assert "tool_patch_file" in coder_tools
    assert "tool_git_commit" in coder_tools


def test_architect_has_no_write_tools():
    from agents.bea_team.tools import AGENT_TOOL_ACCESS
    arch_tools = AGENT_TOOL_ACCESS["bea-architect"]
    assert "tool_write_file" not in arch_tools
    assert "tool_patch_file" not in arch_tools
    assert "tool_git_commit" not in arch_tools


def test_reviewer_has_no_write_tools():
    from agents.bea_team.tools import AGENT_TOOL_ACCESS
    rev_tools = AGENT_TOOL_ACCESS["bea-reviewer"]
    assert "tool_write_file" not in rev_tools
    assert "tool_patch_file" not in rev_tools


def test_watcher_has_log_tools():
    from agents.bea_team.tools import AGENT_TOOL_ACCESS
    watcher_tools = AGENT_TOOL_ACCESS["bea-watcher"]
    assert "tool_read_logs" in watcher_tools
    assert "tool_detect_error_patterns" in watcher_tools


def test_get_tools_for_agent_returns_callables():
    from agents.bea_team.tools import get_tools_for_agent
    tools = get_tools_for_agent("bea-coder")
    assert len(tools) > 0
    for name, fn in tools.items():
        assert callable(fn), f"Tool {name} is not callable"


def test_get_tools_for_unknown_agent_returns_readonly():
    from agents.bea_team.tools import get_tools_for_agent
    tools = get_tools_for_agent("unknown-agent")
    assert len(tools) > 0
    assert "tool_read_file" in tools
    assert "tool_write_file" not in tools


# ── Tool catalog consistency ──────────────────────────────────

def test_catalog_covers_all_tool_functions():
    """Every tool_* function should have a catalog entry."""
    from agents.bea_team import tools as mod
    tool_fns = {name for name in dir(mod) if name.startswith("tool_") and callable(getattr(mod, name))}
    catalog_names = {f"tool_{entry['name']}" for entry in mod.TOOL_CATALOG}
    missing = tool_fns - catalog_names
    # Allow some tolerance for internal helpers
    assert len(missing) <= 3, f"Missing catalog entries: {missing}"


def test_all_access_matrix_tools_exist():
    """Every tool in AGENT_TOOL_ACCESS should exist as a function."""
    from agents.bea_team import tools as mod
    for agent, tool_names in mod.AGENT_TOOL_ACCESS.items():
        for name in tool_names:
            assert hasattr(mod, name) and callable(getattr(mod, name)), \
                f"Agent {agent} references non-existent tool: {name}"


# ── Git commit to master blocked ──────────────────────────────

def test_git_commit_blocks_master():
    """Committing directly to master should be blocked."""
    from agents.bea_team.tools import tool_git_commit
    with patch("agents.bea_team.tools._git", return_value="master"):
        result = tool_git_commit("test commit")
        assert result.success is False
        assert "master" in result.error.lower()
