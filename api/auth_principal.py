"""
api/auth_principal.py — Extraction canonique de l'identité authentifiée.

Ce module ne doit pas contenir de logique métier ni dépendre de modules
internes lourds. Il traduit le `request.state.user` positionné par
`AccessEnforcementMiddleware` (ou `require_auth`) en un identifiant stable,
non-secret, utilisable comme `principal_id` par `PolicyEngine`.

Sources supportées (par fiabilité décroissante) :
  - access_token : token_id stable (non-secret)
  - jwt          : sub/username
  - static       : username="api" (un seul token statique configuré)

Un token brut, un secret ou une clé API ne sont JAMAIS utilisés comme
principal.
"""
from __future__ import annotations

from typing import Any

from fastapi import Request


def build_principal_id(user: dict[str, Any]) -> str:
    """Return a stable, non-secret principal id from a user dict.

    Examples:
      - access token  -> "access_token:<token_id>"
      - JWT admin     -> "jwt:admin"
      - static token  -> "static:api"
      - missing id    -> "<auth_type>:unknown"
    """
    auth_type = str(user.get("auth_type") or "unknown")
    # Prefer token_id for access tokens — stable and non-secret.
    token_id = user.get("token_id")
    if token_id:
        return f"{auth_type}:{token_id}"

    username = user.get("username") or user.get("sub")
    if username:
        return f"{auth_type}:{username}"

    return f"{auth_type}:unknown"


def get_authenticated_principal(request: Request) -> str | None:
    """Extract a validated principal from a FastAPI request.

    Relies on `AccessEnforcementMiddleware` / `require_auth` having already
    populated `request.state.user`. Returns None only when the request did not
    go through auth (internal/test/dev paths) — callers on public endpoints
    MUST fail-closed if this returns None.
    """
    user = getattr(request.state, "user", None)
    if isinstance(user, dict):
        return build_principal_id(user)
    return None
