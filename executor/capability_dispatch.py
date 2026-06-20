"""
executor/capability_dispatch.py — Capability routing layer.

Routes CapabilityRequest to the right backend:
- NATIVE_TOOL → registered handler function
- PLUGIN → PluginRegistry → plugin.invoke()
- MCP_TOOL → MCPAdapter → MCP server HTTP call

All paths return CapabilityResult. Never raises.

MetaOrchestrator and Executor use this as the single dispatch point
for non-standard (non-core) capability invocations.
"""
from __future__ import annotations
import time
import asyncio
import threading
from typing import Any, Awaitable, Protocol, cast
import structlog

from executor.capability_contracts import (
    CapabilityRequest, CapabilityResult, CapabilityType
)

log = structlog.get_logger("executor.capability_dispatch")

# Hard timeouts for each dispatch path. These are intentionally conservative:
# native tools (in-process) get 30s, plugins (subprocess/network) 60s,
# MCP tools (external HTTP servers) 30s.
_NATIVE_TIMEOUT_S = 30
_PLUGIN_TIMEOUT_S = 60
_MCP_TIMEOUT_S = 30


class _NativeHandler(Protocol):
    def __call__(self, **kwargs: Any) -> Any: ...


class _PluginLike(Protocol):
    def invoke(self, action: str, params: dict[str, Any], context: dict[str, Any]) -> Any: ...


class _McpAdapterLike(Protocol):
    def invoke_tool(self, tool_id: str, params: dict[str, Any], context: dict[str, Any]) -> Awaitable[dict[str, Any]]: ...


