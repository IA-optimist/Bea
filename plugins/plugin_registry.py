"""
plugins/plugin_registry.py — In-memory plugin registry.

Plugins are registered explicitly by calling register().
No auto-discovery, no dynamic imports from arbitrary paths.

A plugin must expose:
- metadata: PluginMetadata  (class attribute)
- async invoke(action: str, params: dict, context: dict) -> dict
- async health_check() -> str  ("ok" / "degraded" / "unavailable")
"""
from __future__ import annotations
import threading
from typing import Optional, Any
import structlog

from plugins.plugin_models import PluginMetadata, PluginStatus
from plugins.signatures import verify_plugin_metadata

log = structlog.get_logger("plugins.registry")


class PluginRegistry:
    """
    Central registry for all Bea plugins.

    Thread-safe. Re-populated on each startup via explicit register() calls.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._plugins: dict[str, Any] = {}           # plugin_id → plugin instance
        self._meta: dict[str, PluginMetadata] = {}   # plugin_id → metadata
        self._status: dict[str, PluginStatus] = {}   # plugin_id → status
        self._disabled: set = set()

    def register(self, plugin) -> bool:
        """
        Register a plugin instance. The plugin must have a .metadata attribute.
        Returns False if registration fails (bad contract).
        """
        try:
            meta: PluginMetadata = plugin.metadata
            if not isinstance(meta, PluginMetadata):
                raise TypeError("plugin.metadata must be PluginMetadata instance")
            if not callable(getattr(plugin, "invoke", None)):
                raise TypeError("plugin must implement invoke(action, params, context)")

            # Verify plugin signature when one is present
            if meta.signature and not verify_plugin_metadata(meta):
                raise ValueError("plugin metadata signature verification failed")
        except Exception as e:
            log.warning("plugin_registration_failed", error=str(e))
            return False

        with self._lock:
            self._plugins[meta.plugin_id] = plugin
            self._meta[meta.plugin_id] = meta
            self._status[meta.plugin_id] = PluginStatus(
                plugin_id=meta.plugin_id, health_status="unknown"
            )
        log.info("plugin_registered",
                 plugin_id=meta.plugin_id,
                 name=meta.name,
                 version=meta.version,
                 risk_level=meta.risk_level)
        return True

    def unregister(self, plugin_id: str) -> bool:
        with self._lock:
            if plugin_id in self._plugins:
                del self._plugins[plugin_id]
                del self._meta[plugin_id]
                del self._status[plugin_id]
                self._disabled.discard(plugin_id)
                log.info("plugin_unregistered", plugin_id=plugin_id)
                return True
        return False

    def disable(self, plugin_id: str) -> None:
        with self._lock:
            self._disabled.add(plugin_id)
            if plugin_id in self._status:
                self._status[plugin_id].health_status = "disabled"
        log.info("plugin_disabled", plugin_id=plugin_id)

    def enable(self, plugin_id: str) -> None:
        with self._lock:
            self._disabled.discard(plugin_id)
            if plugin_id in self._status:
                self._status[plugin_id].health_status = "unknown"
        log.info("plugin_enabled", plugin_id=plugin_id)

    def is_available(self, plugin_id: str) -> bool:
        return (plugin_id in self._plugins
                and plugin_id not in self._disabled
                and self._status.get(plugin_id, PluginStatus(plugin_id=plugin_id)).health_status != "unavailable")

    def get(self, plugin_id: str):
        return self._plugins.get(plugin_id)

    def get_metadata(self, plugin_id: str) -> Optional[PluginMetadata]:
        return self._meta.get(plugin_id)

    def get_status(self, plugin_id: str) -> Optional[PluginStatus]:
        return self._status.get(plugin_id)

    def update_status(self, plugin_id: str, health: str, error: str = None):
        import time
        with self._lock:
            if plugin_id in self._status:
                self._status[plugin_id].health_status = health
                self._status[plugin_id].last_checked = time.time()
                self._status[plugin_id].error = error

    def list_available(self) -> list[PluginMetadata]:
        return [
            meta for pid, meta in self._meta.items()
            if pid not in self._disabled
        ]

    def list_all(self) -> list[dict]:
        result = []
        for pid, meta in self._meta.items():
            status = self._status.get(pid, PluginStatus(plugin_id=pid))
            result.append({
                "metadata": meta.to_dict(),
                "status": status.to_dict(),
                "disabled": pid in self._disabled,
            })
        return result

    def stats(self) -> dict:
        return {
            "total": len(self._plugins),
            "available": len(self.list_available()),
            "disabled": len(self._disabled),
        }


# ── Singleton ─────────────────────────────────────────────────

_registry: Optional[PluginRegistry] = None
_registry_lock = threading.Lock()


def get_plugin_registry() -> PluginRegistry:
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = PluginRegistry()
    return _registry
