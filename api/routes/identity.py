"""
JARVIS MAX — Identity API Routes
====================================
REST endpoints for Identity Manager.

POST /identity/create   — Create identity (template-driven)
POST /identity/link     — Link identity to service/domain
POST /identity/use      — Use identity (retrieve credentials via vault)
POST /identity/revoke   — Revoke identity + linked secrets
POST /identity/rotate   — Rotate a specific secret
POST /identity/delete   — Delete identity
GET  /identity/list     — List identities (metadata only)
GET  /identity/graph    — Get identity relationship graph
GET  /identity/logs     — Get audit logs
GET  /identity/templates — List available provider templates
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api._deps import require_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/identity", tags=["identity"], dependencies=[Depends(require_auth)])


# ── Request Models ──

class CreateIdentityRequest(BaseModel):
    provider: str
    display_name: str = ""
    secrets: dict = Field(default_factory=dict)
    fields: dict = Field(default_factory=dict)
    environment: str = "prod"
    workspace_id: str = ""
    policy: dict = Field(default_factory=dict)

class LinkRequest(BaseModel):
    identity_id: str
    target: str
    link_type: str = "service"   # "service" or "domain"
    edge_type: str = "authenticates"

class UseRequest(BaseModel):
    identity_id: str
    agent_name: str
    target_service: str = ""
    environment: str = "prod"
    purpose: str = ""

class RotateRequest(BaseModel):
    identity_id: str
    secret_role: str
    new_value: str

class RevokeRequest(BaseModel):
    identity_id: str

class DeleteRequest(BaseModel):
    identity_id: str


# ── Manager singleton ──

_manager = None

def get_manager():
    global _manager
    if _manager is None:
        from core.identity.identity_manager import IdentityManager
        _manager = IdentityManager()
    return _manager

def set_manager(manager):
    global _manager
    _manager = manager


# ── Endpoints ──

@router.post("/create")
def create_identity(req: CreateIdentityRequest):
    mgr = get_manager()
    try:
        identity = mgr.create_identity(
            provider=req.provider,
            display_name=req.display_name,
            secrets=req.secrets or None,
            fields=req.fields or None,
            environment=req.environment,
            workspace_id=req.workspace_id,
            policy=req.policy or None,
            role="admin",
        )
        return {"status": "created", "identity": identity.to_dict()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)[:200])


@router.post("/link")
def link_identity(req: LinkRequest):
    mgr = get_manager()
    if req.link_type == "domain":
        ok = mgr.link_to_domain(req.identity_id, req.target)
    else:
        ok = mgr.link_to_service(req.identity_id, req.target, req.edge_type)
    if not ok:
        raise HTTPException(status_code=404, detail="Identity not found or permission denied")
    return {"status": "linked", "identity_id": req.identity_id, "target": req.target}


@router.post("/use")
def use_identity(req: UseRequest):
    mgr = get_manager()
    result = mgr.use_identity(
        req.identity_id, req.agent_name, req.target_service,
        req.environment, req.purpose,
    )
    if not result.success:
        raise HTTPException(status_code=403, detail=result.error)
    return result.safe_dict()


@router.post("/rotate")
def rotate_secret(req: RotateRequest):
    mgr = get_manager()
    ok = mgr.rotate_secret(req.identity_id, req.secret_role, req.new_value)
    if not ok:
        raise HTTPException(status_code=404, detail="Identity or secret role not found")
    return {"status": "rotated", "identity_id": req.identity_id}


@router.post("/revoke")
def revoke_identity(req: RevokeRequest):
    mgr = get_manager()
    ok = mgr.revoke_identity(req.identity_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Identity not found")
    return {"status": "revoked", "identity_id": req.identity_id}


@router.post("/delete")
def delete_identity(req: DeleteRequest):
    mgr = get_manager()
    ok = mgr.delete_identity(req.identity_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Identity not found")
    return {"status": "deleted", "identity_id": req.identity_id}


@router.get("/list")
def list_identities(
    environment: str | None = None,
    provider: str | None = None,
    status: str | None = None,
):
    mgr = get_manager()
    return {"identities": mgr.list_identities(environment, provider, status)}


@router.get("/graph")
def identity_graph():
    mgr = get_manager()
    return mgr.get_graph()


@router.get("/logs")
def identity_logs(
    identity_id: str | None = None,
    limit: int = 100,
):
    mgr = get_manager()
    logs = mgr.get_audit_logs(identity_id=identity_id, limit=limit)
    return {"logs": logs, "count": len(logs)}


@router.get("/templates")
def identity_templates():
    from core.identity.identity_templates import list_templates, template_providers
    return {
        "templates": list_templates(),
        "providers": template_providers(),
    }
