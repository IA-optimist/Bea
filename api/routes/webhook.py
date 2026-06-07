"""Webhook générique — présence multi-plateforme (inspiration OpenClaw).

N'importe quelle plateforme (Discord, Signal, OpenClaw, un cron…) peut POSTer un
payload JSON ici : il est normalisé par `WebhookAdapter` (mapping de champs
configurable) puis routé via le `GatewayRunner` vers la cognition de Béa. La même
abstraction gateway que Telegram, sans lib spécifique.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Header

from api._deps import _check_auth
from gateway.platforms.webhook import WebhookAdapter
from gateway.runner import GatewayRunner

router = APIRouter(prefix="/api/v3", tags=["webhook"])


async def _cognition_handler(event) -> str:
    """Route le message normalisé vers l'orchestrateur de cognition de Béa."""
    from api.routes.chat import _get_orchestrator

    orch = _get_orchestrator()
    mission = {
        "mission_id": f"webhook-{datetime.now(timezone.utc).timestamp()}",
        "goal": event.text,
        "context": {"source": event.platform, "user_id": event.user_id,
                    "conversation_history": []},
    }
    result = await orch.execute_with_project_context(
        mission, project_id=None, enable_tot=False,
        enable_confidence=True, enable_learning=True)
    return result.get("result", "") if isinstance(result, dict) else str(result)


@router.post("/webhook")
async def webhook(
    payload: dict,
    x_bea_token: Annotated[Optional[str], Header()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Entrée générique. Payload mappé (`user_id`/`chat_id`/`text` par défaut) puis
    routé via GatewayRunner -> cognition. Renvoie {ok, response, platform}."""
    _check_auth(x_bea_token, authorization)
    adapter = WebhookAdapter()
    runner = GatewayRunner(handler=_cognition_handler, allowlist=None)
    runner.register(adapter)
    event = adapter.parse(payload)
    if event is None:
        return {"ok": False, "error": "payload invalide (champ 'text' requis)"}
    response = await runner.handle(event)
    return {"ok": True, "response": response, "platform": event.platform}
