"""Ffuf Tool — Web category (fast web fuzzer for content discovery)."""
from __future__ import annotations

import logging
import shutil
from typing import Any, Dict

from ..registry import registry
from ..core.executor import execute_command

logger = logging.getLogger(__name__)

DEFAULT_WORDLIST = "/usr/share/wordlists/dirb/common.txt"


def check_ffuf_installed() -> bool:
    return shutil.which("ffuf") is not None


def ffuf_handler(params: Dict[str, Any]) -> Dict[str, Any]:
    target = params.get("target")
    if not target:
        raise ValueError("Missing required parameter: target")

    options = params.get("options", "")
    wordlist = params.get("wordlist", DEFAULT_WORDLIST)
    # ffuf: -u for URL (with FUZZ keyword), -w for wordlist
    # If target doesn't contain FUZZ, append /FUZZ for directory discovery
    url = target if "FUZZ" in target else f"{target.rstrip('/')}/FUZZ"
    command = f"ffuf -u {url} -w {wordlist} {options}".strip()

    result = execute_command(command, timeout=300)
    if not result.success:
        raise RuntimeError(f"ffuf failed: {result.stderr or result.error}")
    return {"target": target, "output": result.stdout, "duration_seconds": result.duration_seconds}


registry.register(
    name="ffuf",
    category="web",
    description="Fast web fuzzer for directory/file/parameter discovery",
    handler=ffuf_handler,
    parameters={
        "target": {"type": "string", "required": True, "description": "Base URL (FUZZ keyword auto-appended if missing)"},
        "wordlist": {"type": "string", "required": False, "description": "Path to wordlist (default: dirb/common.txt)"},
        "options": {"type": "string", "required": False, "description": "Extra ffuf flags (e.g. -e .php,.html -mc 200)"},
    },
    risk_level="medium",
    requires_approval=True,
    check_fn=check_ffuf_installed,
    tags=["web", "ffuf", "fuzzing", "discovery"],
)

logger.info("ffuf tool registered")
