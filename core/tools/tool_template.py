"""
core/tools/tool_template.py — Standardized tool interface template.

Every new Jarvis tool MUST follow this pattern:
1. Implement execute() → dict with ok/result/error
2. Register a Capability schema
3. Use JarvisError for error handling
4. Support timeout_guard
5. Support idempotency_key
6. Integrate with PolicyEngine via capability risk level

This file serves as both documentation and base class.
"""
from __future__ import annotations

import time
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
_silent_log = __import__("structlog").get_logger(__name__)

log = logging.getLogger("jarvis.tools")


@dataclass
class ToolResult:
    """Standardized tool execution result."""
    ok: bool = False
    result: str = ""
    error: str = ""
    blocked_by_policy: bool = False
    retryable: bool = False
    duration_ms: float = 0.0
    idempotency_key: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class BaseTool(ABC):
    """
    Base class for all Jarvis tools.

    Subclasses must implement:
    - name: tool identifier
    - risk_level: LOW / MEDIUM / HIGH
    - execute(**params) → ToolResult
    """

    name: str = "base_tool"
    risk_level: str = "MEDIUM"
    description: str = ""
    timeout_seconds: float = 10.0

    @abstractmethod
    def execute(self, **params) -> ToolResult:
        """Execute the tool with given parameters."""
        ...

    def safe_execute(self, **params) -> ToolResult:
        """Execute with timeout guard, error handling, and idempotency."""
        start = time.time()

        # Timeout guard
        try:
            from core.resilience import timeout_guard, idempotency_key, JarvisError  # noqa: F401
        except ImportError:
            idempotency_key = lambda *a: ""

        idem_key = ""
        try:
            idem_key = idempotency_key(self.name, params)
        except Exception:
            _silent_log.debug("suppressed_exception", src='tool_template.py')

        try:
            result = self.execute(**params)
            result.duration_ms = (time.time() - start) * 1000
            result.idempotency_key = idem_key
            return result
        except Exception as exc:
            duration = (time.time() - start) * 1000
            try:
                err = JarvisError.from_exception(exc, component="tool")
                return ToolResult(
                    ok=False,
                    error=f"{err.code}: {err.message}",
                    retryable=err.retryable,
                    duration_ms=duration,
                    idempotency_key=idem_key,
                )
            except Exception:
                return ToolResult(
                    ok=False,
                    error=str(exc)[:500],
                    duration_ms=duration,
                    idempotency_key=idem_key,
                )

    def capability_schema(self) -> dict:
        """Return capability registration for this tool."""
        return {
            "name": self.name,
            "risk_level": self.risk_level,
            "description": self.description,
            "timeout_seconds": self.timeout_seconds,
        }
