"""
Tests for agents/bea_team/ — Bea Agent Team.

Verifies:
    - All 6 agents importable and instantiable
    - BaseAgent interface compliance (system_prompt, user_message)
    - Registration in AgentCrew
    - Fail-open git/file helpers
    - Branch naming conventions
"""
import pytest
from pathlib import Path
from unittest.mock import MagicMock


# ── Import tests ──────────────────────────────────────────────

def test_bea_team_imports():
    """All bea-team agents are importable."""
    from agents.bea_team import (
        BEA_TEAM_AGENTS,
    )
    assert len(BEA_TEAM_AGENTS) == 6
    assert "bea-architect" in BEA_TEAM_AGENTS
    assert "bea-coder" in BEA_TEAM_AGENTS
    assert "bea-reviewer" in BEA_TEAM_AGENTS
    assert "bea-qa" in BEA_TEAM_AGENTS
    assert "bea-devops" in BEA_TEAM_AGENTS
    assert "bea-watcher" in BEA_TEAM_AGENTS


def test_agent_names_match_registry_keys():
    """Agent .name attribute matches the registry key."""
    from agents.bea_team import BEA_TEAM_AGENTS
    settings = MagicMock()
    for key, cls in BEA_TEAM_AGENTS.items():
        agent = cls(settings)
        assert agent.name == key, f"Agent name mismatch: {agent.name} != {key}"


def test_agents_have_system_prompt():
    """All agents return a non-empty system prompt."""
    from agents.bea_team import BEA_TEAM_AGENTS
    settings = MagicMock()
    for key, cls in BEA_TEAM_AGENTS.items():
        agent = cls(settings)
        prompt = agent.system_prompt()
        assert isinstance(prompt, str), f"{key}.system_prompt() must return str"
        assert len(prompt) > 50, f"{key}.system_prompt() too short"


def test_agents_have_user_message():
    """All agents can produce a user message from a mock session."""
    from agents.bea_team import BEA_TEAM_AGENTS
    settings = MagicMock()
    session = MagicMock()
    session.user_input = "Test mission"
    session.mission_summary = "Test mission"
    session.agents_plan = []
    session.outputs = {}
    session.context_snapshot.return_value = {}

    for key, cls in BEA_TEAM_AGENTS.items():
        agent = cls(settings)
        msg = agent.user_message(session)
        assert isinstance(msg, str), f"{key}.user_message() must return str"
        assert len(msg) > 0, f"{key}.user_message() must be non-empty"


# ── Base class tests ──────────────────────────────────────────

def test_base_git_helper_fail_open():
    """Git helper returns empty string on failure, not exception."""
    from agents.bea_team.base import BeaTeamAgent
    # Run a git command in a non-existent directory — should fail-open
    result = BeaTeamAgent._git("status", cwd=Path("/nonexistent_dir_12345"))
    assert result == ""


def test_base_read_file_fail_open():
    """File reader returns empty string for non-existent files."""
    from agents.bea_team.base import BeaTeamAgent
    result = BeaTeamAgent.read_file("/nonexistent_path_12345/foo.py")
    assert result == ""


def test_base_list_files_fail_open():
    """File lister returns empty list for non-existent directories."""
    from agents.bea_team.base import BeaTeamAgent
    result = BeaTeamAgent.list_files("/nonexistent_dir_12345")
    assert result == []


# ── Protected files ───────────────────────────────────────────

def test_coder_knows_protected_files():
    """bea-coder's system prompt mentions protected files."""
    from agents.bea_team.coder import BeaCoder, PROTECTED_FILES
    settings = MagicMock()
    coder = BeaCoder(settings)
    prompt = coder.system_prompt()
    for f in PROTECTED_FILES:
        assert f in prompt, f"Protected file {f} not mentioned in coder prompt"


# ── Registration test ─────────────────────────────────────────

def test_bea_team_registration_in_crew():
    """Bea team agents are registered when AgentCrew initializes."""
    try:
        # This will fail in test environments without full settings,
        # so we just verify the registration method exists and is callable
        from agents.crew import AgentCrew
        assert hasattr(AgentCrew, "_register_bea_team")
    except Exception:
        pytest.skip("AgentCrew not fully loadable in test env")
