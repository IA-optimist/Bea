"""Dnsenum Tool — Recon category (DNS enumeration)."""
from __future__ import annotations

import logging
import shutil
from typing import Any, Dict

from ..registry import registry
from ..core.executor import execute_command

logger = logging.getLogger(__name__)


def check_dnsenum_installed() -> bool:
    return shutil.which("dnsenum") is not None


def dnsenum_handler(params: Dict[str, Any]) -> Dict[str, Any]:
    target = params.get("target")
    if not target:
        raise ValueError("Missing required parameter: target")

    options = params.get("options", "")
    # dnsenum: target (domain) comes first, then options
    command = f"dnsenum {target} {options}".strip()

    result = execute_command(command, timeout=300)
    if not result.success:
        raise RuntimeError(f"dnsenum failed: {result.stderr or result.error}")
    return {"target": target, "output": result.stdout, "duration_seconds": result.duration_seconds}


registry.register(
    name="dnsenum",
    category="recon",
    description="DNS enumeration: subdomains, MX, NS, zone transfer attempts",
    handler=dnsenum_handler,
    parameters={
        "target": {"type": "string", "required": True, "description": "Domain to enumerate"},
        "options": {"type": "string", "required": False, "description": "Extra dnsenum flags"},
    },
    risk_level="medium",
    requires_approval=True,
    check_fn=check_dnsenum_installed,
    tags=["recon", "dnsenum", "dns"],
)

logger.info("dnsenum tool registered")
