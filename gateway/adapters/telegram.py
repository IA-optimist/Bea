"""Adaptateur Telegram pour le gateway Béa (long-polling, usage dev/test).

Implémente le contrat `PlatformAdapter` : parse un update Telegram en `MessageEvent`
et envoie une réponse via l'API Bot. Le token vient de l'environnement
(`TELEGRAM_BOT_TOKEN`), jamais en dur.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

from gateway.base import MessageEvent, PlatformAdapter

_TELEGRAM_MAX = 4096  # limite Telegram par message


class TelegramAdapter(PlatformAdapter):
    name = "telegram"

    def __init__(self, token: str | None = None, timeout: float = 30.0) -> None:
        self.token = token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.timeout = timeout

    def parse(self, raw: Any) -> MessageEvent | None:
        """Update Telegram (dict) -> MessageEvent. None si pas un message texte."""
        if not isinstance(raw, dict):
            return None
        msg = raw.get("message") or raw.get("edited_message")
        if not msg:
            return None
        text = msg.get("text")
        if not text:
            return None
        chat_id = str(msg.get("chat", {}).get("id", ""))
        user_id = str(msg.get("from", {}).get("id", ""))
        if not chat_id:
            return None
        return MessageEvent(platform=self.name, user_id=user_id,
                            chat_id=chat_id, text=text, raw=raw)

    async def send(self, chat_id: str, text: str) -> None:
        """Envoie `text` à `chat_id` (découpé si > limite Telegram)."""
        text = text or "(réponse vide)"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for i in range(0, len(text), _TELEGRAM_MAX - 96):
                chunk = text[i:i + _TELEGRAM_MAX - 96]
                await client.post(
                    f"{self.base_url}/sendMessage",
                    json={"chat_id": chat_id, "text": chunk},
                )
