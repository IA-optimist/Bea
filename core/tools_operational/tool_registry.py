"""
core/tools_operational/tool_registry.py — Unified registry for external operational tools.

Thread-safe singleton. Tools can be registered programmatically or loaded from JSON files.
"""
from __future__ import annotations

import os
import threading
import structlog
from pathlib import Path

from core.tools_operational.tool_schema import OperationalTool

log = structlog.get_logger("tools_operational.registry")

# Default directory for tool definition files
_TOOL_DEFS_DIR = Path(os.path.dirname(__file__)).parent.parent / "business" / "tools"


class OperationalToolRegistry:
    """Registry of external tools Jarvis can invoke."""

    def __init__(self):
        self._lock = threading.RLock()
        self._tools: dict[str, OperationalTool] = {}
        self._loaded = False

    def register(self, tool: OperationalTool) -> None:
        """Register a tool programmatically."""
        with self._lock:
            self._tools[tool.id] = tool
            log.debug("tool_registered", tool_id=tool.id)

    def unregister(self, tool_id: str) -> bool:
        with self._lock:
            return self._tools.pop(tool_id, None) is not None

    def get(self, tool_id: str) -> OperationalTool | None:
        if not self._loaded:
            self.load_all()
        with self._lock:
            return self._tools.get(tool_id)

    def list_all(self) -> list[OperationalTool]:
        if not self._loaded:
            self.load_all()
        with self._lock:
            return list(self._tools.values())

    def list_by_category(self, category: str) -> list[OperationalTool]:
        return [t for t in self.list_all() if t.category == category]

    def list_enabled(self) -> list[OperationalTool]:
        return [t for t in self.list_all() if t.enabled]

    def load_all(self) -> int:
        """Load tool definitions from business/tools/*.json."""
        count = 0
        for base_dir in [_TOOL_DEFS_DIR]:
            if not base_dir.is_dir():
                continue
            for f in sorted(base_dir.glob("*.json")):
                try:
                    tool = OperationalTool.from_json_file(f)
                    self.register(tool)
                    count += 1
                except Exception as e:
                    log.warning("tool_load_failed", path=str(f), err=str(e)[:80])
        self._loaded = True
        # Also register built-in tools
        self._register_builtins()
        return count

    def _register_builtins(self) -> None:
        """Register built-in operational tools."""
        builtins = _get_builtin_tools()
        for tool in builtins:
            with self._lock:
                if tool.id not in self._tools:
                    self._tools[tool.id] = tool

    def stats(self) -> dict:
        tools = self.list_all()
        categories = {}
        for t in tools:
            categories[t.category] = categories.get(t.category, 0) + 1
        return {
            "total": len(tools),
            "enabled": sum(1 for t in tools if t.enabled),
            "by_category": categories,
            "approval_required": sum(1 for t in tools if t.requires_approval),
        }


def _get_builtin_tools() -> list[OperationalTool]:
    """Return built-in tool definitions."""
    return [
        OperationalTool(
            id="n8n.workflow.trigger",
            name="n8n Workflow Trigger",
            description="Trigger an n8n workflow via webhook URL. Sends JSON payload and captures response.",
            category="automation",
            risk_level="medium",
            requires_approval=True,
            required_secrets=["N8N_WEBHOOK_URL"],
            input_schema={
                "type": "object",
                "properties": {
                    "payload": {"type": "object", "description": "JSON payload to send to n8n webhook"},
                    "webhook_url_override": {"type": "string", "description": "Optional URL override (default: env)"},
                },
                "required": ["payload"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "status": {"type": "string"},
                    "http_status": {"type": "integer"},
                    "response": {"type": "string"},
                    "timestamp": {"type": "string"},
                    "duration_ms": {"type": "number"},
                },
            },
            retry_policy=from_retry_dict({"max_retries": 2, "backoff_seconds": 3, "enabled": False}),
            timeout=30,
            tags=["n8n", "webhook", "automation"],
        ),
        OperationalTool(
            id="http.webhook.post",
            name="HTTP Webhook POST",
            description="Send a POST request to any configured webhook URL.",
            category="webhook",
            risk_level="medium",
            requires_approval=True,
            required_secrets=[],
            required_configs=["webhook_url"],
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Target URL"},
                    "payload": {"type": "object", "description": "JSON payload"},
                    "headers": {"type": "object", "description": "Optional headers"},
                },
                "required": ["url", "payload"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "status": {"type": "string"},
                    "http_status": {"type": "integer"},
                    "response": {"type": "string"},
                },
            },
            timeout=30,
            tags=["http", "webhook"],
        ),
        OperationalTool(
            id="notification.log",
            name="Log Notification",
            description="Write a structured notification to workspace log file. No external side effects.",
            category="notification",
            risk_level="low",
            requires_approval=False,
            input_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "message": {"type": "string"},
                    "level": {"type": "string", "enum": ["info", "warning", "error"]},
                },
                "required": ["title", "message"],
            },
            output_schema={
                "type": "object",
                "properties": {"logged": {"type": "boolean"}},
            },
            timeout=5,
            tags=["notification", "log"],
        ),
    ]


def from_retry_dict(d: dict):
    from core.tools_operational.tool_schema import RetryPolicy
    return RetryPolicy.from_dict(d)


# ── Singleton ─────────────────────────────────────────────────

_registry: OperationalToolRegistry | None = None
_lock = threading.Lock()


def get_tool_registry() -> OperationalToolRegistry:
    global _registry
    if _registry is None:
        with _lock:
            if _registry is None:
                _registry = OperationalToolRegistry()
    return _registry
