"""Regression tests for extractions out of agents.crew."""

from pathlib import Path
import sys
import types

if "structlog" not in sys.modules:
    _structlog = types.ModuleType("structlog")
    _logger = types.SimpleNamespace(
        debug=lambda *args, **kwargs: None,
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
    )
    _structlog.get_logger = lambda *args, **kwargs: _logger
    sys.modules["structlog"] = _structlog

if "langchain_core.messages" not in sys.modules:
    _langchain_core = types.ModuleType("langchain_core")
    _messages = types.ModuleType("langchain_core.messages")

    class _Message:
        def __init__(self, content="", **kwargs):
            self.content = content
            self.kwargs = kwargs

    _messages.SystemMessage = _Message
    _messages.HumanMessage = _Message
    sys.modules.setdefault("langchain_core", _langchain_core)
    sys.modules["langchain_core.messages"] = _messages

def test_agent_selector_has_dedicated_module_with_crew_compatibility():
    from agents import selector
    from agents.crew import AgentSelector, MISSION_ROUTING, get_agent_selector, select_agents

    assert selector.AgentSelector is AgentSelector
    assert selector.get_agent_selector is get_agent_selector
    assert selector.select_agents is select_agents
    assert selector.MISSION_ROUTING is MISSION_ROUTING
    assert "class AgentSelector" not in Path("agents/crew.py").read_text(encoding="utf-8")


def test_agent_selector_keeps_existing_routing_behaviour(monkeypatch):
    from agents.selector import AgentSelector

    monkeypatch.setattr("core.mission_system.is_capability_query", lambda goal: False)

    selected = AgentSelector().select_agents(
        "implement api tests",
        risk_level="LOW",
        domain="software_dev",
        complexity="high",
    )

    assert "forge-builder" in selected
    assert len(selected) <= 5

def test_agent_crew_runtime_has_dedicated_module_with_crew_compatibility():
    from agents import crew_runtime
    from agents.crew import AgentCrew

    assert crew_runtime.AgentCrew is AgentCrew
    assert "class AgentCrew" not in Path("agents/crew.py").read_text(encoding="utf-8")
