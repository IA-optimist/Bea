"""Shared types, decorators, and path-guard used across all tool modules."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from collections.abc import Callable
from typing import Any

import structlog

log = structlog.get_logger(__name__)

REPO_ROOT = Path(os.environ.get("BEAMAX_REPO", ".")).resolve()


class ToolRisk(str, Enum):
    SAFE       = "safe"
    SUPERVISED = "supervised"
    DANGEROUS  = "dangerous"


@dataclass
class ToolResult:
    """Structured output from every tool call."""
    success:     bool
    tool:        str
    data:        Any  = None
    error:       str  = ""
    risk:        str  = "safe"
    duration_ms: int  = 0
    meta:        dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "tool": self.tool,
            "data": self.data,
            "error": self.error,
            "risk": self.risk,
            "duration_ms": self.duration_ms,
            "meta": self.meta,
        }


def _timed(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator that measures execution time and wraps exceptions."""
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        t0 = time.monotonic()
        try:
            result = fn(*args, **kwargs)
            if isinstance(result, ToolResult):
                result.duration_ms = int((time.monotonic() - t0) * 1000)
            return result
        except Exception as e:
            ms = int((time.monotonic() - t0) * 1000)
            tool_name = fn.__name__.replace("tool_", "")
            log.warning("tool_failed", tool=tool_name, err=str(e)[:200])
            return ToolResult(
                success=False, tool=tool_name,
                error=str(e)[:500], duration_ms=ms,
            )
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


PROTECTED_FILES = frozenset({
    "core/meta_orchestrator.py",
    "core/mission_system.py",
    "core/state.py",
    "core/contracts.py",
    "config/settings.py",
    "agents/crew.py",
})

PROTECTED_DIRS = frozenset({
    "core/contracts",
    "config",
})


def is_protected(path: str) -> bool:
    """Check if a path is protected (requires reviewer approval to modify)."""
    rel = str(Path(path).relative_to(REPO_ROOT)) if Path(path).is_absolute() else path
    rel = rel.lstrip("./")
    if rel in PROTECTED_FILES:
        return True
    for d in PROTECTED_DIRS:
        if rel.startswith(d + "/") or rel == d:
            return True
    return False
