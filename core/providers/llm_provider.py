"""Neutral LLM provider interface.

This module defines the canonical abstraction used by the rest of Béa to get an
LLM client. It deliberately does not import any provider SDK at top level.
`core.llm_factory.LLMFactory` is the current concrete implementation; this file
provides the public boundary callers should depend on.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    model: str
    api_key: str | None = None
    base_url: str | None = None
    timeout: float = 120.0
    max_retries: int = 2


class BaseLLMProvider(ABC):
    """Abstract LLM provider. Every concrete provider must implement invoke."""

    @abstractmethod
    def invoke(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        """Send messages and return completion text."""
        raise NotImplementedError

    @abstractmethod
    def available(self) -> bool:
        """Return True if this provider can be used right now."""
        raise NotImplementedError


class LLMProviderError(Exception):
    """Raised when no provider is available or a provider call fails."""


_PROVIDER_BACKBONE: dict[str, Any] = {}


def register_provider(name: str, factory: Any) -> None:
    """Register a concrete provider factory under ``name``."""
    _PROVIDER_BACKBONE[name] = factory


def get_llm_provider(role: str = "default", preferred: str | None = None, config: Any | None = None):
    """Return the LLM provider selected for ``role``.

    Delegates to ``core.llm_factory.LLMFactory`` to keep the existing routing
    logic intact while exposing a single entry point.
    """
    from core.llm_factory import LLMFactory

    settings = config
    if settings is None:
        from config.settings import get_settings

        settings = get_settings()

    factory = LLMFactory(settings)
    provider_name = preferred or _provider_override_for_role(role)
    if provider_name and provider_name in _PROVIDER_BACKBONE:
        return _PROVIDER_BACKBONE[provider_name](settings)
    return factory.get(role)


def _provider_override_for_role(role: str) -> str | None:
    """Allow future per-role default provider overrides."""
    return None


def list_providers() -> list[str]:
    """Return the names of currently registered providers."""
    return sorted(_PROVIDER_BACKBONE.keys())
