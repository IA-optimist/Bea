"""
Httpx Tool — Web category

Auto-extracted from hexstrike_server.py
TODO: Review and enhance implementation
"""
from __future__ import annotations

import logging
import shutil
from typing import Any, Dict

from ..registry import registry
from ..core.executor import execute_command

logger = logging.getLogger(__name__)


def check_httpx_installed() -> bool:
    """Check if httpx is installed"""
    # TODO: Implement proper check
    return shutil.which("httpx") is not None


def httpx_handler(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute httpx.
    
    TODO: Extract implementation from hexstrike_server.py::httpx()
    
    Args:
        params: Tool parameters
            - target (str): Target to scan
            - options (str): Additional options
    
    Returns:
        Result dictionary
    """
    target = params.get("target")
    if not target:
        raise ValueError("Missing required parameter: target")
    
    options = params.get("options", "")
    
    # TODO: Build proper command
    command = f"httpx {options} {target}"
    
    # Execute
    result = execute_command(command, timeout=300)
    
    if not result.success:
        raise RuntimeError(f"{tool_name} failed: {result.stderr or result.error}")
    
    return {
        "target": target,
        "output": result.stdout,
        "duration_seconds": result.duration_seconds,
    }


# Register the tool
registry.register(
    name="httpx",
    category="web",
    description="Httpx tool",
    handler=httpx_handler,
    parameters={
        "target": {
            "type": "string",
            "required": True,
            "description": "Target to scan"
        },
        "options": {
            "type": "string",
            "required": False,
            "description": "Additional options"
        },
    },
    risk_level="medium",
    requires_approval=True,
    check_fn=check_httpx_installed,
    tags=["web", "httpx"],
)

logger.info("httpx tool registered")
