"""
JARVIS MAX v3 — WebSockets & Time-Travel API

Sécurité :
  - Le token d'authentification est lu depuis le header HTTP
    `X-Jarvis-Token` ou `Authorization: Bearer <token>`.
  - Les query params ne sont PLUS acceptés pour éviter l'exposition
    du token dans les logs proxy, l'historique navigateur et les
    headers Referer envoyés à des tiers.
  - La connexion WebSocket est rejetée (code 1008) AVANT accept()
    si le token est invalide — pas après.
"""
import asyncio
import time as _time
import structlog
from typing import Any, Optional
from fastapi import APIRouter, Header, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import BaseModel
from config.settings import get_settings
_silent_log = __import__("structlog").get_logger(__name__)

log = structlog.get_logger()
router = APIRouter()

# Registre canonique dans core.event_stream — ce module ré-exporte pour
# compatibilité (meta_orchestrator importe désormais directement depuis core).
from core.event_stream import (
    ACTIVE_WS_STREAMS as ACTIVE_STREAMS,
    register_ws_stream as register_stream,
    deregister_ws_stream as deregister_stream,
)


def _verify_ws_token(token: Optional[str]) -> bool:
    """
    Vérifie le token WebSocket via le module RBAC.
    Retourne True si valide, False sinon.
    Utilise la même logique que les endpoints REST (hmac.compare_digest + JWT).
    """
    if not token:
        return False
    try:
        # Unified auth: use same verify_token as REST endpoints
        from api.auth import verify_token as _api_verify_token
        user = _api_verify_token(token)
        if user:
            return True
        # Fallback: try RBAC resolver (returns CurrentUser instead of dict)
        from core.security.rbac import _resolve_user_from_token
        return _resolve_user_from_token(token) is not None
    except Exception:
        return False



# Public alias for verify_token (used in token validation)
verify_token = _verify_ws_token

@router.websocket("/api/v3/mission/{mission_id}/stream")
async def websocket_stream(
    websocket: WebSocket,
    mission_id: str,
    x_jarvis_token: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
):
    """
    Point d'entrée WebSocket — flux d'événements de mission en temps réel.

    Authentification :
      Header X-Jarvis-Token: <token>
      — ou —
      Header Authorization: Bearer <token>

    NOTE : Les query params (?token=...) ne sont plus acceptés.
    Le client doit passer le token via les headers WebSocket upgrade.
    """
    # Extraire le token depuis les headers (native clients: Flutter / curl)
    from api.token_utils import strip_bearer
    import hmac as _hmac
    import os as _os
    token: Optional[str] = None
    if x_jarvis_token:
        token = x_jarvis_token
    elif authorization:
        token = strip_bearer(authorization)

    # Fast path: header auth (native clients)
    _authorized = _verify_ws_token(token)
    _api_token = _os.getenv("JARVIS_API_TOKEN", "")

    # Pre-accept rejection: if header token provided but invalid, reject early
    # NOTE: query params plus acceptés — use headers or first-message auth only
    if token and not _authorized and _api_token:
        log.warning("ws_unauthorized_pre_accept", mission_id=mission_id, error="Your access token is invalid")
        await websocket.close(code=1008)
        return

    # Accept() is required before any receive/send operations
    await websocket.accept()

    # Slow path: first-message auth (browser clients — window.WebSocket cannot send headers)
    if not _authorized:
        if _api_token:
            try:
                first_msg = await asyncio.wait_for(websocket.receive_text(), timeout=8)
                candidate = first_msg.strip()
                if _hmac.compare_digest(candidate.encode(), _api_token.encode()):
                    _authorized = True
                else:
                    from api._deps import _verify_jwt
                    _authorized = _verify_jwt(candidate)
            except asyncio.TimeoutError:
                log.warning("ws_auth_timeout", mission_id=mission_id)
        else:
            _authorized = True  # No token configured — auth disabled

    if not _authorized:
        log.warning("ws_unauthorized", mission_id=mission_id)
        await websocket.close(code=1008)
        return
    log.info("ws_client_connected", mission_id=mission_id)

    entry = ACTIVE_STREAMS.get(mission_id)
    stream = entry["stream"] if entry else None
    if not stream:
        await websocket.send_json({"error": "Mission introuvable ou inactive.", "source": "system"})
        await websocket.close()
        return

    # Envoi de l'historique
    events = stream.get_events()
    for e in events:
        await websocket.send_json(e.model_dump())

    # Souscription aux futurs événements
    async def _on_new_event(event):
        try:
            await websocket.send_json(event.model_dump())
        except Exception as err:
            log.warning("ws_send_failed", err=str(err))

    stream.subscribe(_on_new_event)

    try:
        import json as _json
        while True:
            data = await websocket.receive_text()
            # Respond to pings — parse JSON to handle {"type":"ping","ts":...}
            _is_ping = data.strip().lower() == 'ping'
            if not _is_ping:
                try:
                    _p = _json.loads(data)
                    if isinstance(_p, dict) and _p.get('type') == 'ping':
                        _is_ping = True
                except Exception:
                    _silent_log.debug("suppressed_exception", src='ws.py')
            if _is_ping:
                await websocket.send_json({"type": "pong"})
            else:
                log.debug("ws_client_msg", msg=data[:200])
    except WebSocketDisconnect:
        log.info("ws_client_disconnected", mission_id=mission_id)
    finally:
        stream.unsubscribe(_on_new_event)


