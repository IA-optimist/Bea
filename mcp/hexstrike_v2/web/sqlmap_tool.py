"""Sqlmap Tool — Web category (SQL injection detection and exploitation)."""
from __future__ import annotations

import logging
import shutil
from typing import Any, Dict

from ..registry import registry
from ..core.executor import execute_command

logger = logging.getLogger(__name__)


def check_sqlmap_installed() -> bool:
    return shutil.which("sqlmap") is not None


def sqlmap_handler(params: Dict[str, Any]) -> Dict[str, Any]:
    target = params.get("target")
    if not target:
        raise ValueError("Missing required parameter: target")

    options = params.get("options", "")
    level = params.get("level", "1")
    # sqlmap requires -u for URL; --batch for non-interactive mode
    command = f"sqlmap -u {target} --level {level} --batch {options}".strip()

    result = execute_command(command, timeout=600)
    if not result.success:
        raise RuntimeError(f"sqlmap failed: {result.stderr or result.error}")
    return {"target": target, "output": result.stdout, "duration_seconds": result.duration_seconds}


registry.register(
    name="sqlmap",
    category="web",
    description="Automatic SQL injection detection and exploitation",
    handler=sqlmap_handler,
    parameters={
        "target": {"type": "string", "required": True, "description": "Target URL with injectable parameter (e.g. http://site.com/page?id=1)"},
        "level": {"type": "string", "required": False, "description": "Test depth 1-5 (default: 1)"},
        "options": {"type": "string", "required": False, "description": "Extra sqlmap flags (e.g. --dbs --dump)"},
    },
    risk_level="high",
    requires_approval=True,
    check_fn=check_sqlmap_installed,
    tags=["web", "sqlmap", "sqli"],
)

logger.info("sqlmap tool registered")
