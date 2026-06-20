"""
BEA MAX — Token Management API Routes
==========================================
Admin-only endpoints for managing access tokens.

POST   /api/v3/tokens          — Create new token
GET    /api/v3/tokens          — List all tokens
GET    /api/v3/tokens/stats    — Token system stats
DELETE /api/v3/tokens/{id}     — Delete token
POST   /api/v3/tokens/{id}/revoke  — Revoke token
POST   /api/v3/tokens/{id}/enable  — Re-enable token
POST   /api/v3/tokens/validate     — Validate a token (any role)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api._deps import require_auth, require_admin
from api.access_tokens import get_token_manager

router = APIRouter(prefix="/api/v3/tokens", tags=["tokens"])


# ── Request models ──

class CreateTokenRequest(BaseModel):
    name: str
    role: str = "user"
    expires_days: int = 0
    max_uses: int = 0
    metadata: dict = {}


class ValidateTokenRequest(BaseModel):
    token: str


# ── Routes ──

@router.post("")
async def create_token(req: CreateTokenRequest, _: dict = Depends(require_admin)):
    """Create a new access token (admin only). Returns raw token ONCE."""
    manager = get_token_manager()
    try:
        raw_token, token = manager.create_token(
            name=req.name,
            role=req.role,
            expires_days=req.expires_days,
            max_uses=req.max_uses,
            metadata=req.metadata,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "token": raw_token,
        "token_id": token.id,
        "name": token.name,
        "role": token.role,
        "expires_at": token.expires_at,
        "max_uses": token.max_uses,
        "message": "Save this token now — it will not be shown again.",
    }


@router.get("")
async def list_tokens(include_expired: bool = False, _: dict = Depends(require_admin)):
    """List all tokens (admin only). Never returns raw tokens."""
    manager = get_token_manager()
    return {"tokens": manager.list_tokens(include_expired=include_expired)}


@router.get("/stats")
async def token_stats(_: dict = Depends(require_admin)):
    """Token system statistics (admin only)."""
    manager = get_token_manager()
    return manager.get_stats()


@router.delete("/{token_id}")
async def delete_token(token_id: str, _: dict = Depends(require_admin)):
    """Permanently delete a token (admin only)."""
    manager = get_token_manager()
    if manager.delete_token(token_id):
        return {"status": "deleted", "token_id": token_id}
    raise HTTPException(status_code=404, detail="Token not found")


@router.post("/{token_id}/revoke")
async def revoke_token(token_id: str, _: dict = Depends(require_admin)):
    """Revoke (disable) a token (admin only)."""
    manager = get_token_manager()
    if manager.revoke_token(token_id):
        return {"status": "revoked", "token_id": token_id}
    raise HTTPException(status_code=404, detail="Token not found")


@router.post("/{token_id}/enable")
async def enable_token(token_id: str, _: dict = Depends(require_admin)):
    """Re-enable a revoked token (admin only)."""
    manager = get_token_manager()
    if manager.enable_token(token_id):
        return {"status": "enabled", "token_id": token_id}
    raise HTTPException(status_code=404, detail="Token not found")


@router.post("/validate")
async def validate_token_endpoint(req: ValidateTokenRequest, _: dict = Depends(require_auth)):
    """Validate a token (any authenticated user)."""
    manager = get_token_manager()
    token = manager.validate_token(req.token)
    if token:
        return {"valid": True, "role": token.role, "name": token.name}
    return {"valid": False}
