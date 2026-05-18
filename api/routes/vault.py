"""
JARVIS MAX — Vault API Routes
================================
REST endpoints for Secret Vault management.

All endpoints require authentication.
Reveal/create/delete require admin role.
Use requires operator+.
List available to all authenticated users.

POST /vault/create   — Create a new secret
POST /vault/update   — Update secret value (rotate)
POST /vault/use      — Use a secret (agent injection)
POST /vault/reveal   — Reveal plaintext (admin only)
POST /vault/delete   — Delete a secret
GET  /vault/list     — List secret metadata
GET  /vault/logs     — Get audit logs
POST /vault/unlock   — Unlock the vault
POST /vault/lock     — Lock the vault
GET  /vault/status   — Vault status
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api._deps import require_auth, require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vault", tags=["vault"], dependencies=[Depends(require_auth)])


# ── Request/Response Models ──

class UnlockRequest(BaseModel):
    master_password: str

class CreateSecretRequest(BaseModel):
    name: str
    value: str
    secret_type: str = "api_key"
    description: str = ""
    domain: str = ""
    policy: dict = Field(default_factory=dict)
    totp_config: dict | None = None

class UpdateSecretRequest(BaseModel):
    secret_id: str
    new_value: str
    reason: str = ""

class UseSecretRequest(BaseModel):
    secret_id: str
    agent_name: str
    target_domain: str
    purpose: str = ""

class RevealSecretRequest(BaseModel):
    secret_id: str
    reason: str = ""

class DeleteSecretRequest(BaseModel):
    secret_id: str


# ── Vault singleton (lazy init) ──

_vault = None

def get_vault():
    global _vault
    if _vault is None:
        from core.security.secret_vault import SecretVault
        _vault = SecretVault()
    return _vault


def set_vault(vault):
    """For testing — inject a vault instance."""
    global _vault
    _vault = vault


def _vault_role(user: dict) -> str:
    """Map API roles to vault policy roles."""
    role = (user or {}).get("role", "viewer")
    if role == "admin":
        return "admin"
    if role == "user":
        return "operator"
    return "viewer"


# ── Endpoints ──

@router.post("/unlock")
def unlock_vault(req: UnlockRequest):
    vault = get_vault()
    success = vault.unlock(req.master_password)
    if not success:
        raise HTTPException(status_code=401, detail="Wrong master password")
    return {"status": "unlocked", "timeout_s": vault._lock_timeout}


@router.post("/lock")
def lock_vault():
    vault = get_vault()
    vault.lock()
    return {"status": "locked"}


@router.get("/status")
def vault_status():
    vault = get_vault()
    return {
        "unlocked": vault.is_unlocked,
        "secret_count": vault.secret_count,
        "audit_entries": vault._audit.entry_count,
    }


@router.post("/create")
def create_secret(req: CreateSecretRequest, user: dict = Depends(require_admin)):
    vault = get_vault()
    try:
        meta = vault.create_secret(
            name=req.name, value=req.value,
            secret_type=req.secret_type,
            description=req.description,
            domain=req.domain,
            policy=req.policy,
            totp_config=req.totp_config,
            role="admin",
        )
        return {"status": "created", "secret": meta.to_dict()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)[:200])


@router.post("/update")
def update_secret(req: UpdateSecretRequest, user: dict = Depends(require_admin)):
    vault = get_vault()
    try:
        ok = vault.update_secret(req.secret_id, req.new_value, reason=req.reason)
        if not ok:
            raise HTTPException(status_code=404, detail="Secret not found")
        return {"status": "updated", "secret_id": req.secret_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)[:200])


@router.post("/use")
def use_secret(req: UseSecretRequest, user: dict = Depends(require_auth)):
    vault = get_vault()
    role = _vault_role(user)
    if role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Role cannot use secrets")
    result = vault.use_secret(
        req.secret_id, req.agent_name, req.target_domain, req.purpose,
        role=role,
    )
    if not result.success:
        raise HTTPException(status_code=403, detail=result.error)
    # NEVER return inject_value in API response
    return result.safe_dict()


@router.post("/reveal")
def reveal_secret(req: RevealSecretRequest, user: dict = Depends(require_admin)):
    vault = get_vault()
    try:
        plaintext = vault.reveal_secret(req.secret_id, reason=req.reason)
        return {"secret_id": req.secret_id, "value": plaintext}
    except Exception as e:
        raise HTTPException(status_code=403, detail=str(e)[:200])


@router.post("/delete")
def delete_secret(req: DeleteSecretRequest, user: dict = Depends(require_admin)):
    vault = get_vault()
    try:
        ok = vault.delete_secret(req.secret_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Secret not found")
        return {"status": "deleted", "secret_id": req.secret_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)[:200])


@router.get("/list")
def list_secrets():
    vault = get_vault()
    return {"secrets": vault.list_secrets()}


@router.get("/logs")
def audit_logs(
    secret_id: str | None = None,
    actor: str | None = None,
    limit: int = 100,
    user: dict = Depends(require_admin),
):
    vault = get_vault()
    logs = vault.get_audit_logs(secret_id, actor, limit, role="admin")
    return {"logs": logs, "count": len(logs)}
