"""Plugin metadata signing utilities.

Plugins can sign their metadata with HMAC-SHA256 over a canonical JSON payload.
A registry can then verify the signature before loading the plugin. The secret
can be rotated via the ``PLUGIN_SIGNING_SECRET`` environment variable.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os

from plugins.plugin_models import PluginMetadata


def _canonical_string(metadata: PluginMetadata) -> str:
    """Canonical JSON of the metadata with signature excluded."""
    payload = metadata.canonical_payload()
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sign_plugin_metadata(metadata: PluginMetadata, secret: str | None = None) -> str:
    """Return an HMAC-SHA256 signature for the metadata.

    If ``secret`` is not provided, ``PLUGIN_SIGNING_SECRET`` is used. If no
    secret is available, this function raises ``RuntimeError``.
    """
    key = secret if secret is not None else os.environ.get("PLUGIN_SIGNING_SECRET", "")
    if not key:
        raise RuntimeError("PLUGIN_SIGNING_SECRET is required to sign plugin metadata")
    payload = _canonical_string(metadata)
    sig = hmac.new(key.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"hmac-sha256:{sig}"


def verify_plugin_metadata(
    metadata: PluginMetadata,
    secret: str | None = None,
) -> bool:
    """Verify the signature on ``metadata``.

    Returns ``False`` if there is no signature, no secret, or if verification
    fails.
    """
    if not metadata.signature or not metadata.signature.startswith("hmac-sha256:"):
        return False
    key = secret or os.environ.get("PLUGIN_SIGNING_SECRET", "")
    if not key:
        return False
    expected = sign_plugin_metadata(metadata, secret=key)
    return hmac.compare_digest(metadata.signature, expected)
