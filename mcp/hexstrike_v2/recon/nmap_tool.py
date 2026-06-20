"""
Nmap Tool — Recon category

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


def check_nmap_installed() -> bool:
    """Check if nmap is installed"""
    # TODO: Implement proper check
    return shutil.which("nmap") is not None


def nmap_handler(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute nmap.
    
    TODO: Extract implementation from hexstrike_server.py::nmap()
    
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
    command = f"nmap {options} {target}"

    # Execute
    result = execute_command(command, timeout=300)

    if not result.success:
        raise RuntimeError(f"nmap failed: {result.stderr or result.error}")

    return {
        "target": target,
        "output": result.stdout,
        "duration_seconds": result.duration_seconds,
    }


# Register the tool
registry.register(
    name="nmap",
    category="recon",
    description="Nmap tool",
    handler=nmap_handler,
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
    check_fn=check_nmap_installed,
    tags=["recon", "nmap"],
)

logger.info("nmap tool registered")
