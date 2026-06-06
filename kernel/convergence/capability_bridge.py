"""
kernel/convergence/capability_bridge.py — Makes kernel the authoritative capability source.

MetaOrchestrator can query kernel capabilities alongside (or instead of)
the existing ProviderRegistry.

This bridge:
  1. Syncs kernel registry from runtime on first call
  2. Provides query() that returns kernel Capability objects
  3. Provides resolve_provider() that uses kernel registry + existing scorer
"""
from __future__ import annotations

import threading
import structlog

log = structlog.get_logger("kernel.convergence.capability")

_synced = False
_sync_lock = threading.Lock()


def ensure_synced() -> None:
    """Ensure kernel capability registry is populated from runtime. Idempotent."""
    global _synced
    if _synced:
        return
    with _sync_lock:
        if _synced:
            return
        try:
            from kernel.adapters.capability_adapter import sync_kernel_from_runtime
            sync_kernel_from_runtime()
            _synced = True
        except Exception as e:
            log.debug("capability_sync_failed", err=str(e)[:60])


def query_capabilities(category: str = "") -> list[dict]:
    """
    Query kernel capability registry. Authoritative source after sync.

    Args:
        category: Optional filter (planning, execution, memory, policy)

    Returns:
        List of capability dicts
    """
    ensure_synced()
    try:
        from kernel.capabilities.registry import get_capability_registry
        registry = get_capability_registry()
        if category:
            caps = registry.list_by_category(category)
        else:
            caps = registry.list_all()
        return [c.to_dict() for c in caps]
    except Exception as e:
        log.debug("capability_query_failed", err=str(e)[:60])
        return []


def resolve_provider(capability_id: str) -> dict | None:
    """
    Resolve the best provider for a capability using kernel registry + existing scorer.

    Tries kernel-first, falls back to core capability routing.

    Returns:
        {"capability_id": str, "provider_id": str, "providers": list, "source": str}
        or None if unresolvable
    """
    ensure_synced()

    # Try kernel registry first
    try:
        from kernel.capabilities.registry import get_capability_registry
        registry = get_capability_registry()
        cap = registry.get(capability_id)
        if cap and cap.providers:
            return {
                "capability_id": capability_id,
                "provider_id": cap.providers[0],
                "providers": cap.providers,
                "source": "kernel",
                "requires_approval": cap.requires_approval,
            }
    except Exception as _exc:
        log.warning("swallowed_exception", action="capability_bridge_1", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    # Fallback to core capability routing
    try:
        from core.capability_routing.router import route_single_capability
        result = route_single_capability(capability_id)
        if result and result.get("provider"):
            return {
                "capability_id": capability_id,
                "provider_id": result["provider"].get("id", ""),
                "providers": [result["provider"].get("id", "")],
                "source": "core_routing",
                "score": result.get("score", 0),
            }
    except Exception as _exc:
        log.warning("swallowed_exception", action="capability_bridge_2", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    return None


def get_registry_stats() -> dict:
    """Get combined stats from kernel + core registries."""
    ensure_synced()
    stats = {"kernel": {}, "core": {}}

    try:
        from kernel.capabilities.registry import get_capability_registry
        stats["kernel"] = get_capability_registry().stats()
    except Exception as _exc:
        log.warning("swallowed_exception", action="capability_bridge_3", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    try:
        from core.capability_routing.registry import ProviderRegistry
        pr = ProviderRegistry()
        counts = pr.populate()
        stats["core"] = counts
    except Exception as _exc:
        log.warning("swallowed_exception", action="capability_bridge_4", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    return stats
