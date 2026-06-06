"""
integrations/mcp/mcp_adapter.py — MCP tool invocation adapter.

Invokes MCP tools via HTTP (or stdio stub).
Always returns structured dict {ok, result, error}.
Never raises — failure is returned as structured error.

Integration: called by executor.capability_dispatch, not directly.

Observability (Cycle 2 Phase B):
- Every tool call logs: tool_id, tool_name, server_id, provider, latency_ms, status
- When LANGFUSE_ENABLED=true: emits a Langfuse span per tool call (never blocks)
"""
from __future__ import annotations
import os
import time
from typing import Any, Optional
import structlog

from integrations.mcp.mcp_registry import get_mcp_registry
from integrations.mcp.mcp_models import MCPTool, MCPServer

log = structlog.get_logger("mcp.adapter")

_HTTP_TIMEOUT = 10.0  # seconds


class MCPAdapter:
    """
    Invokes MCP tools.

    Resolves tool_id → server endpoint via MCPRegistry,
    then dispatches HTTP POST to the MCP server.
    """

    def __init__(self, registry=None):
        self._registry = registry or get_mcp_registry()

    async def invoke_tool(
        self,
        tool_id: str,
        params: dict,
        context: Optional[dict] = None,
    ) -> dict:
        """
        Invoke an MCP tool by ID.

        Returns:
            {ok: bool, result: Any, error: str|None, tool_id: str, ms: int}
        """
        t0 = time.monotonic()
        context = context or {}

        tool = self._registry.get_tool(tool_id)
        if tool is None:
            return self._error(tool_id, "Tool not found in MCP registry", t0)

        server = self._registry.get_server(tool.server_id)
        if server is None:
            return self._error(tool_id, f"Server {tool.server_id!r} not found", t0)

        if server.health_status == "unavailable":
            return self._error(tool_id, f"Server {server.name!r} is unavailable", t0)

        # Dispatch by transport
        if server.transport == "http":
            return await self._invoke_http(tool, server, params, context, t0)
        else:
            return self._error(
                tool_id,
                f"Unsupported MCP transport: {server.transport!r}",
                t0
            )

    async def _invoke_http(
        self,
        tool: MCPTool,
        server: MCPServer,
        params: dict,
        context: dict,
        t0: float,
    ) -> dict:
        """HTTP invocation of MCP tool with structured observability."""
        provider = (server.metadata or {}).get("provider", server.server_id)
        try:
            import httpx
            url = f"{server.endpoint.rstrip('/')}/invoke"
            payload = {
                "tool": tool.name,
                "params": params,
                "context": context,
            }
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
            ms = int((time.monotonic() - t0) * 1000)
            log.info("mcp_tool_invoked",
                     tool_id=tool.tool_id,
                     tool_name=tool.name,
                     server_id=server.server_id,
                     provider=provider,
                     status="ok",
                     ms=ms)
            _trace_mcp_langfuse(tool, server, params, data, ms,
                                success=True, error=None)
            return {"ok": True, "result": data, "error": None,
                    "tool_id": tool.tool_id, "ms": ms}
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            ms = int((time.monotonic() - t0) * 1000)
            # Mark server degraded on connection errors
            if "Connect" in type(exc).__name__ or "Timeout" in type(exc).__name__:
                self._registry.update_health(server.server_id, "degraded")
            log.warning("mcp_tool_failed",
                        tool_id=tool.tool_id,
                        tool_name=tool.name,
                        server_id=server.server_id,
                        provider=provider,
                        status="error",
                        ms=ms,
                        error=err[:120])
            _trace_mcp_langfuse(tool, server, params, None, ms,
                                success=False, error=err)
            return self._error(tool.tool_id, err, t0)

    async def check_health(self, server_id: str) -> str:
        """
        Ping MCP server health endpoint.
        Returns "ok", "degraded", or "unavailable".
        """
        server = self._registry.get_server(server_id)
        if server is None:
            return "unavailable"
        try:
            import httpx
            url = f"{server.endpoint.rstrip('/')}/health"
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(url)
                status = "ok" if resp.status_code == 200 else "degraded"
        except Exception:
            status = "unavailable"
        self._registry.update_health(server_id, status)
        return status

    @staticmethod
    def _error(tool_id: str, msg: str, t0: float) -> dict:
        ms = int((time.monotonic() - t0) * 1000)
        log.warning("mcp_tool_error", tool_id=tool_id, error=msg, ms=ms)
        return {"ok": False, "result": None, "error": msg,
                "tool_id": tool_id, "ms": ms}


# ── Langfuse observability (Phase B) ──────────────────────────────────────────

def _trace_mcp_langfuse(
    tool: "MCPTool",
    server: "MCPServer",
    params: dict,
    result: Any,
    ms: int,
    success: bool,
    error: Optional[str],
) -> None:
    """
    Emit a Langfuse span for an MCP tool call.

    Only active when LANGFUSE_ENABLED=true. Never raises — observability
    must never break tool invocations.

    Emitted fields (no secret leakage):
      - tool_id, tool_name, server_id, provider
      - latency_ms, success, error (truncated)
      - params keys only (values may be sensitive)
    """
    try:
        if os.environ.get("LANGFUSE_ENABLED", "false").lower() not in ("1", "true", "yes"):
            return
        from langfuse import Langfuse
        lf = Langfuse()
        provider = (server.metadata or {}).get("provider", server.server_id)
        trace = lf.trace(name="mcp_tool_call", metadata={"source": "jarvis_mcp_adapter"})
        trace.span(
            name=tool.tool_id,
            input={"tool": tool.name, "params_keys": list(params.keys())},
            output={"ok": success, "error": (error or "")[:120]},
            metadata={
                "server_id": server.server_id,
                "provider": provider,
                "latency_ms": ms,
                "success": success,
                "risk_level": tool.risk_level,
            },
        )
        lf.flush()
    except Exception:
        log.debug("swallowed_exception", exc_info=True)
