"""
plugins — BeaMax plugin system.

Plugins extend Bea with new capabilities (tools, data sources,
integrations, notifications) through a controlled registry.

Rules:
- NO auto-discovery. All plugins are registered explicitly.
- Plugin execution flows through executor.capability_dispatch
- Plugins declare risk level and can require approval
- Failing plugins return structured errors, never raise
"""
from plugins.plugin_registry import PluginRegistry, get_plugin_registry
from plugins.plugin_models import PluginMetadata, PluginStatus

__all__ = ["PluginRegistry", "get_plugin_registry", "PluginMetadata", "PluginStatus"]
