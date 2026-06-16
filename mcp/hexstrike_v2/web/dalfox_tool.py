"""Dalfox Tool — Web category (XSS scanner)."""
from __future__ import annotations

import logging
import shutil
from typing import Any, Dict

from ..registry import registry
from ..core.executor import execute_command

logger = logging.getLogger(__name__)


def check_dalfox_installed() -> bool:
    return shutil.which("dalfox") is not None


def dalfox_handler(params: Dict[str, Any]) -> Dict[str, Any]:
    target = params.get("target")
    if not target:
        raise ValueError("Missing required parameter: target")

    options = params.get("options", "")
    # dalfox: 'url' subcommand + target URL
    command = f"dalfox url {target} {options}".strip()

    result = execute_command(command, timeout=300)
    if not result.success:
        raise RuntimeError(f"dalfox failed: {result.stderr or result.error}")
    return {"target": target, "output": result.stdout, "duration_seconds": result.duration_seconds}


registry.register(
    name="dalfox",
    category="web",
    description="Fast XSS scanner with parameter analysis",
    handler=dalfox_handler,
    parameters={
        "target": {"type": "string", "required": True, "description": "Target URL with parameters"},
        "options": {"type": "string", "required": False, "description": "Extra dalfox flags (e.g. --skip-bav --timeout 10)"},
    },
    risk_level="medium",
    requires_approval=True,
    check_fn=check_dalfox_installed,
    tags=["web", "dalfox", "xss"],
)

logger.info("dalfox tool registered")
