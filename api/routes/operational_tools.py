"""
api/routes/operational_tools.py — Operational tool & execution plan API.

Endpoints for tool registry, readiness, execution, plans, templates, history.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

from api._deps import require_auth
from api.auth_principal import get_authenticated_principal

router = APIRouter(tags=["operational-tools"])


# ── Tool Registry ─────────────────────────────────────────────

@router.get("/api/v3/tools")
async def list_tools(_user: dict = Depends(require_auth)):
    from core.tools_operational.tool_registry import get_tool_registry
    tools = get_tool_registry().list_all()
    return {"ok": True, "data": [t.to_dict() for t in tools]}


@router.get("/api/v3/tools/stats")
async def tool_stats(_user: dict = Depends(require_auth)):
    from core.tools_operational.tool_registry import get_tool_registry
    return {"ok": True, "data": get_tool_registry().stats()}


@router.get("/api/v3/tools/readiness")
async def all_readiness(_user: dict = Depends(require_auth)):
    from core.tools_operational.tool_readiness import check_all_readiness
    return {"ok": True, "data": check_all_readiness()}


@router.get("/api/v3/tools/{tool_id}")
async def get_tool(tool_id: str, _user: dict = Depends(require_auth)):
    from core.tools_operational.tool_registry import get_tool_registry
    tool = get_tool_registry().get(tool_id)
    if not tool:
        raise HTTPException(404, f"Tool not found: {tool_id}")
    return {"ok": True, "data": tool.to_dict()}


@router.get("/api/v3/tools/{tool_id}/readiness")
async def tool_readiness(tool_id: str, _user: dict = Depends(require_auth)):
    from core.tools_operational.tool_readiness import check_readiness
    return {"ok": True, "data": check_readiness(tool_id)}


class ToolExecRequest(BaseModel):
    inputs: dict = {}
    mission_id: str = ""
    simulate: bool = False
    approval_override: bool = False


@router.post("/api/v3/tools/{tool_id}/execute")
async def execute_tool(
    tool_id: str,
    req: ToolExecRequest,
    request: Request,
    _user: dict = Depends(require_auth),
):
    from core.tools_operational.tool_executor import get_tool_executor
    inputs = dict(req.inputs)
    # Inject validated principal. Any client-supplied `_bea_principal_id` or
    # `principal_id` is overwritten; public routes never trust user identity.
    principal_id = get_authenticated_principal(request)
    inputs["_bea_principal_id"] = principal_id or ""
    inputs.pop("principal_id", None)
    result = get_tool_executor().execute(
        tool_id=tool_id,
        inputs=inputs,
        mission_id=req.mission_id,
        simulate=req.simulate,
        approval_override=req.approval_override,
    )
    return {"ok": result.ok, "data": result.to_dict()}


@router.post("/api/v3/tools/{tool_id}/simulate")
async def simulate_tool(
    tool_id: str, req: ToolExecRequest, _user: dict = Depends(require_auth)
):
    from core.tools_operational.tool_executor import get_tool_executor
    result = get_tool_executor().simulate(tool_id, req.inputs)
    return {"ok": result.ok, "data": result.to_dict()}


# ── Execution Plans ───────────────────────────────────────────

@router.get("/api/v3/plans")
async def list_plans(
    status: Optional[str] = None, _user: dict = Depends(require_auth)
):
    from core.planning.plan_serializer import get_plan_store
    return {"ok": True, "data": get_plan_store().list_all(status=status)}


@router.get("/api/v3/plans/active")
async def active_plans(_user: dict = Depends(require_auth)):
    from core.planning.plan_serializer import get_plan_store
    return {"ok": True, "data": get_plan_store().list_active()}


@router.get("/api/v3/plans/stats")
async def plan_stats(_user: dict = Depends(require_auth)):
    from core.planning.plan_serializer import get_plan_store
    return {"ok": True, "data": get_plan_store().stats()}


@router.get("/api/v3/plans/{plan_id}")
async def get_plan(plan_id: str, _user: dict = Depends(require_auth)):
    from core.planning.plan_serializer import get_plan_store
    plan = get_plan_store().get(plan_id)
    if not plan:
        raise HTTPException(404, f"Plan not found: {plan_id}")
    return {"ok": True, "data": plan.to_dict()}


class PlanCreateRequest(BaseModel):
    goal: str
    steps: list[dict]
    description: str = ""
    mission_id: str = ""


@router.post("/api/v3/plans")
async def create_plan(req: PlanCreateRequest, _user: dict = Depends(require_auth)):
    from core.planning.execution_plan import ExecutionPlan, PlanStep
    from core.planning.plan_validator import validate_plan
    from core.planning.plan_serializer import get_plan_store

    steps = [PlanStep.from_dict(s) for s in req.steps]
    plan = ExecutionPlan(
        goal=req.goal,
        description=req.description,
        steps=steps,
        mission_id=req.mission_id,
    )
    plan.risk_score = plan.compute_risk()
    plan.requires_approval = plan.compute_approval_required()

    validation = validate_plan(plan)
    if not validation["valid"]:
        return {"ok": False, "errors": validation["errors"], "warnings": validation["warnings"]}

    if plan.requires_approval:
        plan.status = __import__("core.planning.execution_plan", fromlist=["PlanStatus"]).PlanStatus.AWAITING_APPROVAL
    else:
        plan.status = __import__("core.planning.execution_plan", fromlist=["PlanStatus"]).PlanStatus.VALIDATED

    get_plan_store().save(plan)
    return {"ok": True, "data": plan.to_dict(), "validation": validation}


@router.post("/api/v3/plans/{plan_id}/approve")
async def approve_plan(plan_id: str, _user: dict = Depends(require_auth)):
    from core.planning.plan_serializer import get_plan_store
    ok = get_plan_store().approve(plan_id, decided_by="operator")
    if not ok:
        raise HTTPException(400, "Plan not awaiting approval or not found")
    return {"ok": True, "plan_id": plan_id, "status": "approved"}


@router.post("/api/v3/plans/{plan_id}/cancel")
async def cancel_plan(plan_id: str, _user: dict = Depends(require_auth)):
    from core.planning.plan_serializer import get_plan_store
    ok = get_plan_store().cancel(plan_id)
    if not ok:
        raise HTTPException(400, "Plan not cancellable or not found")
    return {"ok": True, "plan_id": plan_id, "status": "cancelled"}


@router.post("/api/v3/plans/{plan_id}/validate")
async def validate_plan_endpoint(plan_id: str, _user: dict = Depends(require_auth)):
    from core.planning.plan_serializer import get_plan_store
    from core.planning.plan_validator import validate_plan
    plan = get_plan_store().get(plan_id)
    if not plan:
        raise HTTPException(404, f"Plan not found: {plan_id}")
    return {"ok": True, "data": validate_plan(plan)}


# ── Workflow Templates ────────────────────────────────────────

@router.get("/api/v3/templates")
async def list_templates(_user: dict = Depends(require_auth)):
    from core.planning.workflow_templates import load_templates
    return {"ok": True, "data": load_templates()}


@router.get("/api/v3/templates/{template_id}")
async def get_template(template_id: str, _user: dict = Depends(require_auth)):
    from core.planning.workflow_templates import get_template
    tmpl = get_template(template_id)
    if not tmpl:
        raise HTTPException(404, f"Template not found: {template_id}")
    return {"ok": True, "data": tmpl}


class TemplateInstantiateRequest(BaseModel):
    goal_override: str = ""
    inputs: dict = {}
    mission_id: str = ""


@router.post("/api/v3/templates/{template_id}/instantiate")
async def instantiate_template(
    template_id: str, req: TemplateInstantiateRequest,
    _user: dict = Depends(require_auth),
):
    from core.planning.workflow_templates import build_plan_from_template
    from core.planning.plan_validator import validate_plan
    from core.planning.plan_serializer import get_plan_store
    from core.planning.execution_plan import PlanStatus

    plan = build_plan_from_template(
        template_id, req.goal_override, req.inputs, req.mission_id
    )
    if not plan:
        raise HTTPException(404, f"Template not found: {template_id}")

    validation = validate_plan(plan)
    if plan.requires_approval:
        plan.status = PlanStatus.AWAITING_APPROVAL
    else:
        plan.status = PlanStatus.VALIDATED

    get_plan_store().save(plan)
    return {"ok": True, "data": plan.to_dict(), "validation": validation}


# ── Execution History ─────────────────────────────────────────

@router.get("/api/v3/execution-history")
async def execution_history(limit: int = 50, _user: dict = Depends(require_auth)):
    from core.planning.execution_memory import get_execution_memory
    return {"ok": True, "data": get_execution_memory().get_history(limit)}


@router.get("/api/v3/execution-history/stats")
async def execution_stats(_user: dict = Depends(require_auth)):
    from core.planning.execution_memory import get_execution_memory
    return {"ok": True, "data": get_execution_memory().stats()}


@router.get("/api/v3/execution-history/patterns")
async def execution_patterns(_user: dict = Depends(require_auth)):
    from core.planning.execution_memory import get_execution_memory
    return {"ok": True, "data": get_execution_memory().get_successful_patterns()}
