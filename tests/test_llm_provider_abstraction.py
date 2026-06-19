from __future__ import annotations

import pytest

from core.providers import (
    BaseLLMProvider,
    LLMProviderError,
    ProviderConfig,
    get_llm_provider,
    list_providers,
    register_provider,
)
from core.llm_factory import ROLE_PROVIDERS


def test_provider_interface_has_roles_from_factory() -> None:
    assert isinstance(ROLE_PROVIDERS, dict)
    assert "builder" in ROLE_PROVIDERS


def test_register_and_list_providers() -> None:
    class StubProvider(BaseLLMProvider):
        def invoke(self, messages, **kwargs):
            return "stub"

        def available(self):
            return True

    register_provider("stub", StubProvider)
    assert "stub" in list_providers()


def test_get_llm_provider_is_callable() -> None:
    import inspect

    sig = inspect.signature(get_llm_provider)
    params = list(sig.parameters)
    assert "role" in params
    assert "preferred" in params


def test_provider_config_is_frozen() -> None:
    config = ProviderConfig(name="stub", model="test")
    with pytest.raises(AttributeError):
        config.name = "other"
