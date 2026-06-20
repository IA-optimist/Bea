"""
core/mcp/tool_loader.py — MCP Tool Hot-Load Infrastructure

Dynamic tool loading with manifest validation and signature verification.
Supports hot-loading tools from:
- Local manifest files (*.json)
- Plugin directories
- Remote repositories (future)

Hot-load workflow:
1. Discover manifest files
2. Validate manifest structure and signature
3. Check permissions and risk level
4. Register tool in MCP registry
5. Load tool implementation
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass

import structlog

from core.mcp.manifest_schema import (
    ToolManifest,
    validate_manifest,
    CORE_TOOL_MANIFESTS,
)

log = structlog.get_logger("mcp.tool_loader")


@dataclass
class LoadedTool:
    """A successfully loaded MCP tool."""
    manifest: ToolManifest
    implementation: Any
    load_path: str
    loaded_at: float
    is_active: bool = True


class ToolLoadError(Exception):
    """Error loading a tool."""
    def __init__(self, tool_id: str, reason: str):
        self.tool_id = tool_id
        self.reason = reason
        super().__init__(f"Failed to load tool '{tool_id}': {reason}")


class MCPToolLoader:
    """
    Hot-load MCP tools from manifests with validation.
    
    Thread-safe. Supports dynamic loading/unloading of tools.
    """

    def __init__(self, manifest_dirs: Optional[List[str]] = None):
        self._manifest_dirs = [Path(d) for d in (manifest_dirs or ["data/mcp/tools"])]
        self._loaded_tools: Dict[str, LoadedTool] = {}
        self._lock = threading.RLock()

        # Ensure manifest directories exist
        for dir_path in self._manifest_dirs:
            dir_path.mkdir(parents=True, exist_ok=True)

    def discover_manifests(self) -> List[Path]:
        """Discover all manifest files in configured directories."""
        manifests = []
        for dir_path in self._manifest_dirs:
            if dir_path.exists():
                manifests.extend(dir_path.glob("**/*.json"))
        return manifests

    def load_manifest_from_file(self, path: Path) -> ToolManifest:
        """Load and validate a manifest from a file."""
        try:
            content = path.read_text(encoding="utf-8")
            data = json.loads(content)
            manifest = ToolManifest.from_dict(data)

            # Validate manifest
            validation = validate_manifest(manifest)
            if not validation["valid"]:
                raise ToolLoadError(
                    manifest.tool_id or path.name,
                    f"Validation failed: {', '.join(validation['issues'])}"
                )

            return manifest
        except json.JSONDecodeError as e:
            raise ToolLoadError(path.name, f"Invalid JSON: {e}")
        except Exception as e:
            raise ToolLoadError(path.name, f"Load error: {e}")

    def load_tool(
        self,
        manifest: ToolManifest,
        implementation_path: Optional[str] = None,
    ) -> LoadedTool:
        """
        Load a tool from manifest.
        
        Args:
            manifest: Validated tool manifest
            implementation_path: Optional path to tool implementation module
        
        Returns:
            LoadedTool instance
        
        Raises:
            ToolLoadError: If tool cannot be loaded
        """
        tool_id = manifest.tool_id

        with self._lock:
            # Check if already loaded
            if tool_id in self._loaded_tools:
                log.info("tool_already_loaded", tool_id=tool_id)
                return self._loaded_tools[tool_id]

            try:
                # Load implementation
                implementation = self._load_implementation(
                    tool_id,
                    implementation_path,
                )

                # Create loaded tool record
                import time
                loaded = LoadedTool(
                    manifest=manifest,
                    implementation=implementation,
                    load_path=implementation_path or "builtin",
                    loaded_at=time.time(),
                    is_active=True,
                )

                self._loaded_tools[tool_id] = loaded
                log.info(
                    "tool_loaded",
                    tool_id=tool_id,
                    risk_level=manifest.risk_level.value,
                    permissions=len(manifest.permissions),
                )

                return loaded

            except Exception as e:
                raise ToolLoadError(tool_id, str(e))

    def _load_implementation(
        self,
        tool_id: str,
        implementation_path: Optional[str],
    ) -> Any:
        """Load tool implementation.

        External Python files are intentionally *not* executed to avoid arbitrary
        code execution from dropped manifests. Only built-in stubs or explicitly
        allow-listed implementations are supported.
        """
        if implementation_path:
            raise ToolLoadError(
                tool_id,
                "External Python implementations are disabled for security",
            )

        return type(
            "ToolStub",
            (),
            {
                "tool_id": tool_id,
                "execute": lambda self, **kwargs: {
                    "result": f"Stub execution for {tool_id}",
                    "kwargs": kwargs,
                },
            },
        )()

    def unload_tool(self, tool_id: str) -> bool:
        """Unload a tool."""
        with self._lock:
            if tool_id in self._loaded_tools:
                del self._loaded_tools[tool_id]
                log.info("tool_unloaded", tool_id=tool_id)
                return True
            return False

    def get_tool(self, tool_id: str) -> Optional[LoadedTool]:
        """Get a loaded tool."""
        return self._loaded_tools.get(tool_id)

    def list_loaded_tools(self) -> List[LoadedTool]:
        """List all loaded tools."""
        return list(self._loaded_tools.values())

    def load_all_core_tools(self) -> int:
        """Load all core tools from CORE_TOOL_MANIFESTS."""
        count = 0
        for tool_id, manifest in CORE_TOOL_MANIFESTS.items():
            try:
                self.load_tool(manifest)
                count += 1
            except ToolLoadError as e:
                log.warning("core_tool_load_failed", tool_id=tool_id, error=str(e))
        return count

    def load_from_directory(self, directory: Path) -> int:
        """Load all manifests from a directory.

        Implementation files next to manifests are intentionally ignored.
        """
        count = 0
        if not directory.exists():
            log.warning("manifest_directory_not_found", path=str(directory))
            return 0

        for manifest_file in directory.glob("*.json"):
            try:
                manifest = self.load_manifest_from_file(manifest_file)
                self.load_tool(manifest, implementation_path=None)
                count += 1

            except ToolLoadError as e:
                log.warning("tool_load_failed", file=str(manifest_file), error=str(e))

        log.info("tools_loaded_from_directory", count=count, directory=str(directory))
        return count

    def reload_tool(self, tool_id: str) -> Optional[LoadedTool]:
        """Reload a tool (useful for development)."""
        with self._lock:
            if tool_id not in self._loaded_tools:
                return None

            old_tool = self._loaded_tools[tool_id]
            manifest = old_tool.manifest

            try:
                self.unload_tool(tool_id)
                return self.load_tool(manifest, old_tool.load_path)
            except ToolLoadError as e:
                log.error("tool_reload_failed", tool_id=tool_id, error=str(e))
                return None

    def get_tool_stats(self) -> Dict[str, Any]:
        """Get statistics about loaded tools."""
        by_risk: Dict[str, int] = {}
        for tool in self._loaded_tools.values():
            risk = tool.manifest.risk_level.value
            by_risk[risk] = by_risk.get(risk, 0) + 1

        return {
            "total_loaded": len(self._loaded_tools),
            "by_risk_level": by_risk,
            "active_tools": sum(1 for t in self._loaded_tools.values() if t.is_active),
        }


# Singleton
_loader: Optional[MCPToolLoader] = None
_loader_lock = threading.Lock()


def get_tool_loader() -> MCPToolLoader:
    """Get the singleton MCP tool loader."""
    global _loader
    with _loader_lock:
        if _loader is None:
            _loader = MCPToolLoader()
            # Auto-load core tools
            _loader.load_all_core_tools()
    return _loader
