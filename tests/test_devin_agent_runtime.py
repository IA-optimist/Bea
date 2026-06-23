from __future__ import annotations

import pytest

from agents.autonomous.devin_agent import DevinAgent


def test_devin_agent_instantiates_without_llm():
    """Regression: DevinAgent must be instantiable when LLMFactory is absent."""
    agent = DevinAgent(model_hint="no-model")
    assert agent._llm is None
    assert agent.memory_bank is not None
    # query() must be safe even when the memory backend is unavailable.
    assert isinstance(agent.memory_bank.query("test"), str)
