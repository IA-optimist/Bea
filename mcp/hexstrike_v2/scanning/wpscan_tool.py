"""Wpscan Tool — Scanning category (WordPress vulnerability scanner)."""
from __future__ import annotations

import logging
import shutil
from typing import Any, Dict

from ..registry import registry
from ..core.executor import execute_command

logger = logging.getLogger(__name__)


def check_wpscan_installed() -> bool:
    return shutil.which("wpscan") is not None


def wpscan_handler(params: Dict[str, Any]) -> Dict[str, Any]:
    target = params.get("target")
    if not target:
        raise ValueError("Missing required parameter: target")

    options = params.get("options", "")
    enumerate = params.get("enumerate", "")
    enum_flag = f"--enumerate {enumerate}" if enumerate else ""
    # wpscan requires --url flag
    command = f"wpscan --url {target} {enum_flag} {options}".strip()

    result = execute_command(command, timeout=300)
    if not result.success:
        raise RuntimeError(f"wpscan failed: {result.stderr or result.error}")
    return {"target": target, "output": result.stdout, "duration_seconds": result.duration_seconds}


registry.register(
    name="wpscan",
    category="scanning",
    description="WordPress vulnerability scanner: plugins, themes, users, CVEs",
    handler=wpscan_handler,
    parameters={
        "target": {"type": "string", "required": True, "description": "WordPress site URL"},
        "enumerate": {"type": "string", "required": False, "description": "Enumerate: u (users), p (plugins), t (themes), vp (vulnerable plugins)"},
        "options": {"type": "string", "required": False, "description": "Extra wpscan flags"},
    },
    risk_level="medium",
    requires_approval=True,
    check_fn=check_wpscan_installed,
    tags=["scanning", "wpscan", "wordpress"],
)

logger.info("wpscan tool registered")