async def ws_handler(websocket: WebSocket):
    """
    Generic WebSocket handler for /ws/stream.
    Used by the mobile app for general-purpose status streaming.
    Auth via X-Jarvis-Token or Authorization header.
    """
    from api.token_utils import strip_bearer
    import os as _os

    # Extract token from headers
    headers = dict(websocket.headers) if hasattr(websocket, 'headers') else {}
    token = headers.get("x-jarvis-token") or ""
    if not token:
        auth_header = headers.get("authorization", "")
        if auth_header:
            token = strip_bearer(auth_header)

    authorized = _verify_ws_token(token)
    api_token = _os.getenv("JARVIS_API_TOKEN", "")

    # Pre-accept rejection
    if token and not authorized and api_token:
        log.warning("ws_handler_unauthorized_pre_accept")
        await websocket.close(code=1008)
        return

    await websocket.accept()

    # First-message auth fallback (browser clients)
    if not authorized:
        if api_token:
            try:
                import hmac as _hmac
                first_msg = await asyncio.wait_for(websocket.receive_text(), timeout=8)
                candidate = first_msg.strip()
                if _hmac.compare_digest(candidate.encode(), api_token.encode()):
                    authorized = True
                else:
                    from api._deps import _verify_jwt
                    authorized = _verify_jwt(candidate)
            except asyncio.TimeoutError:
                log.warning("ws_handler_auth_timeout")
        else:
            authorized = True

    if not authorized:
        log.warning("ws_handler_unauthorized")
        await websocket.close(code=1008)
        return

    log.info("ws_handler_connected")

    # Send initial status
    try:
        await websocket.send_json({
            "type": "connected",
            "message": "WebSocket connected to JarvisMax",
            "active_streams": len(ACTIVE_STREAMS),
        })
    except Exception:
        _silent_log.debug("suppressed_exception", src='ws.py')

    # Keep alive — relay events or wait for disconnect
    try:
        import json as _json
        while True:
            data = await websocket.receive_text()
            # Handle ping — parse JSON properly to handle extra fields (e.g. "ts")
            # and varying whitespace from different clients (Flutter jsonEncode
            # produces spaces: {"type": "ping", "ts": ...} which breaks exact matching).
            _is_ping = False
            if data.strip().lower() == 'ping':
                _is_ping = True
            else:
                try:
                    _parsed = _json.loads(data)
                    if isinstance(_parsed, dict) and _parsed.get('type') == 'ping':
                        _is_ping = True
                except Exception:
                    _silent_log.debug("suppressed_exception", src='ws.py')

            if _is_ping:
                await websocket.send_json({"type": "pong"})
            else:
                log.debug("ws_handler_msg", msg=data[:200])
    except WebSocketDisconnect:
        log.info("ws_handler_disconnected")
    except Exception:
        _silent_log.debug("suppressed_exception", src='ws.py')


class RewindRequest(BaseModel):
    event_id: str


@router.post("/api/v3/mission/{mission_id}/rewind")
async def rewind_mission(
    mission_id: str,
    req: RewindRequest,
    x_jarvis_token: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
):
    """Time-Travel : coupe l'EventStream jusqu'à un événement précis."""
    from api.token_utils import strip_bearer as _sb
    _rewind_token = x_jarvis_token or _sb(authorization)
    if not _verify_ws_token(_rewind_token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    """Time-Travel : coupe l'EventStream jusqu'à un événement précis."""
    entry = ACTIVE_STREAMS.get(mission_id)
    stream = entry["stream"] if entry else None
    if not stream:
        raise HTTPException(status_code=404, detail=f"Mission {mission_id} introuvable.")

    success = await stream.rewind_to(req.event_id)
    if not success:
        raise HTTPException(status_code=400, detail="Event ID invalide.")

    return {"ok": True, "message": f"Time-Travel effectué vers {req.event_id}."}
