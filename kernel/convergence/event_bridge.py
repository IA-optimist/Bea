"""
kernel/convergence/event_bridge.py — Kernel event recording bridge.

Records kernel canonical events in kernel memory alongside existing
cognitive journal emissions. This is the transitional layer.

Key design: this bridge does NOT re-emit events into the cognitive journal.
The original emitter (ToolExecutor, PlanRunner, MetaOrchestrator, etc.)
already writes to the cognitive journal. The kernel bridge records the
same event in kernel memory using kernel-typed contracts, providing:
  - Typed event storage
  - Execution trace queries
  - Future kernel-native routing inputs

Usage:
  from kernel.convergence.event_bridge import emit_kernel_event
  emit_kernel_event("mission.created", mission_id="m-123", goal="build chatbot")

All calls are fail-open. Kernel event emission NEVER blocks runtime.
"""
from __future__ import annotations

from typing import Any

import structlog

log = structlog.get_logger("kernel.convergence.events")


def emit_kernel_event(event_type: str, **kwargs: Any) -> bool:
    """
    Record a kernel canonical event in kernel memory.

    This does NOT write to the cognitive journal (the original emitter
    already does that). It records a kernel-typed event for:
      - Execution trace queries (recent tools, step timeline, etc.)
      - Kernel memory (episodic)
      - Future kernel-native routing and scoring

    Args:
        event_type: Kernel canonical event type (e.g. "mission.created")
        **kwargs: Event-specific data (mission_id, tool_id, error, etc.)

    Returns:
        True if event was recorded successfully
    """
    try:
        # 1. Record in kernel memory (primary)
        from kernel.memory.interfaces import get_memory
        # Sanitize: only store safe string representations, limit sizes
        safe_payload = {k: str(v)[:200] for k, v in kwargs.items()
                        if k not in ("secret", "password", "token", "api_key")}
        get_memory().write_episodic(
            content={"event_type": event_type, **safe_payload},
            source=kwargs.get("source", "kernel"),
            mission_id=kwargs.get("mission_id", ""),
            step_id=kwargs.get("step_id", ""),
        )

        # 2. Update performance intelligence (fail-open)
        try:
            _update_performance(event_type, kwargs)
        except Exception as _exc:
            log.warning("structured_exception", action="event_bridge_1", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

        return True
    except Exception as e:
        log.debug("kernel_event_bridge_failed", event_type=event_type, err=str(e)[:60])
        return False


def _update_performance(event_type: str, kwargs: dict[str, Any]) -> None:
    """
    Update performance store from execution events.

    Only fires for outcome events (completed/failed), not start events.
    Uses identity map to resolve capability_id/provider_id when not provided.
    """
    from kernel.capabilities.performance import get_performance_store
    store = get_performance_store()

    tool_id = kwargs.get("tool_id", "")
    capability_id = kwargs.get("capability_id", "")
    provider_id = kwargs.get("provider_id", "")
    duration_ms = 0.0
    try:
        duration_ms = float(kwargs.get("duration_ms", 0))
    except (ValueError, TypeError) as _exc:
        log.warning("structured_exception", action="event_bridge_2", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    # Resolve missing identity via lookup (fail-open)
    if tool_id and (not capability_id or not provider_id):
        try:
            from kernel.capabilities.identity import get_identity_map
            resolution = get_identity_map().resolve_tool(tool_id)
            if not capability_id and resolution["capability_ids"]:
                capability_id = resolution["capability_ids"][0]
            if not provider_id and resolution["provider_id"]:
                provider_id = resolution["provider_id"]
        except Exception as _exc:
            log.warning("structured_exception", action="event_bridge_3", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    if event_type == "tool.completed":
        store.record_tool_outcome(
            tool_id=tool_id or "unknown",
            success=True,
            duration_ms=duration_ms,
            capability_id=capability_id,
            provider_id=provider_id,
        )
    elif event_type == "tool.failed":
        store.record_tool_outcome(
            tool_id=tool_id or "unknown",
            success=False,
            duration_ms=duration_ms,
            capability_id=capability_id,
            provider_id=provider_id,
        )
    elif event_type == "step.completed":
        store.record_step_outcome(
            step_id=kwargs.get("step_id", ""),
            success=True,
            step_type=kwargs.get("step_type", ""),
            capability_id=capability_id,
            provider_id=provider_id,
        )
        # Also record as tool-level for skill/tool steps (enables routing feedback)
        if tool_id:
            store.record_tool_outcome(
                tool_id=tool_id,
                success=True,
                duration_ms=duration_ms,
                capability_id=capability_id,
                provider_id=provider_id,
            )
    elif event_type == "step.failed":
        store.record_step_outcome(
            step_id=kwargs.get("step_id", ""),
            success=False,
            step_type=kwargs.get("step_type", ""),
            capability_id=capability_id,
            provider_id=provider_id,
        )
        if tool_id:
            store.record_tool_outcome(
                tool_id=tool_id,
                success=False,
                duration_ms=duration_ms,
                capability_id=capability_id,
                provider_id=provider_id,
            )
