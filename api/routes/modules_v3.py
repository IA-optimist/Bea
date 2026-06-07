"""
BEA MAX — Modules v3 API Routes
======================================
Versioned REST API with RBAC, audit, dependency validation, health.

All mutations enforced through governance layer:
  1. RBAC check → 2. Audit log → 3. Dependency validation → 4. Execute

/api/v3/agents/*        — Agent CRUD + test + wizard
/api/v3/skills/*        — Skill CRUD + test
/api/v3/connectors/*    — Connector CRUD + test + rebind + health
/api/v3/mcp/*           — MCP CRUD + test + discover
/api/v3/catalog         — Browse + install
/api/v3/modules/health  — Full health overview
/api/v3/modules/audit   — Audit trail
/api/v3/modules/wizard  — Agent creation wizard steps
/api/v3/modules/deps    — Dependency validation
"""
from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, HTTPException, Header, Request
from pydantic import BaseModel, Field
from typing import Optional

from api._deps import require_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v3", tags=["modules-v3"], dependencies=[Depends(require_auth)])


# ── Request Models ──

class AgentRequest(BaseModel):
    name: str = ""
    description: str = ""
    purpose: str = ""
    model: str = ""
    model_tier: str = ""
    tools: list = Field(default_factory=list)
    skills: list = Field(default_factory=list)
    connectors: list = Field(default_factory=list)
    secrets: list = Field(default_factory=list)
    risk: str = "low"
    approval: str = "auto"
    tags: list = Field(default_factory=list)
    system_prompt: str = ""
    behavior_rules: list = Field(default_factory=list)
    limits: dict = Field(default_factory=dict)

class SkillRequest(BaseModel):
    name: str = ""
    description: str = ""
    category: str = ""
    version: str = "1.0"
    tools: list = Field(default_factory=list)
    tags: list = Field(default_factory=list)

class ConnectorRequest(BaseModel):
    provider: str = ""
    name: str = ""
    auth: str = "api_key"
    scopes: list = Field(default_factory=list)
    identity: str = ""
    secrets: list = Field(default_factory=list)
    environment: str = "prod"
    tags: list = Field(default_factory=list)

class MCPRequest(BaseModel):
    name: str = ""
    transport: str = "http"
    endpoint: str = ""
    auth: str = "none"
    auth_ref: str = ""
    trust: str = "medium"
    tags: list = Field(default_factory=list)

class UpdateRequest(BaseModel):
    updates: dict = Field(default_factory=dict)

class BlueprintRequest(BaseModel):
    blueprint: dict = Field(default_factory=dict)


# ── Singletons ──

_mgr = None
_gov_audit = None
_health = None
_validator = None

def _get_mgr():
    global _mgr
    if _mgr is None:
        from core.modules.module_manager import ModuleManager
        _mgr = ModuleManager()
    return _mgr

def _get_audit():
    global _gov_audit
    if _gov_audit is None:
        from core.modules.module_governance import ModuleAuditLog
        _gov_audit = ModuleAuditLog()
    return _gov_audit

def _get_health():
    global _health
    if _health is None:
        from core.modules.module_governance import HealthEngine, DependencyValidator
        _validator = DependencyValidator(_get_mgr())
        _health = HealthEngine(_get_mgr(), _validator)
    return _health

def _get_validator():
    global _validator
    if _validator is None:
        from core.modules.module_governance import DependencyValidator
        _validator = DependencyValidator(_get_mgr())
    return _validator

def set_instances(mgr=None, audit=None, health=None, validator=None):
    """For testing — inject instances."""
    global _mgr, _gov_audit, _health, _validator
    if mgr: _mgr = mgr
    if audit: _gov_audit = audit
    if health: _health = health
    if validator: _validator = validator


