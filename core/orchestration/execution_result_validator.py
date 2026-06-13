"""Execution result metadata finalizer.

Extracted from ExecutionMixin._execute_supervised — post-execution phase.
Stores execution context into ctx.metadata for post-processing helpers
(meta_orchestrator outcome handling, learning, skill store, etc.).
"""
from __future__ import annotations

from typing import Any


def finalize_execution_metadata(
    ctx,
    enriched_goal: str,
    risk: str,
    delegate: Any,
    mission_timeout: int,
    needs_approval: bool,
) -> None:
    """Store execution context in ctx.metadata for downstream processing."""
    ctx.metadata["_exec_enriched_goal"] = enriched_goal
    ctx.metadata["_exec_risk"] = risk
    ctx.metadata["_exec_delegate"] = delegate
    ctx.metadata["_exec_mission_timeout"] = mission_timeout
    ctx.metadata["_exec_needs_approval"] = needs_approval
