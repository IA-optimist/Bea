"""
core/security/rbac.py — Role-Based Access Control pour BeaMax.

Rôles :
  admin    → accès total (self-improvement, admin, missions, lecture)
  operator → peut soumettre des missions, approuver, voir les rapports
  viewer   → lecture seule (status, health, rapports)

Règles de sécurité :
  - L'authentification est TOUJOURS obligatoire. Il n'existe aucun mode
    "open" ou "anonymous". Si BEA_API_TOKEN n'est pas configuré,
    le démarrage échoue en production (startup_guard) et seul un token
    JWT valide est accepté en développement.
  - La comparaison des tokens statiques utilise hmac.compare_digest()
    pour prévenir les timing attacks.
  - Le fallback token.SIGNATURE (PyJWT absent) a été supprimé.
    PyJWT est une dépendance obligatoire.
"""
from __future__ import annotations

import hmac
import os
from dataclasses import dataclass
from typing import Optional

import structlog
from fastapi import Depends, Header, HTTPException, status

log = structlog.get_logger()

# ── Hiérarchie des rôles ──────────────────────────────────────────────────────
ROLE_HIERARCHY: dict[str, int] = {
    "viewer":   10,
    "operator": 20,
    "admin":    30,
}
DEFAULT_ROLE = "viewer"


@dataclass(frozen=True)
class CurrentUser:
    username: str
    role: str

    @property
    def role_level(self) -> int:
        return ROLE_HIERARCHY.get(self.role, 0)

    def has_role(self, required: str) -> bool:
        required_level = ROLE_HIERARCHY.get(required, 999)
        return self.role_level >= required_level


# ── Extraction du token ───────────────────────────────────────────────────────

def _extract_token(
    x_bea_token: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
) -> Optional[str]:
    """Extrait le token brut depuis X-Bea-Token ou Authorization: Bearer."""
    if x_bea_token:
        return x_bea_token
    if authorization:
        if authorization.startswith("Bearer "):
            return authorization[7:]
        return authorization
    return None


# ── Résolution du CurrentUser ─────────────────────────────────────────────────

def _resolve_user_from_token(token: Optional[str]) -> Optional[CurrentUser]:
    """
    Résout un CurrentUser depuis un token JWT ou API statique.
    Retourne None si le token est invalide/absent.

    SÉCURITÉ :
      - Token statique : comparaison constant-time via hmac.compare_digest()
      - JWT : décodé avec PyJWT (obligatoire). Aucun fallback.
      - Aucun accès anonyme ou "dev open" : tout token invalide → None → 401.
    """
    if not token:
        return None

    api_token = os.getenv("BEA_API_TOKEN", "")

    # Token API statique — comparaison constant-time (anti timing-attack)
    if api_token and hmac.compare_digest(token, api_token):
        return CurrentUser(username="api_client", role="admin")

    # JWT — PyJWT obligatoire, aucun fallback
    try:
        import jwt as _jwt
        from config.settings import get_settings
        secret = get_settings().bea_secret_key
        payload = _jwt.decode(token, secret, algorithms=["HS256"])
        username = payload.get("sub", "unknown")
        role = payload.get("role", DEFAULT_ROLE)
        if role not in ROLE_HIERARCHY:
            role = DEFAULT_ROLE
        return CurrentUser(username=username, role=role)
    except ImportError:
        # PyJWT manquant : erreur de configuration, pas un fallback silencieux
        log.error("rbac.pyjwt_missing — install PyJWT: pip install PyJWT>=2.0")
        return None
    except Exception as exc:
        log.warning("rbac.jwt_decode_failed", err=str(exc)[:80])
        return None


# ── Dépendances FastAPI ───────────────────────────────────────────────────────

def get_current_user(
    x_bea_token: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
) -> CurrentUser:
    """
    Dépendance FastAPI : extrait et valide l'utilisateur courant.
    Lève HTTP 401 systématiquement si le token est absent ou invalide.

    AUCUN mode anonyme ou open. L'authentification est toujours requise.
    En dev sans BEA_API_TOKEN configuré, un JWT signé avec
    BEA_SECRET_KEY est quand même nécessaire.
    """
    token = _extract_token(x_bea_token, authorization)
    user = _resolve_user_from_token(token)

    if user is None:
        log.warning("rbac.unauthorized", token_present=bool(token))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Token invalide ou manquant.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def require_role(minimum_role: str):
    """
    Factory de dépendance FastAPI : exige un rôle minimum.

    Usage :
        @router.post("/admin/thing")
        async def thing(user: CurrentUser = Depends(require_role("admin"))):
            ...
    """
    if minimum_role not in ROLE_HIERARCHY:
        raise ValueError(f"Rôle inconnu : {minimum_role!r}. Valeurs valides : {list(ROLE_HIERARCHY)}")

    def _dep(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not user.has_role(minimum_role):
            log.warning(
                "rbac.forbidden",
                username=user.username,
                user_role=user.role,
                required_role=minimum_role,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Accès refusé. Rôle requis : {minimum_role!r} (rôle actuel : {user.role!r}).",
            )
        return user

    return _dep
