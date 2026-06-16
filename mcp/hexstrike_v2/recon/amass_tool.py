"""
Amass Tool — Recon category

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


def check_amass_installed() -> bool:
    return shutil.which("amass") is not None


def amass_handler(params: Dict[str, Any]) -> Dict[str, Any]:
    target = params.get("target")
    if not target:
        raise ValueError("Missing required parameter: target")

    options = params.get("options", "")
    command = f"amass enum -d {target} {options}".strip()
    
    result = execute_command(command, timeout=300)
    if not result.success:
        raise RuntimeError(f"amass failed: {result.stderr or result.error}")
    return {"target": target, "output": result.stdout, "duration_seconds": result.duration_seconds}


# Register the tool
registry.register(
    name="amass",
    category="recon",
    description="Amass tool",
    handler=amass_handler,
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
    check_fn=check_amass_installed,
    tags=["recon", "amass"],
)

logger.info("amass tool registered")