class CapabilityDispatcher:
    """
    Single dispatch point for all capability types.

    Registration:
        dispatcher.register_native_tool("my_tool", handler_fn)
        dispatcher.register_plugin("my_plugin", plugin_instance)
        dispatcher.set_mcp_adapter(mcp_adapter_instance)

    Invocation:
        result = await dispatcher.dispatch(request)
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._native: dict[str, _NativeHandler] = {}
        self._mcp_adapter: _McpAdapterLike | None = None

    # ── Registration ──────────────────────────────────────────

    def register_native_tool(self, tool_id: str, handler: _NativeHandler) -> None:
        with self._lock:
            self._native[tool_id] = handler
        log.debug("native_tool_registered", tool_id=tool_id)

    def register_plugin(self, plugin_id: str, plugin: _PluginLike) -> None:
        from plugins.plugin_registry import get_plugin_registry
        get_plugin_registry().register(plugin)
        log.debug("plugin_registered_via_dispatcher", plugin_id=plugin_id)

    def set_mcp_adapter(self, adapter: _McpAdapterLike) -> None:
        self._mcp_adapter = adapter
        log.info("mcp_adapter_attached")

    # ── Dispatch ──────────────────────────────────────────────

    async def dispatch(self, request: CapabilityRequest) -> CapabilityResult:
        """Route request to appropriate backend. Never raises."""
        t0 = time.monotonic()
        try:
            if request.capability_type == CapabilityType.NATIVE_TOOL:
                return await self._dispatch_native(request, t0)
            elif request.capability_type == CapabilityType.PLUGIN:
                return await self._dispatch_plugin(request, t0)
            elif request.capability_type == CapabilityType.MCP_TOOL:
                return await self._dispatch_mcp(request, t0)
            else:
                return CapabilityResult.failure(
                    request.capability_type,
                    request.capability_id,
                    f"Unknown capability type: {request.capability_type!r}",
                    ms=_ms(t0),
                )
        except Exception as exc:
            err = f"Dispatch error: {type(exc).__name__}: {exc}"
            log.error("capability_dispatch_error",
                      capability_id=request.capability_id, error=err)
            return CapabilityResult.failure(
                request.capability_type, request.capability_id, err, ms=_ms(t0)
            )

    async def _dispatch_native(
        self, req: CapabilityRequest, t0: float
    ) -> CapabilityResult:
        handler = self._native.get(req.capability_id)
        if handler is None:
            return CapabilityResult.failure(
                CapabilityType.NATIVE_TOOL, req.capability_id,
                f"Native tool {req.capability_id!r} not registered",
                ms=_ms(t0),
            )
        try:
            if asyncio.iscoroutinefunction(handler):
                result = await asyncio.wait_for(
                    handler(**req.params), timeout=_NATIVE_TIMEOUT_S
                )
            else:
                loop = asyncio.get_running_loop()
                result = await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: handler(**req.params)),
                    timeout=_NATIVE_TIMEOUT_S,
                )
        except asyncio.TimeoutError:
            err = f"Native tool {req.capability_id!r} timed out after {_NATIVE_TIMEOUT_S}s"
            log.warning("native_tool_timeout", capability_id=req.capability_id,
                        timeout_s=_NATIVE_TIMEOUT_S)
            return CapabilityResult.failure(
                CapabilityType.NATIVE_TOOL, req.capability_id, err, ms=_ms(t0)
            )
        return CapabilityResult.success(
            CapabilityType.NATIVE_TOOL, req.capability_id, result, ms=_ms(t0)
        )

    async def _dispatch_plugin(
        self, req: CapabilityRequest, t0: float
    ) -> CapabilityResult:
        from plugins.plugin_registry import get_plugin_registry
        registry = get_plugin_registry()

        if not registry.is_available(req.capability_id):
            return CapabilityResult.failure(
                CapabilityType.PLUGIN, req.capability_id,
                f"Plugin {req.capability_id!r} unavailable or not registered",
                ms=_ms(t0),
            )

        plugin = cast(_PluginLike, registry.get(req.capability_id))
        try:
            if asyncio.iscoroutinefunction(plugin.invoke):
                result = await asyncio.wait_for(
                    plugin.invoke(req.action, req.params, req.context),
                    timeout=_PLUGIN_TIMEOUT_S,
                )
            else:
                loop = asyncio.get_running_loop()
                result = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda: plugin.invoke(req.action, req.params, req.context),
                    ),
                    timeout=_PLUGIN_TIMEOUT_S,
                )
            return CapabilityResult.success(
                CapabilityType.PLUGIN, req.capability_id, result, ms=_ms(t0)
            )
        except asyncio.TimeoutError:
            err = f"Plugin {req.capability_id!r} timed out after {_PLUGIN_TIMEOUT_S}s"
            log.warning("plugin_timeout", plugin_id=req.capability_id,
                        timeout_s=_PLUGIN_TIMEOUT_S)
            return CapabilityResult.failure(
                CapabilityType.PLUGIN, req.capability_id, err, ms=_ms(t0)
            )
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            log.warning("plugin_invoke_failed",
                        plugin_id=req.capability_id, error=err)
            return CapabilityResult.failure(
                CapabilityType.PLUGIN, req.capability_id, err, ms=_ms(t0)
            )

    async def _dispatch_mcp(
        self, req: CapabilityRequest, t0: float
    ) -> CapabilityResult:
        if self._mcp_adapter is None:
            return CapabilityResult.failure(
                CapabilityType.MCP_TOOL, req.capability_id,
                "No MCP adapter registered. Call dispatcher.set_mcp_adapter()",
                ms=_ms(t0),
            )
        try:
            raw = await asyncio.wait_for(
                self._mcp_adapter.invoke_tool(req.capability_id, req.params, req.context),
                timeout=_MCP_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            err = f"MCP tool {req.capability_id!r} timed out after {_MCP_TIMEOUT_S}s"
            log.warning("mcp_tool_timeout", capability_id=req.capability_id,
                        timeout_s=_MCP_TIMEOUT_S)
            return CapabilityResult.failure(
                CapabilityType.MCP_TOOL, req.capability_id, err, ms=_ms(t0)
            )
        if raw.get("ok"):
            return CapabilityResult.success(
                CapabilityType.MCP_TOOL, req.capability_id,
                raw.get("result"), ms=raw.get("ms", _ms(t0))
            )
        return CapabilityResult.failure(
            CapabilityType.MCP_TOOL, req.capability_id,
            raw.get("error", "Unknown MCP error"), ms=raw.get("ms", _ms(t0))
        )

    # ── Introspection ─────────────────────────────────────────

    def list_capabilities(self) -> dict[str, list[str]]:
        from plugins.plugin_registry import get_plugin_registry
        from integrations.mcp.mcp_registry import get_mcp_registry
        return {
            "native_tools": list(self._native.keys()),
            "plugins": [m.plugin_id for m in get_plugin_registry().list_available()],
            "mcp_tools": [t.tool_id for t in get_mcp_registry().list_tools()],
        }


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


# ── Singleton ─────────────────────────────────────────────────
_dispatcher: CapabilityDispatcher | None = None
_dispatcher_lock = threading.Lock()


def get_capability_dispatcher() -> CapabilityDispatcher:
    global _dispatcher
    with _dispatcher_lock:
        if _dispatcher is None:
            _dispatcher = CapabilityDispatcher()
        dispatcher = _dispatcher
    assert dispatcher is not None
    return dispatcher
