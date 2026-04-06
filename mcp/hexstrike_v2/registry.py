"""
HexStrike Tool Registry — Hermes Pattern

Inspired by: hermes-agent/tools/registry.py
Central registry for all security tools with clean registration API.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ToolDefinition:
    """Definition of a security tool"""
    name: str
    category: str  # recon, scanning, exploitation, web, network, reporting
    description: str
    handler: Callable[[Dict[str, Any]], Dict[str, Any]]
    parameters: Dict[str, Any] = field(default_factory=dict)
    risk_level: str = "medium"  # low, medium, high
    requires_approval: bool = False
    requires_env: List[str] = field(default_factory=list)
    check_fn: Optional[Callable[[], bool]] = None
    tags: List[str] = field(default_factory=list)


class ToolRegistry:
    """
    Central registry for all HexStrike security tools.
    
    Usage:
        registry = ToolRegistry()
        registry.register(
            name="nmap_scan",
            category="recon",
            description="Network reconnaissance with Nmap",
            handler=nmap_handler,
            risk_level="medium",
            requires_approval=True
        )
        
        tool = registry.get_tool("nmap_scan")
        result = tool.handler({"target": "example.com"})
    """
    
    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}
        self._categories: Dict[str, List[str]] = {}
    
    def register(
        self,
        name: str,
        category: str,
        description: str,
        handler: Callable[[Dict[str, Any]], Dict[str, Any]],
        parameters: Dict[str, Any] = None,
        risk_level: str = "medium",
        requires_approval: bool = False,
        requires_env: List[str] = None,
        check_fn: Optional[Callable[[], bool]] = None,
        tags: List[str] = None,
    ) -> None:
        """Register a new security tool"""
        if name in self._tools:
            logger.warning(f"Tool '{name}' already registered, overwriting")
        
        tool = ToolDefinition(
            name=name,
            category=category,
            description=description,
            handler=handler,
            parameters=parameters or {},
            risk_level=risk_level,
            requires_approval=requires_approval,
            requires_env=requires_env or [],
            check_fn=check_fn,
            tags=tags or [],
        )
        
        self._tools[name] = tool
        
        # Update category index
        if category not in self._categories:
            self._categories[category] = []
        if name not in self._categories[category]:
            self._categories[category].append(name)
        
        logger.debug(f"Registered tool: {name} ({category}, risk={risk_level})")
    
    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        """Get a tool by name"""
        return self._tools.get(name)
    
    def get_tools_by_category(self, category: str) -> List[ToolDefinition]:
        """Get all tools in a category"""
        tool_names = self._categories.get(category, [])
        return [self._tools[name] for name in tool_names if name in self._tools]
    
    def get_all_tools(self) -> List[ToolDefinition]:
        """Get all registered tools"""
        return list(self._tools.values())
    
    def get_categories(self) -> List[str]:
        """Get all categories"""
        return list(self._categories.keys())
    
    def is_available(self, name: str) -> bool:
        """Check if a tool is available (installed, configured, etc.)"""
        tool = self.get_tool(name)
        if not tool:
            return False
        
        # Check if check_fn exists and passes
        if tool.check_fn:
            try:
                return tool.check_fn()
            except Exception as e:
                logger.debug(f"Tool '{name}' check failed: {e}")
                return False
        
        return True
    
    def execute(self, name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a tool by name.
        
        Returns:
            {
                "success": bool,
                "data": Any,
                "error": Optional[str],
                "tool": str,
                "risk_level": str
            }
        """
        tool = self.get_tool(name)
        if not tool:
            return {
                "success": False,
                "error": f"Tool '{name}' not found",
                "tool": name,
            }
        
        # Check if requires approval
        if tool.requires_approval:
            logger.warning(f"Tool '{name}' requires approval before execution")
            # In production, this would check an approval system
            # For now, just log it
        
        # Check if available
        if not self.is_available(name):
            return {
                "success": False,
                "error": f"Tool '{name}' not available (check requirements)",
                "tool": name,
                "required_env": tool.requires_env,
            }
        
        # Execute
        try:
            result = tool.handler(params)
            return {
                "success": True,
                "data": result,
                "tool": name,
                "risk_level": tool.risk_level,
            }
        except Exception as e:
            logger.error(f"Tool '{name}' execution failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "tool": name,
                "risk_level": tool.risk_level,
            }
    
    def get_stats(self) -> Dict[str, Any]:
        """Get registry statistics"""
        return {
            "total_tools": len(self._tools),
            "categories": {
                cat: len(tools) for cat, tools in self._categories.items()
            },
            "by_risk_level": {
                "low": len([t for t in self._tools.values() if t.risk_level == "low"]),
                "medium": len([t for t in self._tools.values() if t.risk_level == "medium"]),
                "high": len([t for t in self._tools.values() if t.risk_level == "high"]),
            },
            "requires_approval": len([t for t in self._tools.values() if t.requires_approval]),
        }


# Global registry instance
registry = ToolRegistry()
