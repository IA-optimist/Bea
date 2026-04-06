"""
Dirb Tool — Web category

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


def check_dirb_installed() -> bool:
    """Check if dirb is installed"""
    # TODO: Implement proper check
    return shutil.which("dirb") is not None


def dirb_handler(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute dirb.
    
    TODO: Extract implementation from hexstrike_server.py::dirb()
    
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
    command = f"dirb {options} {target}"
    
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
    name="dirb",
    category="web",
    description="Dirb tool",
    handler=dirb_handler,
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
    check_fn=check_dirb_installed,
    tags=["web", "dirb"],
)

logger.info("dirb tool registered")
