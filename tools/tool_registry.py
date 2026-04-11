"""
tools/tool_registry.py — Tool EXECUTOR Registry
================================================

ROLE: Holds live tool INSTANCES and executes them synchronously.
      This is the "can I run it?" layer.

DISTINCT FROM: core/tool_registry.py — which holds tool DEFINITIONS (metadata,
      descriptions, risk levels). That is the "what tools exist?" layer.

CANONICAL IMPORT for execution:
    from tools.tool_registry import get_tool_registry
    result = get_tool_registry().execute("filesystem_tool", "read", {"path": "..."})

CANONICAL IMPORT for tool discovery/metadata:
    from core.tool_registry import get_tool_registry as get_tool_defs
    tools = get_tool_defs().list_tools()  # returns List[ToolDefinition]

Bridge:
    ToolExecutorRegistry.list_tools() returns List[str] (tool names).
    Merges names from both: live instances + core definitions.

NOTE: This file was previously confusingly named identical to core/tool_registry.py.
      Renaming the class to ToolExecutorRegistry is tracked but deferred to avoid
      cascading import changes. Both registries will be unified in a future pass.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
_silent_log = __import__("structlog").get_logger(__name__)


@dataclass
class ToolResult:
    tool_name: str
    success: bool
    result: Any = None
    error: str = ""
    duration_ms: int = 0
    risk_level: str = "safe"


class ToolRegistry:
    """
    Tool EXECUTOR registry.
    Holds live tool instances and dispatches .execute() calls.

    For tool DEFINITIONS and metadata, use core.tool_registry.ToolRegistry.

    Usage:
        registry = get_tool_registry()
        result = registry.execute("filesystem_tool", "read", {"path": "workspace/foo.txt"})
    """

    _instance = None

    def __init__(self):
        self._tools: dict[str, Any] = {}
        self._execution_log: list[dict] = []

    @classmethod
    def get_instance(cls) -> "ToolRegistry":
        if cls._instance is None:
            cls._instance = cls()
            cls._instance._auto_register()
        return cls._instance

    def register(self, name: str, tool_instance: Any) -> None:
        """Register a live tool instance under the given name."""
        self._tools[name] = tool_instance

    def execute(
        self,
        tool_name: str,
        action: str,
        params: dict = None,
        timeout: int = 30,
    ) -> ToolResult:
        """Execute tool action. Returns ToolResult — never raises."""
        params = params or {}
        t0 = time.perf_counter()

        tool = self._tools.get(tool_name)
        if tool is None:
            ms = int((time.perf_counter() - t0) * 1000)
            result = ToolResult(
                tool_name=tool_name,
                success=False,
                error=f"Tool '{tool_name}' not registered in executor registry",
                duration_ms=ms,
            )
            self._log(result, action)
            return result

        try:
            method = getattr(tool, action, None)
            if method is None:
                raise AttributeError(f"Tool '{tool_name}' has no action '{action}'")

            raw = method(**params)
            ms = int((time.perf_counter() - t0) * 1000)

            # Determine risk level from tool if available
            risk = "safe"
            try:
                risk = tool.risk.value if hasattr(tool, "risk") else "safe"
            except Exception:
                _silent_log.debug("suppressed_exception", src='tool_registry.py')

            if isinstance(raw, dict):
                success = raw.get("success", True)
                error = raw.get("error", "")
                result_data = raw.get("result") or raw
            else:
                success = True
                error = ""
                result_data = raw

            result = ToolResult(
                tool_name=tool_name,
                success=success,
                result=result_data,
                error=error,
                duration_ms=ms,
                risk_level=risk,
            )
        except Exception as e:
            ms = int((time.perf_counter() - t0) * 1000)
            result = ToolResult(
                tool_name=tool_name,
                success=False,
                error=str(e),
                duration_ms=ms,
            )

        self._log(result, action)
        return result

    def list_tools(self) -> list[str]:
        """
        Return sorted list of all known tool names.

        Merges:
        - Live instances registered in this executor registry
        - Tool names from core.tool_registry (definition registry)
        """
        live_names = set(self._tools.keys())
        # Pull names from definition registry — fail-open
        try:
            from core.tool_registry import get_tool_registry as _get_defs
            defs = _get_defs()
            for td in defs.list_tools():
                live_names.add(td.name)
        except Exception:
            _silent_log.debug("suppressed_exception", src='tool_registry.py')
        return sorted(live_names)

    def get_tool_stats(self) -> dict[str, dict]:
        """Return per-tool execution stats from log."""
        stats: dict[str, dict] = {}
        for entry in self._execution_log:
            name = entry.get("tool_name", "?")
            if name not in stats:
                stats[name] = {"calls": 0, "failures": 0, "total_ms": 0}
            stats[name]["calls"] += 1
            if not entry.get("success"):
                stats[name]["failures"] += 1
            stats[name]["total_ms"] += entry.get("duration_ms", 0)
        return stats

    def _log(self, result: ToolResult, action: str) -> None:
        """Append to in-memory execution log (last 1000 entries)."""
        self._execution_log.append({
            "tool_name": result.tool_name,
            "action": action,
            "success": result.success,
            "error": result.error,
            "duration_ms": result.duration_ms,
        })
        if len(self._execution_log) > 1000:
            self._execution_log = self._execution_log[-1000:]

    def _auto_register(self) -> None:
        """Auto-register available tool instances at init. Fail-open per tool."""
        tool_classes = [
            ("filesystem_tool",   "tools.filesystem_tool",   "FilesystemTool"),
            ("python_tool",       "tools.python_tool",       "PythonTool"),
            ("web_research_tool", "tools.web_research_tool", "WebResearchTool"),
            ("dependency_tool",   "tools.dependency_tool",   "DependencyTool"),
        ]
        for name, module_path, class_name in tool_classes:
            try:
                import importlib
                mod = importlib.import_module(module_path)
                cls = getattr(mod, class_name)
                self._tools[name] = cls()
            except Exception:
                pass  # fail-open — skip unavailable tools


def get_tool_registry() -> ToolRegistry:
    """Get the singleton ToolExecutorRegistry."""
    return ToolRegistry.get_instance()
