"""tests/test_plugin_signatures.py — Plugin metadata signing tests."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("PLUGIN_SIGNING_SECRET", "test-secret")

from plugins.deploy.deploy_plugin import DeployPlugin
from plugins.github.github_plugin import GitHubPlugin
from plugins.plugin_models import PluginMetadata
from plugins.plugin_registry import PluginRegistry
from plugins.signatures import sign_plugin_metadata, verify_plugin_metadata


def test_plugin_metadata_signature_verifies_for_built_in_plugins() -> None:
    for plugin in (DeployPlugin, GitHubPlugin):
        assert plugin.metadata.signature.startswith("hmac-sha256:"), plugin.metadata.plugin_id
        assert verify_plugin_metadata(plugin.metadata), plugin.metadata.plugin_id


def test_registry_accepts_signed_plugins() -> None:
    registry = PluginRegistry()
    result = registry.register(DeployPlugin())
    assert result is True
    assert registry.get_metadata("deploy") is not None


def test_registry_rejects_tampered_signature() -> None:
    bad = PluginMetadata(
        plugin_id="bad",
        name="Bad Plugin",
        description="tampered metadata",
        version="1.0.0",
        risk_level="low",
        signature="hmac-sha256:0000000000000000000000000000000000000000000000000000000000000000",
    )

    class FakePlugin:
        metadata = bad
        async def invoke(self, action, params, context): ...

    registry = PluginRegistry()
    assert registry.register(FakePlugin()) is False


def test_sign_plugin_metadata_requires_secret() -> None:
    meta = PluginMetadata(plugin_id="x", name="X", description="x", risk_level="low")
    assert sign_plugin_metadata(meta, secret="test-secret").startswith("hmac-sha256:")
    with pytest.raises(RuntimeError):
        sign_plugin_metadata(meta, secret="")
