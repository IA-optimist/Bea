"""Masscan Tool — Recon category (fast port scanner)."""
from __future__ import annotations

import logging
import shutil
from typing import Any, Dict

from ..registry import registry
from ..core.executor import execute_command

logger = logging.getLogger(__name__)


def check_masscan_installed() -> bool:
    return shutil.which("masscan") is not None


def masscan_handler(params: Dict[str, Any]) -> Dict[str, Any]:
    target = params.get("target")
    if not target:
        raise ValueError("Missing required parameter: target")

    options = params.get("options", "")
    ports = params.get("ports", "1-65535")
    # masscan: target IP/CIDR + port range (--rate cap at 1000 for safety)
    rate = params.get("rate", "1000")
    command = f"masscan {target} -p {ports} --rate {rate} {options}".strip()

    result = execute_command(command, timeout=600)
    if not result.success:
        raise RuntimeError(f"masscan failed: {result.stderr or result.error}")
    return {"target": target, "output": result.stdout, "duration_seconds": result.duration_seconds}


registry.register(
    name="masscan",
    category="recon",
    description="Fast port scanner — scans thousands of ports per second",
    handler=masscan_handler,
    parameters={
        "target": {"type": "string", "required": True, "description": "Target IP/CIDR"},
        "ports": {"type": "string", "required": False, "description": "Port range (default: 1-65535)"},
        "rate": {"type": "string", "required": False, "description": "Packets per second (default: 1000)"},
        "options": {"type": "string", "required": False, "description": "Extra masscan flags"},
    },
    risk_level="high",
    requires_approval=True,
    check_fn=check_masscan_installed,
    tags=["recon", "masscan", "portscan"],
)

logger.info("masscan tool registered")
