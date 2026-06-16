"""Nuclei Tool — Scanning category (template-based vulnerability scanner)."""
from __future__ import annotations

import logging
import shutil
from typing import Any, Dict

from ..registry import registry
from ..core.executor import execute_command

logger = logging.getLogger(__name__)


def check_nuclei_installed() -> bool:
    return shutil.which("nuclei") is not None


def nuclei_handler(params: Dict[str, Any]) -> Dict[str, Any]:
    target = params.get("target")
    if not target:
        raise ValueError("Missing required parameter: target")

    options = params.get("options", "")
    severity = params.get("severity", "")
    # nuclei requires -u for URL target
    sev_flag = f"-severity {severity}" if severity else ""
    command = f"nuclei -u {target} {sev_flag} {options}".strip()

    result = execute_command(command, timeout=600)
    if not result.success:
        raise RuntimeError(f"nuclei failed: {result.stderr or result.error}")
    return {"target": target, "output": result.stdout, "duration_seconds": result.duration_seconds}


registry.register(
    name="nuclei",
    category="scanning",
    description="Template-based vulnerability scanner with community templates",
    handler=nuclei_handler,
    parameters={
        "target": {"type": "string", "required": True, "description": "Target URL"},
        "severity": {"type": "string", "required": False, "description": "Filter by severity: critical,high,medium,low"},
        "options": {"type": "string", "required": False, "description": "Extra nuclei flags (e.g. -t cves/)"},
    },
    risk_level="medium",
    requires_approval=True,
    check_fn=check_nuclei_installed,
    tags=["scanning", "nuclei", "templates"],
)

logger.info("nuclei tool registered")
