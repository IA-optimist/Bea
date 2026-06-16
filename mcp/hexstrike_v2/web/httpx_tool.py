"""Httpx Tool — Web category (HTTP probing and fingerprinting)."""
from __future__ import annotations

import logging
import shutil
from typing import Any, Dict

from ..registry import registry
from ..core.executor import execute_command

logger = logging.getLogger(__name__)


def check_httpx_installed() -> bool:
    # httpx (Go tool from projectdiscovery) — not to confuse with Python httpx lib
    return shutil.which("httpx") is not None


def httpx_handler(params: Dict[str, Any]) -> Dict[str, Any]:
    target = params.get("target")
    if not target:
        raise ValueError("Missing required parameter: target")

    options = params.get("options", "")
    # httpx: -u for single URL; common flags for status/title/tech
    command = f"httpx -u {target} -status-code -title -tech-detect {options}".strip()

    result = execute_command(command, timeout=120)
    if not result.success:
        raise RuntimeError(f"httpx failed: {result.stderr or result.error}")
    return {"target": target, "output": result.stdout, "duration_seconds": result.duration_seconds}


registry.register(
    name="httpx",
    category="web",
    description="Fast HTTP probing: status codes, titles, tech detection, redirects",
    handler=httpx_handler,
    parameters={
        "target": {"type": "string", "required": True, "description": "Target URL or domain"},
        "options": {"type": "string", "required": False, "description": "Extra httpx flags (e.g. -follow-redirects -json)"},
    },
    risk_level="low",
    requires_approval=False,
    check_fn=check_httpx_installed,
    tags=["web", "httpx", "probing"],
)

logger.info("httpx tool registered")
