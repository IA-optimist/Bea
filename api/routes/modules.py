"""
JARVIS MAX — Modules API Routes (/modules/* prefix)
=====================================================
Provides agent/skill/MCP/connector CRUD at /modules/*.
Registered in api/main.py as modules_router.

Note: api/routes/modules_v3.py covers the same resources at /api/v3/* prefix.
Both routers are mounted — they serve different path namespaces.

Unified REST endpoints for Agents, Skills, Connectors, MCP.

/modules/agents/*      — Agent CRUD + toggle + duplicate
/modules/skills/*      — Skill CRUD + toggle
/modules/mcp/*         — MCP CRUD + toggle + test
/modules/connectors/*  — Connector CRUD + toggle + test
/modules/catalog       — Browse installable modules
/modules/blueprint/*   — Export/import module configs
/modules/health        — Aggregate health summary
"""
from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api._deps import require_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/modules", tags=["modules"], dependencies=[Depends(require_auth)])


# ── Request Models ──

class AgentRequest(BaseModel):
    name: str = ""
    description: str = ""
    purpose: str = ""
    model: str = ""
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
    input_schema: dict = Field(default_factory=dict)
    output_schema: dict = Field(default_factory=dict)
    tools: list = Field(default_factory=list)
    tags: list = Field(default_factory=list)

class MCPRequest(BaseModel):
    name: str = ""
    transport: str = "http"
    endpoint: str = ""
    auth: str = "none"
    auth_ref: str = ""
    trust: str = "medium"
    headers: dict = Field(default_factory=dict)
    env_vars: dict = Field(default_factory=dict)
    tags: list = Field(default_factory=list)

class ConnectorRequest(BaseModel):
    provider: str = ""
    name: str = ""
    auth: str = "api_key"
    scopes: list = Field(default_factory=list)
    identity: str = ""
    secrets: list = Field(default_factory=list)
    environment: str = "prod"
    notes: str = ""
    tags: list = Field(default_factory=list)

class UpdateRequest(BaseModel):
    updates: dict = Field(default_factory=dict)

class BlueprintRequest(BaseModel):
    blueprint: dict = Field(default_factory=dict)


# ── Singleton ──

_mgr = None

def get_mgr():
    global _mgr
    if _mgr is None:
        from core.modules.module_manager import ModuleManager
        _mgr = ModuleManager()
    return _mgr

def set_mgr(mgr):
    global _mgr
    _mgr = mgr


# ── Agents ──

@router.post("/agents/create")
def create_agent(req: AgentRequest, mode: str = "simple"):
    return {"agent": get_mgr().create_agent(req.model_dump(), mode).to_dict()}

@router.put("/agents/{agent_id}")
def update_agent(agent_id: str, req: UpdateRequest):
    result = get_mgr().update_agent(agent_id, req.updates)
    if not result:
        raise HTTPException(404, "Agent not found")
    return {"agent": result.to_dict()}

@router.delete("/agents/{agent_id}")
def delete_agent(agent_id: str):
    if not get_mgr().delete_agent(agent_id):
        raise HTTPException(404, "Agent not found")
    return {"status": "deleted"}

@router.post("/agents/{agent_id}/toggle")
def toggle_agent(agent_id: str):
    status = get_mgr().toggle_agent(agent_id)
    if status is None:
        raise HTTPException(404, "Agent not found")
    return {"status": status}

@router.post("/agents/{agent_id}/duplicate")
def duplicate_agent(agent_id: str):
    result = get_mgr().duplicate_agent(agent_id)
    if not result:
        raise HTTPException(404, "Agent not found")
    return {"agent": result.to_dict()}

@router.get("/agents")
def list_agents(status: str | None = None, simple: bool = False):
    return {"agents": get_mgr().list_agents(status, simple)}


# ── Skills ──

@router.post("/skills/create")
def create_skill(req: SkillRequest):
    return {"skill": get_mgr().create_skill(req.model_dump()).to_dict()}

