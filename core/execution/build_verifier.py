"""
core/execution/build_verifier.py — Build output verification.

Extracted from build_pipeline.py to isolate validation logic.
Public API: verify_build(build_dir, requirements) -> (passed, failed)
"""
from __future__ import annotations

import json
from pathlib import Path
from core.execution.artifacts import ValidationRequirement


def verify_build(
    build_dir: Path,
    requirements: list[ValidationRequirement],
) -> tuple[list[str], list[str]]:
    """
    Run validation checks on build output.

    Returns (passed_names, failed_names).
    Check types: exists | content | schema | manual
    """
    passed: list[str] = []
    failed: list[str] = []

    for req in requirements:
        try:
            if req.check_type == "exists":
                target = build_dir / req.target
                if target.exists() and target.stat().st_size > 0:
                    passed.append(req.name)
                else:
                    failed.append(req.name)

            elif req.check_type == "content":
                target = build_dir / req.target
                if target.exists():
                    content = target.read_text(encoding="utf-8")
                    if len(content.strip()) > 10:
                        passed.append(req.name)
                    else:
                        failed.append(req.name)
                else:
                    failed.append(req.name)

            elif req.check_type == "schema":
                target = build_dir / req.target
                if target.exists():
                    try:
                        json.loads(target.read_text(encoding="utf-8"))
                        passed.append(req.name)
                    except json.JSONDecodeError:
                        failed.append(req.name)
                else:
                    failed.append(req.name)

            elif req.check_type == "manual":
                passed.append(req.name)

            else:
                passed.append(req.name)

        except Exception:
            failed.append(req.name)

    return passed, failed
