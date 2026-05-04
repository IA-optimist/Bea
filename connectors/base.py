"""
connectors/base.py — Base connector interface + registry.

Design:
  - ConnectorBase: abstract interface for all connectors
  - ConnectorResult: structured action result
  - ConnectorRegistry: discover, enable, disable connectors
  - Policy check before every action
  - ExecutionTrace for every action
  - Disable via CONNECTOR_{NAME}_ENABLED=0
"""
from __future__ import annotations

import os
import time
import uuid
import structlog
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
_silent_log = __import__("structlog").get_logger(__name__)

log = structlog.get_logger("connectors")


@dataclass
class ConnectorResult:
    """Result of a connector action."""
    connector: str = ""
    action: str = ""
    success: bool = False
    output: dict = field(default_factory=dict)
    error: str = ""
    duration_ms: float = 0
    trace_id: str = ""
    policy_checked: bool = False

    def __post_init__(self):
        if not self.trace_id:
            self.trace_id = f"ct-{uuid.uuid4().hex[:8]}"

    def to_dict(self) -> dict:
        return {
            "connector": self.connector,
            "action": self.action,
            "success": self.success,
            "output": {k: str(v)[:500] for k, v in self.output.items()},
            "error": self.error[:300],
            "duration_ms": round(self.duration_ms),
            "trace_id": self.trace_id,
            "policy_checked": self.policy_checked,
        }


class ConnectorBase(ABC):
    """Abstract base for all connectors."""

    name: str = "base"
    description: str = ""
    actions: list[str] = []

    def is_enabled(self) -> bool:
        """Check if connector is enabled via env var."""
        key = f"CONNECTOR_{self.name.upper()}_ENABLED"
        return os.environ.get(key, "1") != "0"

    def is_configured(self) -> bool:
        """Check if connector has required configuration."""
        return True

    @abstractmethod
    def execute(self, action: str, params: dict) -> ConnectorResult:
        """Execute an action. Must be implemented by subclass."""
        ...

    def _check_policy(self, action: str, params: dict) -> tuple[bool, str]:
        """Check policy before executing action."""
        try:
            from core.execution.policy import check_content_policy
            blocked = check_content_policy(str(params))
            if blocked:
                return False, f"Policy blocked: {blocked}"
        except Exception:
            pass  # Fail-open
        return True, ""

    def _record_trace(self, result: ConnectorResult) -> None:
        """Record action in cognitive journal."""
        try:
            from core.cognitive_events.emitter import ce_emit
            ce_emit.tool_completed(
                tool_id=f"connector.{self.name}.{result.action}",
                mission_id="",
                duration_ms=result.duration_ms,
                metadata={
                    "success": result.success,
                    "trace_id": result.trace_id,
                    "connector": self.name,
                },
            )
        except Exception:
            _silent_log.debug("suppressed_exception", src='base.py')

    def safe_execute(self, action: str, params: dict) -> ConnectorResult:
        """Execute with policy check, tracing, and error handling."""
        t0 = time.time()
        result = ConnectorResult(connector=self.name, action=action)

        if not self.is_enabled():
            result.error = f"Connector {self.name} is disabled"
            result.duration_ms = (time.time() - t0) * 1000
            return result

        # Policy check
        ok, reason = self._check_policy(action, params)
        result.policy_checked = True
        if not ok:
            result.error = reason
            result.duration_ms = (time.time() - t0) * 1000
            return result

        try:
            result = self.execute(action, params)
            result.policy_checked = True
        except Exception as e:
            result.error = str(e)[:300]

        result.duration_ms = (time.time() - t0) * 1000
        self._record_trace(result)
        return result

    def get_status(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "enabled": self.is_enabled(),
            "configured": self.is_configured(),
            "actions": self.actions,
        }


class ConnectorRegistry:
    """Registry of all available connectors."""

    def __init__(self):
        self._connectors: dict[str, ConnectorBase] = {}

    def register(self, connector: ConnectorBase) -> None:
        self._connectors[connector.name] = connector

    def get(self, name: str) -> Optional[ConnectorBase]:
        return self._connectors.get(name)

    def list_all(self) -> list[dict]:
        return [c.get_status() for c in self._connectors.values()]

    def get_enabled(self) -> list[ConnectorBase]:
        return [c for c in self._connectors.values() if c.is_enabled()]

    def execute(self, connector_name: str, action: str, params: dict) -> ConnectorResult:
        """Execute an action on a named connector."""
        c = self._connectors.get(connector_name)
        if not c:
            return ConnectorResult(
                connector=connector_name, action=action,
                error=f"Connector '{connector_name}' not found",
            )
        return c.safe_execute(action, params)


# Singleton
_registry = ConnectorRegistry()


def get_connector_registry() -> ConnectorRegistry:
    return _registry
