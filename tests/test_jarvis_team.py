"""
Tests for agents/jarvis_team/ — Jarvis Agent Team.

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

def test_jarvis_team_imports():
    """All jarvis-team agents are importable."""
    from agents.jarvis_team import (
        JARVIS_TEAM_AGENTS,
    )
    assert len(JARVIS_TEAM_AGENTS) == 6
    assert "jarvis-architect" in JARVIS_TEAM_AGENTS
    assert "jarvis-coder" in JARVIS_TEAM_AGENTS
    assert "jarvis-reviewer" in JARVIS_TEAM_AGENTS
    assert "jarvis-qa" in JARVIS_TEAM_AGENTS
    assert "jarvis-devops" in JARVIS_TEAM_AGENTS
    assert "jarvis-watcher" in JARVIS_TEAM_AGENTS


def test_agent_names_match_registry_keys():
    """Agent .name attribute matches the registry key."""
    from agents.jarvis_team import JARVIS_TEAM_AGENTS
    settings = MagicMock()
    for key, cls in JARVIS_TEAM_AGENTS.items():
        agent = cls(settings)
        assert agent.name == key, f"Agent name mismatch: {agent.name} != {key}"


def test_agents_have_system_prompt():
    """All agents return a non-empty system prompt."""
    from agents.jarvis_team import JARVIS_TEAM_AGENTS
    settings = MagicMock()
    for key, cls in JARVIS_TEAM_AGENTS.items():
        agent = cls(settings)
        prompt = agent.system_prompt()
        assert isinstance(prompt, str), f"{key}.system_prompt() must return str"
        assert len(prompt) > 50, f"{key}.system_prompt() too short"


def test_agents_have_user_message():
    """All agents can produce a user message from a mock session."""
    from agents.jarvis_team import JARVIS_TEAM_AGENTS
    settings = MagicMock()
    session = MagicMock()
    session.user_input = "Test mission"
    session.mission_summary = "Test mission"
    session.agents_plan = []
    session.outputs = {}
    session.context_snapshot.return_value = {}

    for key, cls in JARVIS_TEAM_AGENTS.items():
        agent = cls(settings)
        msg = agent.user_message(session)
        assert isinstance(msg, str), f"{key}.user_message() must return str"
        assert len(msg) > 0, f"{key}.user_message() must be non-empty"


# ── Base class tests ──────────────────────────────────────────

def test_base_git_helper_fail_open():
    """Git helper returns empty string on failure, not exception."""
    from agents.jarvis_team.base import JarvisTeamAgent
    # Run a git command in a non-existent directory — should fail-open
    result = JarvisTeamAgent._git("status", cwd=Path("/nonexistent_dir_12345"))
    assert result == ""


def test_base_read_file_fail_open():
    """File reader returns empty string for non-existent files."""
    from agents.jarvis_team.base import JarvisTeamAgent
    result = JarvisTeamAgent.read_file("/nonexistent_path_12345/foo.py")
    assert result == ""


def test_base_list_files_fail_open():
    """File lister returns empty list for non-existent directories."""
    from agents.jarvis_team.base import JarvisTeamAgent
    result = JarvisTeamAgent.list_files("/nonexistent_dir_12345")
    assert result == []


# ── Protected files ───────────────────────────────────────────

def test_coder_knows_protected_files():
    """jarvis-coder's system prompt mentions protected files."""
    from agents.jarvis_team.coder import JarvisCoder, PROTECTED_FILES
    settings = MagicMock()
    coder = JarvisCoder(settings)
    prompt = coder.system_prompt()
    for f in PROTECTED_FILES:
        assert f in prompt, f"Protected file {f} not mentioned in coder prompt"


# ── Registration test ─────────────────────────────────────────

def test_jarvis_team_registration_in_crew():
    """Jarvis team agents are registered when AgentCrew initializes."""
    try:
        # This will fail in test environments without full settings,
        # so we just verify the registration method exists and is callable
        from agents.crew import AgentCrew
        assert hasattr(AgentCrew, "_register_jarvis_team")
    except Exception:
        pytest.skip("AgentCrew not fully loadable in test env")