def _role_from_request(request: Request) -> str:
    """Extract role from verified auth state set by AccessEnforcementMiddleware.

    Reads request.state.user (populated from the validated JWT/token by the
    global middleware) instead of a client-controlled X-Role header.
    Fails safe to 'viewer' — never grants admin by default.
    """
    user = getattr(request.state, "user", None)
    if user and isinstance(user, dict):
        return user.get("role", "viewer")
    return "viewer"


# ── Agents ──

@router.get("/agents")
def list_agents(status: str | None = None, simple: bool = False):
    return {"agents": _get_mgr().list_agents(status, simple)}

@router.post("/agents")
def create_agent(req: AgentRequest, request: Request, x_source: Optional[str] = Header("api")):
    from core.modules.module_governance import check_rbac, MODEL_TIER_MAP
    role = _role_from_request(request)
    rbac = check_rbac(role, "agent", "create")
    if not rbac.allowed:
        raise HTTPException(403, rbac.reason)

    config = req.model_dump()
    # Map model tier to model name
    if req.model_tier and req.model_tier in MODEL_TIER_MAP:
        config["model"] = MODEL_TIER_MAP[req.model_tier]["model"]

    mode = "advanced" if req.system_prompt else "simple"
    agent = _get_mgr().create_agent(config, mode)
    _get_audit().record(role, role, "agent", agent.id, "create", source=x_source or "api",
                        after=agent.to_dict())
    return {"agent": agent.to_dict(), "approval_needed": rbac.needs_approval}

@router.put("/agents/{agent_id}")
def update_agent(agent_id: str, req: UpdateRequest, request: Request):
    role = _role_from_request(request)
    from core.modules.module_governance import check_rbac
    rbac = check_rbac(role, "agent", "update")
    if not rbac.allowed:
        raise HTTPException(403, rbac.reason)

    before = _get_mgr().get_agent(agent_id)
    before_d = before.to_dict() if before else {}
    result = _get_mgr().update_agent(agent_id, req.updates)
    if not result:
        raise HTTPException(404, "Agent not found")
    _get_audit().record(role, role, "agent", agent_id, "update", before=before_d, after=result.to_dict())
    return {"agent": result.to_dict()}

@router.delete("/agents/{agent_id}")
def delete_agent(agent_id: str, request: Request):
    role = _role_from_request(request)
    from core.modules.module_governance import check_rbac
    rbac = check_rbac(role, "agent", "delete")
    if not rbac.allowed:
        raise HTTPException(403, rbac.reason)
    if not _get_mgr().delete_agent(agent_id):
        raise HTTPException(404, "Agent not found")
    _get_audit().record(role, role, "agent", agent_id, "delete")
    return {"status": "deleted"}

@router.post("/agents/{agent_id}/test")
def test_agent(agent_id: str):
    health = _get_health().agent_health(agent_id)
    return health.to_dict()

@router.post("/agents/{agent_id}/toggle")
def toggle_agent(agent_id: str, request: Request):
    status = _get_mgr().toggle_agent(agent_id)
    if status is None:
        raise HTTPException(404, "Agent not found")
    role = _role_from_request(request)
    _get_audit().record(role, role, "agent", agent_id, "toggle")
    return {"status": status}

@router.post("/agents/{agent_id}/duplicate")
def duplicate_agent(agent_id: str):
    result = _get_mgr().duplicate_agent(agent_id)
    if not result:
        raise HTTPException(404, "Agent not found")
    return {"agent": result.to_dict()}


# ── Skills ──

@router.get("/skills")
def list_skills(category: str | None = None):
    return {"skills": _get_mgr().list_skills(category)}

@router.post("/skills")
def create_skill(req: SkillRequest, request: Request):
    skill = _get_mgr().create_skill(req.model_dump())
    role = _role_from_request(request)
    _get_audit().record(role, role, "skill", skill.id, "create", after=skill.to_dict())
    return {"skill": skill.to_dict()}

@router.put("/skills/{skill_id}")
def update_skill(skill_id: str, req: UpdateRequest):
    result = _get_mgr().update_skill(skill_id, req.updates)
    if not result:
        raise HTTPException(404, "Skill not found")
    return {"skill": result.to_dict()}

