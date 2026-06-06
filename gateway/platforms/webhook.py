"""webhook — adaptateur générique : reçoit un payload JSON et le normalise.

Permet d'agir depuis n'importe quelle plateforme via un webhook HTTP, sans lib
spécifique (Telegram/Discord/Signal natifs = adaptateurs dédiés ultérieurs). Le
mapping des champs est configurable pour s'adapter à des payloads variés.
L'envoi sortant est délégué à un `sender` injecté (callable), gardant l'adaptateur
testable et sans dépendance réseau.
"""
from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, Optional

from gateway.base import MessageEvent, PlatformAdapter


def _dig(payload: dict, path: str) -> Any:
    """Accès par chemin pointé : 'message.from.id' → payload['message']['from']['id']."""
    cur: Any = payload
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


class WebhookAdapter(PlatformAdapter):
    name = "webhook"

    def __init__(
        self,
        sender: Optional[Callable[[str, str], Any]] = None,
        user_field: str = "user_id",
        chat_field: str = "chat_id",
        text_field: str = "text",
    ) -> None:
        self._sender = sender
        self._user_field = user_field
        self._chat_field = chat_field
        self._text_field = text_field

    def parse(self, raw: Any) -> Optional[MessageEvent]:
        if not isinstance(raw, dict):
            return None
        text = _dig(raw, self._text_field)
        if text is None or str(text).strip() == "":
            return None
        user_id = _dig(raw, self._user_field)
        chat_id = _dig(raw, self._chat_field)
        return MessageEvent(
            platform=self.name,
            user_id=str(user_id) if user_id is not None else "",
            chat_id=str(chat_id) if chat_id is not None else str(user_id or ""),
            text=str(text),
            raw=raw,
        )

    async def send(self, chat_id: str, text: str) -> None:
        if self._sender is None:
            return
        result = self._sender(chat_id, text)
        if inspect.isawaitable(result):
            await result
