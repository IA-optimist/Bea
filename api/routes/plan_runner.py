"""
api/routes/plan_runner.py — Plan execution API.

Two route prefixes:
  /api/v3/plans/{plan_id}/...  — plan-scoped operations (canonical)
  /api/v3/runs/...             — run-scoped operations (direct run access)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api._deps import require_auth

router = APIRouter(tags=["plan-runner"])

# ── Plan-scoped routes (canonical) ────────────────────────────


@router.post("/api/v3/plans/{plan_id}/run")
async def plan_run(plan_id: str, _user: dict = Depends(require_auth)):
    """Start executing a validated/approved plan."""
    from core.planning.plan_runner import get_plan_runner
    run = get_plan_runner().start(plan_id)
    ok = run.status.value != "failed" or run.steps_completed > 0
    return {"ok": ok, "data": run.to_dict()}


@router.post("/api/v3/plans/{plan_id}/pause")
async def plan_pause(plan_id: str, _user: dict = Depends(require_auth)):
    """Pause the active run for this plan."""
    from core.planning.run_state import get_run_store
    for run_data in get_run_store().list_active():
        if run_data.get("plan_id") == plan_id:
            from core.planning.plan_runner import get_plan_runner
            get_plan_runner().pause(run_data["run_id"])
            return {"ok": True, "message": "Pause requested", "run_id": run_data["run_id"]}
    raise HTTPException(404, "No active run for this plan")


@router.post("/api/v3/plans/{plan_id}/resume")
async def plan_resume(plan_id: str, _user: dict = Depends(require_auth)):
    """Resume the paused/awaiting run for this plan."""
    from core.planning.run_state import get_run_store
    for run_data in get_run_store().list_all():
        if run_data.get("plan_id") == plan_id and run_data.get("status") in ("paused", "awaiting_approval"):
            from core.planning.plan_runner import get_plan_runner
            run = get_plan_runner().resume(run_data["run_id"])
            return {"ok": True, "data": run.to_dict()}
    raise HTTPException(404, "No resumable run for this plan")


# NOTE: POST /api/v3/plans/{plan_id}/cancel is handled by operational_tools_router
# (mounted first at line ~395 in main.py). That version cancels the plan entity.
# This run-cancellation logic is preserved below as /api/v3/plans/{plan_id}/runs/cancel
# if needed. For now, route removed to avoid silent duplicate.

@router.get("/api/v3/plans/{plan_id}/runs")
async def plan_runs(plan_id: str, _user: dict = Depends(require_auth)):
    """List all runs for a specific plan."""
    from core.planning.run_state import get_run_store
    runs = [r for r in get_run_store().list_all() if r.get("plan_id") == plan_id]
    return {"ok": True, "data": runs}


# ── Run-scoped routes ─────────────────────────────────────────


@router.post("/api/v3/runs/start/{plan_id}")
async def start_run(plan_id: str, _user: dict = Depends(require_auth)):
    """Start executing a validated/approved plan (alias for /plans/{id}/run)."""
    from core.planning.plan_runner import get_plan_runner
    run = get_plan_runner().start(plan_id)
    return {"ok": run.status.value != "failed" or run.steps_completed > 0,
            "data": run.to_dict()}


@router.post("/api/v3/runs/resume/{run_id}")
async def resume_run(run_id: str, _user: dict = Depends(require_auth)):
    """Resume a paused or approval-waiting run."""
    from core.planning.plan_runner import get_plan_runner
    run = get_plan_runner().resume(run_id)
    return {"ok": run.status.value != "failed" or run.steps_completed > 0,
            "data": run.to_dict()}


@router.post("/api/v3/runs/pause/{run_id}")
async def pause_run(run_id: str, _user: dict = Depends(require_auth)):
    """Request pause at next step boundary."""
    from core.planning.plan_runner import get_plan_runner
    ok = get_plan_runner().pause(run_id)
    return {"ok": ok, "message": "Pause requested"}


@router.post("/api/v3/runs/cancel/{run_id}")
async def cancel_run(run_id: str, _user: dict = Depends(require_auth)):
    """Cancel a running or paused run."""
    from core.planning.plan_runner import get_plan_runner
    run = get_plan_runner().cancel(run_id)
    if not run:
        raise HTTPException(404, f"Run not found: {run_id}")
    return {"ok": True, "data": run.to_dict()}


class ApproveStepRequest(BaseModel):
    step_id: str
    reason: str = ""


@router.post("/api/v3/runs/approve-step/{run_id}")
async def approve_step(
    run_id: str, req: ApproveStepRequest, _user: dict = Depends(require_auth)
):
    """Approve a specific step in a paused run."""
    from core.planning.plan_runner import get_plan_runner
    ok = get_plan_runner().approve_step(run_id, req.step_id, req.reason)
    if not ok:
        raise HTTPException(404, "Run not found")
    return {"ok": True, "message": f"Step {req.step_id} approved"}


@router.get("/api/v3/plans/runs/{run_id}")
async def get_run_by_plan_path(run_id: str, _user: dict = Depends(require_auth)):
    """Get run status and details (plan-scoped path)."""
    from core.planning.plan_runner import get_plan_runner
    run = get_plan_runner().get_run(run_id)
    if not run:
        raise HTTPException(404, f"Run not found: {run_id}")
    return {"ok": True, "data": run.to_dict()}


@router.get("/api/v3/plans/runs/{run_id}/context")
async def get_run_context(run_id: str, _user: dict = Depends(require_auth)):
    """Get execution context for a run (step outputs, approvals, metadata)."""
    from core.planning.plan_runner import get_plan_runner
    run = get_plan_runner().get_run(run_id)
    if not run:
        raise HTTPException(404, f"Run not found: {run_id}")
    return {"ok": True, "data": run.context.to_dict()}


@router.get("/api/v3/plans/runs/{run_id}/artifacts")
async def get_run_artifacts(run_id: str, _user: dict = Depends(require_auth)):
    """Get artifacts produced by a run."""
    from core.planning.plan_runner import get_plan_runner
    run = get_plan_runner().get_run(run_id)
    if not run:
        raise HTTPException(404, f"Run not found: {run_id}")
    return {
        "ok": True,
        "data": {
            "run_id": run_id,
            "artifacts": run.context.artifacts,
            "step_outputs": {
                sid: {k: str(v)[:200] for k, v in out.items()}
                for sid, out in run.context.step_outputs.items()
            },
        },
    }


@router.get("/api/v3/runs/{run_id}")
async def get_run(run_id: str, _user: dict = Depends(require_auth)):
    """Get run status and details."""
    from core.planning.plan_runner import get_plan_runner
    run = get_plan_runner().get_run(run_id)
    if not run:
        raise HTTPException(404, f"Run not found: {run_id}")
    return {"ok": True, "data": run.to_dict()}


@router.get("/api/v3/runs/{run_id}/skill-outputs")
async def get_skill_outputs(run_id: str, _user: dict = Depends(require_auth)):
    """
    Get structured skill outputs from a run.

    Returns LLM-generated content when available, with metadata:
    - invoked: whether LLM was called
    - content: structured analysis (JSON fields from skill schema)
    - quality: validation score and details
    - model: which model produced the output
    - duration_ms: LLM call duration

    Content is returned in full (not truncated) for productive skills.
    """
    from core.planning.plan_runner import get_plan_runner
    run = get_plan_runner().get_run(run_id)
    if not run:
        raise HTTPException(404, f"Run not found: {run_id}")

    skill_outputs = {}
    for step_id, output in run.context.step_outputs.items():
        skill_id = output.get("skill_id", "")
        if not skill_id:
            continue  # Not a skill step

        invoked = output.get("invoked", False)
        entry = {
            "step_id": step_id,
            "skill_id": skill_id,
            "invoked": invoked,
        }
        if invoked and "content" in output:
            content = output["content"]
            entry["content"] = content
            entry["content_fields"] = list(content.keys()) if isinstance(content, dict) else []
            entry["content_summary"] = {
                k: type(v).__name__ + (f"[{len(v)}]" if isinstance(v, (list, dict)) else "")
                for k, v in content.items()
            } if isinstance(content, dict) else {}
            entry["quality"] = output.get("quality", {})
            entry["model"] = output.get("model", "")
            entry["duration_ms"] = output.get("duration_ms", 0)
            entry["raw_length"] = output.get("raw_length", 0)
        else:
            entry["prepared"] = output.get("prepared", False)
            entry["prompt_context_length"] = output.get("prompt_context_length", 0)
            if output.get("llm_error"):
                entry["llm_error"] = output["llm_error"]

        skill_outputs[step_id] = entry

    return {
        "ok": True,
        "data": {
            "run_id": run_id,
            "status": run.status.value,
            "skill_count": len(skill_outputs),
            "productive_count": sum(1 for s in skill_outputs.values() if s.get("invoked")),
            "skills": skill_outputs,
        },
    }


@router.get("/api/v3/runs")
async def list_runs(_user: dict = Depends(require_auth)):
    """List all runs."""
    from core.planning.run_state import get_run_store
    return {"ok": True, "data": get_run_store().list_all()}


@router.get("/api/v3/runs/filter/active")
async def active_runs(_user: dict = Depends(require_auth)):
    """List active (running/paused/awaiting) runs."""
    from core.planning.run_state import get_run_store
    return {"ok": True, "data": get_run_store().list_active()}
