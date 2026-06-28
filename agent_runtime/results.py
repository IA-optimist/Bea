"""
agent_runtime/results.py — Result helpers and stub handler.
"""
from __future__ import annotations

from agent_runtime.actions import ActionRequest, ActionResult


def not_implemented_handler(request: ActionRequest) -> ActionResult:
    """Stub handler for actions registered but not yet wired to a real backend."""
    return ActionResult.error_result(
        request.action_id,
        f"action '{request.action_type.value}' handler not implemented — wire a real backend",
    )
