"""Neutral LLM provider interface (T5.1 + T5.2).

This module defines the canonical abstraction used by the rest of Béa to get an
LLM client. It deliberately does not import any provider SDK at top level.
`core.llm_factory.LLMFactory` is the current concrete implementation; this file
provides the public boundary callers should depend on.

T5.2 — Codex removed from critical path via FallbackChainProvider:
  The runtime can fall back to any chain of BaseLLMProvider instances when the
  preferred provider is unavailable. Codex stays as Béa's product brain but the
  orchestrator / agent layer degrades cleanly instead of crashing.
"""
from __future__ import annotations

import structlog
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

log = structlog.get_logger(__name__)


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


# ── Fallback chain (T5.2) ─────────────────────────────────────────────────────

class FallbackChainProvider(BaseLLMProvider):
    """Try providers in declaration order; return the first successful response.

    Usage::

        chain = FallbackChainProvider([primary, secondary, tertiary])
        response = chain.invoke(messages)

    Rules:
    - Skips providers where ``available()`` returns False (no wasted network call).
    - Catches ``LLMProviderError`` from each provider and continues to the next.
    - Raises ``LLMProviderError`` only when all providers have been exhausted.
    - Any unexpected exception (non-LLMProviderError) propagates immediately
      (signals a programming error, not a transient network failure).
    """

    def __init__(self, providers: list[BaseLLMProvider]) -> None:
        if not providers:
            raise ValueError("FallbackChainProvider requires at least one provider")
        self._providers = list(providers)

    def available(self) -> bool:
        return any(p.available() for p in self._providers)

    def invoke(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        last_exc: Exception | None = None
        for provider in self._providers:
            if not provider.available():
                log.debug("provider_skipped_unavailable", provider=type(provider).__name__)
                continue
            try:
                return provider.invoke(messages, **kwargs)
            except LLMProviderError as exc:
                last_exc = exc
                log.warning(
                    "provider_fallback",
                    provider=type(provider).__name__,
                    err=str(exc)[:120],
                )
        raise LLMProviderError(
            f"All {len(self._providers)} providers in fallback chain failed"
        ) from last_exc

    def __repr__(self) -> str:
        names = " → ".join(type(p).__name__ for p in self._providers)
        return f"FallbackChainProvider([{names}])"


# ── Registry ──────────────────────────────────────────────────────────────────

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
