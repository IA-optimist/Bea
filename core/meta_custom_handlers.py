"""Custom mission handler mixin for MetaOrchestrator."""
from __future__ import annotations

from typing import Callable

import structlog

log = structlog.get_logger(__name__)


class CustomMissionHandlerMixin:
    """Registration and dispatch helpers for custom mission handlers."""

    _custom_handlers: dict[str, Callable]

    def register_mission_handler(self, mission_type: str, handler: Callable) -> None:
        """Register a custom mission handler for a specific mission type."""
        self._custom_handlers[mission_type] = handler
        log.info("mission_handler_registered", mission_type=mission_type)

    async def dispatch_custom_mission(
        self,
        mission_type: str,
        mission: dict,
        context: dict | None = None,
    ) -> dict:
        """Dispatch a mission to a custom handler if registered."""
        if mission_type not in self._custom_handlers:
            raise KeyError(f"No handler registered for mission type: {mission_type}")

        handler = self._custom_handlers[mission_type]
        log.info("mission_dispatch", mission_type=mission_type)

        try:
            return await handler(mission, context or {})
        except Exception as exc:
            log.error("mission_handler_failed", mission_type=mission_type, err=str(exc))
            raise