@router.delete("/skills/{skill_id}")
def delete_skill(skill_id: str, request: Request):
    if not _get_mgr().delete_skill(skill_id):
        raise HTTPException(404, "Skill not found")
    role = _role_from_request(request)
    _get_audit().record(role, role, "skill", skill_id, "delete")
    return {"status": "deleted"}

@router.post("/skills/{skill_id}/toggle")
def toggle_skill(skill_id: str):
    status = _get_mgr().toggle_skill(skill_id)
    if status is None:
        raise HTTPException(404, "Skill not found")
    return {"status": status}

@router.post("/skills/{skill_id}/test")
def test_skill(skill_id: str):
    skill = _get_mgr().get_skill(skill_id)
    if not skill:
        raise HTTPException(404, "Skill not found")
    return {"status": "ready" if skill.status == "enabled" else "disabled", "name": skill.name}


# ── Connectors ──

@router.get("/connectors")
def list_connectors(provider: str | None = None):
    return {"connectors": _get_mgr().list_connectors(provider)}

@router.post("/connectors")
def create_connector(req: ConnectorRequest, request: Request):
    role = _role_from_request(request)
    from core.modules.module_governance import check_rbac
    risk_ctx = "payment" if req.provider in ("stripe", "paypal") else ""
    rbac = check_rbac(role, "connector", "create", risk_ctx)
    if not rbac.allowed:
        raise HTTPException(403, rbac.reason)

    conn = _get_mgr().create_connector(req.model_dump())
    _get_audit().record(role, role, "connector", conn.id, "create", after=conn.to_dict())
    return {"connector": conn.to_dict(), "approval_needed": rbac.needs_approval}

@router.put("/connectors/{conn_id}")
def update_connector(conn_id: str, req: UpdateRequest):
    result = _get_mgr().update_connector(conn_id, req.updates)
    if not result:
        raise HTTPException(404, "Connector not found")
    return {"connector": result.to_dict()}

@router.delete("/connectors/{conn_id}")
def delete_connector(conn_id: str, request: Request):
    if not _get_mgr().delete_connector(conn_id):
        raise HTTPException(404, "Connector not found")
    role = _role_from_request(request)
    _get_audit().record(role, role, "connector", conn_id, "delete")
    return {"status": "deleted"}

@router.post("/connectors/{conn_id}/toggle")
def toggle_connector(conn_id: str):
    status = _get_mgr().toggle_connector(conn_id)
    if status is None:
        raise HTTPException(404, "Connector not found")
    return {"status": status}

@router.post("/connectors/{conn_id}/test")
def test_connector(conn_id: str):
    test_result = _get_mgr().test_connector(conn_id)
    health = _get_health().connector_health(conn_id)
    return {**test_result, "health": health.to_dict()}

@router.post("/connectors/{conn_id}/rebind")
def rebind_connector(conn_id: str, req: UpdateRequest, request: Request):
    """Rebind secrets/identity for a connector."""
    updates = {}
    if "identity" in req.updates:
        updates["linked_identity"] = req.updates["identity"]
    if "secrets" in req.updates:
        updates["linked_secrets"] = req.updates["secrets"]
    result = _get_mgr().update_connector(conn_id, updates)
    if not result:
        raise HTTPException(404, "Connector not found")
    role = _role_from_request(request)
    _get_audit().record(role, role, "connector", conn_id, "rebind")
    return {"connector": result.to_dict()}


# ── MCP ──

@router.get("/mcp")
def list_mcp():
    return {"mcp": _get_mgr().list_mcp()}

@router.post("/mcp")
def create_mcp(req: MCPRequest, request: Request):
    mcp = _get_mgr().create_mcp(req.model_dump())
    role = _role_from_request(request)
    _get_audit().record(role, role, "mcp", mcp.id, "create", after=mcp.to_safe_dict())
    return {"mcp": mcp.to_safe_dict()}

