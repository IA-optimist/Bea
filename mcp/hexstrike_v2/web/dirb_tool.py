"""Dirb Tool — Web category (web content scanner)."""
from __future__ import annotations

import logging
import shutil
from typing import Any, Dict

from ..registry import registry
from ..core.executor import execute_command

logger = logging.getLogger(__name__)


def check_dirb_installed() -> bool:
    return shutil.which("dirb") is not None


def dirb_handler(params: Dict[str, Any]) -> Dict[str, Any]:
    target = params.get("target")
    if not target:
        raise ValueError("Missing required parameter: target")

    options = params.get("options", "")
    wordlist = params.get("wordlist", "")
    wl_arg = f" {wordlist}" if wordlist else ""
    # dirb: URL target first, optional wordlist, then options
    command = f"dirb {target}{wl_arg} {options}".strip()

    result = execute_command(command, timeout=300)
    if not result.success:
        raise RuntimeError(f"dirb failed: {result.stderr or result.error}")
    return {"target": target, "output": result.stdout, "duration_seconds": result.duration_seconds}


registry.register(
    name="dirb",
    category="web",
    description="Web content scanner using dictionary-based attacks",
    handler=dirb_handler,
    parameters={
        "target": {"type": "string", "required": True, "description": "Target URL"},
        "wordlist": {"type": "string", "required": False, "description": "Custom wordlist path (uses built-in if omitted)"},
        "options": {"type": "string", "required": False, "description": "Extra dirb flags (e.g. -r -z 100)"},
    },
    risk_level="medium",
    requires_approval=True,
    check_fn=check_dirb_installed,
    tags=["web", "dirb", "discovery"],
)

logger.info("dirb tool registered")
