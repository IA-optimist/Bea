"""Waybackurls Tool — Web category (Wayback Machine URL harvester)."""
from __future__ import annotations

import logging
import shutil
from typing import Any, Dict

from ..registry import registry
from ..core.executor import execute_command

logger = logging.getLogger(__name__)


def check_waybackurls_installed() -> bool:
    return shutil.which("waybackurls") is not None


def waybackurls_handler(params: Dict[str, Any]) -> Dict[str, Any]:
    target = params.get("target")
    if not target:
        raise ValueError("Missing required parameter: target")

    options = params.get("options", "")
    # waybackurls accepts domain as positional argument
    command = f"waybackurls {target} {options}".strip()

    result = execute_command(command, timeout=120)
    if not result.success:
        raise RuntimeError(f"waybackurls failed: {result.stderr or result.error}")
    return {"target": target, "output": result.stdout, "duration_seconds": result.duration_seconds}


registry.register(
    name="waybackurls",
    category="web",
    description="Fetch all URLs that Wayback Machine knows about for a domain",
    handler=waybackurls_handler,
    parameters={
        "target": {"type": "string", "required": True, "description": "Domain name (e.g. example.com)"},
        "options": {"type": "string", "required": False, "description": "Extra waybackurls flags"},
    },
    risk_level="low",
    requires_approval=False,
    check_fn=check_waybackurls_installed,
    tags=["web", "waybackurls", "recon", "osint"],
)

logger.info("waybackurls tool registered")
