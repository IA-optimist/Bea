"""Nikto Tool — Scanning category (web server vulnerability scanner)."""
from __future__ import annotations

import logging
import shutil
from typing import Any, Dict

from ..registry import registry
from ..core.executor import execute_command

logger = logging.getLogger(__name__)


def check_nikto_installed() -> bool:
    return shutil.which("nikto") is not None


def nikto_handler(params: Dict[str, Any]) -> Dict[str, Any]:
    target = params.get("target")
    if not target:
        raise ValueError("Missing required parameter: target")

    options = params.get("options", "")
    # nikto requires -h flag for target host
    command = f"nikto -h {target} {options}".strip()

    result = execute_command(command, timeout=600)
    if not result.success:
        raise RuntimeError(f"nikto failed: {result.stderr or result.error}")
    return {"target": target, "output": result.stdout, "duration_seconds": result.duration_seconds}


registry.register(
    name="nikto",
    category="scanning",
    description="Web server scanner: checks for dangerous files, outdated versions, misconfigs",
    handler=nikto_handler,
    parameters={
        "target": {"type": "string", "required": True, "description": "Target URL or IP (e.g. https://example.com)"},
        "options": {"type": "string", "required": False, "description": "Extra nikto flags (e.g. -Tuning x)"},
    },
    risk_level="medium",
    requires_approval=True,
    check_fn=check_nikto_installed,
    tags=["scanning", "nikto", "web"],
)

logger.info("nikto tool registered")