@router.put("/mcp/{mcp_id}")
def update_mcp(mcp_id: str, req: UpdateRequest):
    result = _get_mgr().update_mcp(mcp_id, req.updates)
    if not result:
        raise HTTPException(404, "MCP not found")
    return {"mcp": result.to_safe_dict()}

@router.delete("/mcp/{mcp_id}")
def delete_mcp(mcp_id: str, request: Request):
    if not _get_mgr().delete_mcp(mcp_id):
        raise HTTPException(404, "MCP not found")
    role = _role_from_request(request)
    _get_audit().record(role, role, "mcp", mcp_id, "delete")
    return {"status": "deleted"}

@router.post("/mcp/{mcp_id}/toggle")
def toggle_mcp(mcp_id: str):
    status = _get_mgr().toggle_mcp(mcp_id)
    if status is None:
        raise HTTPException(404, "MCP not found")
    return {"status": status}

@router.post("/mcp/{mcp_id}/test")
def test_mcp(mcp_id: str):
    test_result = _get_mgr().test_mcp(mcp_id)
    health = _get_health().mcp_health(mcp_id)
    return {**test_result, "health": health.to_dict()}

@router.post("/mcp/{mcp_id}/discover")
def discover_mcp_tools(mcp_id: str):
    """Discover tools from MCP server.

    NOT IMPLEMENTED: live MCP connection not yet built.
    Returns 501 so callers know this is a genuine stub, not a silent no-op.
    Configure tools manually via PUT /api/v3/mcp/{mcp_id} until this lands.
    """
    mcp = _get_mgr().get_mcp(mcp_id)
    if not mcp:
        raise HTTPException(404, "MCP not found")
    raise HTTPException(
        status_code=501,
        detail=(
            "MCP live discovery is not yet implemented. "
            "Configure tools manually or use PUT /api/v3/mcp/{mcp_id}."
        ),
    )


# ── Catalog ──

@router.get("/catalog")
def get_catalog(module_type: str | None = None, category: str | None = None):
    return {"catalog": _get_mgr().get_catalog(module_type, category)}

@router.post("/catalog/install")
def install_from_catalog(catalog_id: str, request: Request):
    result = _get_mgr().install_from_catalog(catalog_id)
    if result.get("success"):
        role = _role_from_request(request)
        _get_audit().record(role, role, result.get("type", ""), result.get("id", ""), "install")
    return result


# ── Blueprints ──

@router.get("/blueprint/{module_type}/{module_id}")
def export_blueprint(module_type: str, module_id: str):
    bp = _get_mgr().export_blueprint(module_type, module_id)
    if not bp:
        raise HTTPException(404, "Module not found")
    return bp

@router.post("/blueprint/import")
def import_blueprint(req: BlueprintRequest):
    return _get_mgr().import_blueprint(req.blueprint)


# ── Health / Audit / Deps / Wizard ──

@router.get("/modules/health")
def full_health():
    return _get_health().full_health()

@router.get("/modules/audit")
def module_audit(module_type: str | None = None, module_id: str | None = None, limit: int = 100):
    return {"audit": _get_audit().query(module_type, module_id, limit=limit)}

@router.get("/modules/wizard")
def wizard_steps():
    from core.modules.module_governance import get_wizard_steps
    return {"steps": get_wizard_steps()}

@router.get("/modules/deps/{module_type}/{module_id}")
def check_deps(module_type: str, module_id: str):
    validator = _get_validator()
    if module_type == "agent":
        issues = validator.validate_agent(module_id)
    elif module_type == "connector":
        issues = validator.validate_connector(module_id)
    else:
        return {"issues": [], "message": f"No dependency check for {module_type}"}
    return {"issues": [i.to_dict() for i in issues]}

@router.get("/modules/deps")
def check_all_deps():
    return _get_validator().validate_all()
