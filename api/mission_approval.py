"""Approval helpers for task and mission routes."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import HTTPException


def approve_task_payload(task_id: str) -> dict[str, Any]:
    """Approve a pending action/task and return the API payload."""
    try:
        from core.action_queue import get_action_queue

        action_queue = get_action_queue()
        action = action_queue.approve(task_id, note="Approved via API")
        if action is None:
            raise HTTPException(
                status_code=404,
                detail=f"Task '{task_id}' not found or not pending.",
            )
        return {"ok": True, "data": action.to_dict()}
    except HTTPException:
        raise
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def reject_task_payload(task_id: str, note: str) -> dict[str, Any]:
    """Reject a pending action/task and return the API payload."""
    try:
        from core.action_queue import get_action_queue

        action_queue = get_action_queue()
        action = action_queue.reject(task_id, note=note)
        if action is None:
            raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")
        return {"ok": True, "data": action.to_dict()}
    except HTTPException:
        raise
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def approve_mission_for_resume(
    *,
    mission_id: str,
    note: str,
    mission_system: Any,
    background_tasks: Any,
    get_orchestrator: Callable[[], Any],
    logger: Any,
    silent_logger: Any,
) -> dict[str, Any]:
    """Approve a pending mission and schedule its forced-approved resumption."""
    record = mission_system.approve(mission_id, note=note)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Mission '{mission_id}' not found.")
    if record.status not in ("APPROVED", "PENDING_VALIDATION"):
        return {"ok": False, "error": f"Mission is in status '{record.status}', cannot approve."}

    try:
        from core.orchestration_bridge import get_orchestration_bridge

        get_orchestration_bridge().approve_mission(mission_id, note=note)
    except Exception as exc:
        logger.debug("bridge_approve_skipped", err=str(exc)[:60])

    try:
        from core.meta_orchestrator import get_meta_orchestrator

        orchestrator = get_meta_orchestrator()
        context = orchestrator._missions.get(mission_id)
        if context:
            item_id = context.metadata.get("approval_item_id", "")
            if item_id:
                from core.approval_queue import approve as approve_queue_item

                approve_queue_item(item_id, approved_by="human")
    except Exception as exc:
        logger.debug("approval_queue_approve_skipped", err=str(exc)[:60])

    original_goal = record.user_input or record.decision_trace.get("original_goal", "")
    if not original_goal:
        return {"ok": False, "error": "Cannot resume: original goal not found."}

    async def _resume_mission() -> None:
        try:
            orchestrator = get_orchestrator()
            session = await orchestrator.run_mission(
                goal=original_goal,
                mode="auto",
                mission_id=mission_id,
                force_approved=True,
            )
            final = getattr(session, "result", "") or getattr(session, "final_report", "") or ""
            if final:
                mission_system.set_final_output(mission_id, final)
                mission_system.complete(mission_id, result_text=final)
            else:
                mission_system.complete(mission_id, result_text="Mission approved and executed.")
            logger.info("mission_resumed_completed", mission_id=mission_id)
        except Exception as exc:
            logger.error("mission_resume_failed", mission_id=mission_id, err=str(exc)[:120])
            try:
                mission_system.complete(mission_id, result_text=f"Resumption error: {str(exc)[:200]}")
            except Exception:
                silent_logger.debug("suppressed_exception", src="mission_approval.py")

    background_tasks.add_task(_resume_mission)
    return {
        "ok": True,
        "data": {
            "mission_id": mission_id,
            "status": "resuming",
            "note": note,
        },
    }


def reject_mission_payload(
    *,
    mission_id: str,
    note: str,
    mission_system: Any,
    logger: Any,
    silent_logger: Any,
) -> dict[str, Any]:
    """Reject a pending mission and update bridge/approval queue state."""
    record = mission_system.reject(mission_id, note=note)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Mission '{mission_id}' not found.")

    try:
        from core.orchestration_bridge import get_orchestration_bridge

        get_orchestration_bridge().reject_mission(mission_id, note=note)
    except Exception as exc:
        logger.debug("bridge_reject_skipped", err=str(exc)[:60])

    try:
        from core.meta_orchestrator import get_meta_orchestrator

        context = get_meta_orchestrator()._missions.get(mission_id)
        if context:
            item_id = context.metadata.get("approval_item_id", "")
            if item_id:
                from core.approval_queue import reject as reject_queue_item

                reject_queue_item(item_id, rejected_by="human")
    except Exception:
        silent_logger.debug("suppressed_exception", src="mission_approval.py")

    mission_system.set_final_output(mission_id, f"Mission rejected: {note}")
    return {"ok": True, "data": {"mission_id": mission_id, "status": "rejected", "note": note}}