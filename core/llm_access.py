"""
Core LLM access helpers.

These helpers keep provider selection behind the policy-aware LLMFactory
instead of instantiating provider clients directly in call sites.
"""
from __future__ import annotations

from typing import Any


def get_policy_llm(role: str = "default", settings: Any | None = None):
    """Return the policy-selected LLM for a role."""
    if settings is None:
        from config.settings import get_settings
        settings = get_settings()

    from core.llm_factory import LLMFactory
    return LLMFactory(settings).get(role)