@router.put("/skills/{skill_id}")
def update_skill(skill_id: str, req: UpdateRequest):
    result = get_mgr().update_skill(skill_id, req.updates)
    if not result:
        raise HTTPException(404, "Skill not found")
    return {"skill": result.to_dict()}

@router.delete("/skills/{skill_id}")
def delete_skill(skill_id: str):
    if not get_mgr().delete_skill(skill_id):
        raise HTTPException(404, "Skill not found")
    return {"status": "deleted"}

@router.post("/skills/{skill_id}/toggle")
def toggle_skill(skill_id: str):
    status = get_mgr().toggle_skill(skill_id)
    if status is None:
        raise HTTPException(404, "Skill not found")
    return {"status": status}

@router.get("/skills")
def list_skills(category: str | None = None):
    return {"skills": get_mgr().list_skills(category)}


# ── MCP ──

@router.post("/mcp/create")
def create_mcp(req: MCPRequest):
    return {"mcp": get_mgr().create_mcp(req.model_dump()).to_safe_dict()}

@router.put("/mcp/{mcp_id}")
def update_mcp(mcp_id: str, req: UpdateRequest):
    result = get_mgr().update_mcp(mcp_id, req.updates)
    if not result:
        raise HTTPException(404, "MCP not found")
    return {"mcp": result.to_safe_dict()}

@router.delete("/mcp/{mcp_id}")
def delete_mcp(mcp_id: str):
    if not get_mgr().delete_mcp(mcp_id):
        raise HTTPException(404, "MCP not found")
    return {"status": "deleted"}

@router.post("/mcp/{mcp_id}/toggle")
def toggle_mcp(mcp_id: str):
    status = get_mgr().toggle_mcp(mcp_id)
    if status is None:
        raise HTTPException(404, "MCP not found")
    return {"status": status}

@router.post("/mcp/{mcp_id}/test")
def test_mcp(mcp_id: str):
    return get_mgr().test_mcp(mcp_id)

@router.get("/mcp")
def list_mcp():
    return {"mcp": get_mgr().list_mcp()}


# ── Connectors ──

@router.post("/connectors/create")
def create_connector(req: ConnectorRequest):
    return {"connector": get_mgr().create_connector(req.model_dump()).to_dict()}

@router.put("/connectors/{conn_id}")
def update_connector(conn_id: str, req: UpdateRequest):
    result = get_mgr().update_connector(conn_id, req.updates)
    if not result:
        raise HTTPException(404, "Connector not found")
    return {"connector": result.to_dict()}

@router.delete("/connectors/{conn_id}")
def delete_connector(conn_id: str):
    if not get_mgr().delete_connector(conn_id):
        raise HTTPException(404, "Connector not found")
    return {"status": "deleted"}

@router.post("/connectors/{conn_id}/toggle")
def toggle_connector(conn_id: str):
    status = get_mgr().toggle_connector(conn_id)
    if status is None:
        raise HTTPException(404, "Connector not found")
    return {"status": status}

@router.post("/connectors/{conn_id}/test")
def test_connector(conn_id: str):
    return get_mgr().test_connector(conn_id)

@router.get("/connectors")
def list_connectors(provider: str | None = None):
    return {"connectors": get_mgr().list_connectors(provider)}


# ── Catalog ──

@router.get("/catalog")
def get_catalog(module_type: str | None = None, category: str | None = None):
    return {"catalog": get_mgr().get_catalog(module_type, category)}

@router.post("/catalog/{catalog_id}/install")
def install_from_catalog(catalog_id: str):
    return get_mgr().install_from_catalog(catalog_id)


# ── Blueprints ──

@router.get("/blueprint/{module_type}/{module_id}")
def export_blueprint(module_type: str, module_id: str):
    bp = get_mgr().export_blueprint(module_type, module_id)
    if not bp:
        raise HTTPException(404, "Module not found")
    return bp

@router.post("/blueprint/import")
def import_blueprint(req: BlueprintRequest):
    return get_mgr().import_blueprint(req.blueprint)


# ── Health ──

@router.get("/health")
def health():
    return get_mgr().health_summary()
