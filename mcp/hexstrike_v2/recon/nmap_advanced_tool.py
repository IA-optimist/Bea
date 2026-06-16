"""Nmap Advanced Tool — Recon category (full service/OS/script scan)."""
from __future__ import annotations

import logging
import shutil
from typing import Any, Dict

from ..registry import registry
from ..core.executor import execute_command

logger = logging.getLogger(__name__)


def check_nmap_advanced_installed() -> bool:
    return shutil.which("nmap") is not None


def nmap_advanced_handler(params: Dict[str, Any]) -> Dict[str, Any]:
    target = params.get("target")
    if not target:
        raise ValueError("Missing required parameter: target")

    options = params.get("options", "")
    # Full aggressive scan: service version + OS detection + default scripts
    command = f"nmap -sV -sC -O -A {options} {target}".strip()

    result = execute_command(command, timeout=600)
    if not result.success:
        raise RuntimeError(f"nmap (advanced) failed: {result.stderr or result.error}")
    return {"target": target, "output": result.stdout, "duration_seconds": result.duration_seconds}


registry.register(
    name="nmap_advanced",
    category="recon",
    description="Full Nmap scan: service versions, OS detection, default scripts (-sV -sC -O -A)",
    handler=nmap_advanced_handler,
    parameters={
        "target": {"type": "string", "required": True, "description": "Target IP/hostname/CIDR"},
        "options": {"type": "string", "required": False, "description": "Extra nmap flags"},
    },
    risk_level="medium",
    requires_approval=True,
    check_fn=check_nmap_advanced_installed,
    tags=["recon", "nmap", "advanced"],
)

logger.info("nmap_advanced tool registered")
