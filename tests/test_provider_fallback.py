"""
Tests for T5.2 — FallbackChainProvider.

Verifies that the provider abstraction degrades cleanly when the primary
provider is unavailable or fails, without crashing the runtime.
"""
from __future__ import annotations

import pytest
from typing import Any

from core.providers.llm_provider import (
    BaseLLMProvider,
    FallbackChainProvider,
    LLMProviderError,
)


# ── Stubs ─────────────────────────────────────────────────────────────────────

class AlwaysAvailable(BaseLLMProvider):
    def __init__(self, response: str = "ok") -> None:
        self.response = response
        self.calls: list[list[dict[str, str]]] = []

    def available(self) -> bool:
        return True

    def invoke(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        self.calls.append(messages)
        return self.response


class AlwaysUnavailable(BaseLLMProvider):
    def available(self) -> bool:
        return False

    def invoke(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        raise AssertionError("invoke must not be called on an unavailable provider")


class AlwaysFails(BaseLLMProvider):
    def available(self) -> bool:
        return True

    def invoke(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        raise LLMProviderError("simulated provider failure")


class RaisesUnexpected(BaseLLMProvider):
    def available(self) -> bool:
        return True

    def invoke(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        raise RuntimeError("unexpected: this should propagate")


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestFallbackChainProvider:

    def test_requires_at_least_one_provider(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            FallbackChainProvider([])

    def test_single_provider_success(self) -> None:
        p = AlwaysAvailable("hello")
        chain = FallbackChainProvider([p])
        assert chain.invoke([]) == "hello"

    def test_skips_unavailable_falls_to_second(self) -> None:
        unavail = AlwaysUnavailable()
        avail = AlwaysAvailable("fallback_response")
        chain = FallbackChainProvider([unavail, avail])
        result = chain.invoke([{"role": "user", "content": "hi"}])
        assert result == "fallback_response"
        # unavailable provider must not be invoked
        assert avail.calls

    def test_skips_failing_provider_falls_to_second(self) -> None:
        fail = AlwaysFails()
        ok = AlwaysAvailable("recovered")
        chain = FallbackChainProvider([fail, ok])
        assert chain.invoke([]) == "recovered"

    def test_raises_when_all_fail(self) -> None:
        chain = FallbackChainProvider([AlwaysFails(), AlwaysFails()])
        with pytest.raises(LLMProviderError, match="All 2 providers"):
            chain.invoke([])

    def test_raises_when_all_unavailable(self) -> None:
        chain = FallbackChainProvider([AlwaysUnavailable(), AlwaysUnavailable()])
        with pytest.raises(LLMProviderError):
            chain.invoke([])

    def test_unexpected_exception_propagates(self) -> None:
        chain = FallbackChainProvider([RaisesUnexpected()])
        with pytest.raises(RuntimeError, match="unexpected"):
            chain.invoke([])

    def test_available_true_if_any_provider_available(self) -> None:
        chain = FallbackChainProvider([AlwaysUnavailable(), AlwaysAvailable()])
        assert chain.available() is True

    def test_available_false_if_all_unavailable(self) -> None:
        chain = FallbackChainProvider([AlwaysUnavailable(), AlwaysUnavailable()])
        assert chain.available() is False

    def test_first_successful_is_returned(self) -> None:
        p1 = AlwaysAvailable("first")
        p2 = AlwaysAvailable("second")
        chain = FallbackChainProvider([p1, p2])
        result = chain.invoke([])
        assert result == "first"
        assert len(p1.calls) == 1
        assert len(p2.calls) == 0

    def test_kwargs_forwarded_to_provider(self) -> None:
        received_kwargs: dict = {}

        class CaptureKwargs(BaseLLMProvider):
            def available(self) -> bool:
                return True
            def invoke(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
                received_kwargs.update(kwargs)
                return "ok"

        chain = FallbackChainProvider([CaptureKwargs()])
        chain.invoke([], temperature=0.5, max_tokens=100)
        assert received_kwargs["temperature"] == 0.5
        assert received_kwargs["max_tokens"] == 100

    def test_repr_shows_chain(self) -> None:
        chain = FallbackChainProvider([AlwaysAvailable(), AlwaysFails()])
        r = repr(chain)
        assert "FallbackChainProvider" in r
        assert "AlwaysAvailable" in r
        assert "AlwaysFails" in r
        assert "→" in r
