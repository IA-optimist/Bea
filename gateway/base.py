"""gateway.base — contrats du gateway : MessageEvent + PlatformAdapter (ABC)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MessageEvent:
    """Un message entrant normalisé, quelle que soit la plateforme."""
    platform: str
    user_id: str
    chat_id: str
    text: str
    raw: Any = field(default=None)  # payload brut de la plateforme (debug/extension)

    def session_key(self) -> str:
        """Clé de session stable : isole les conversations par plateforme+chat."""
        return f"{self.platform}:{self.chat_id}"


class PlatformAdapter(ABC):
    """Contrat qu'implémente chaque plateforme (Telegram, Discord, ...).

    Un adaptateur sait (1) s'identifier via `name`, (2) parser un payload brut en
    `MessageEvent`, (3) envoyer une réponse. La boucle d'écoute concrète vit dans
    l'adaptateur ; le `GatewayRunner` ne dépend que de ces trois capacités.
    """

    name: str = "base"

    @abstractmethod
    async def send(self, chat_id: str, text: str) -> None:
        """Envoie `text` vers `chat_id` sur la plateforme."""

    def parse(self, raw: Any) -> MessageEvent | None:
        """Convertit un payload brut en MessageEvent (None si non pertinent).

        Implémentation par défaut : à surcharger par chaque adaptateur concret.
        """
        raise NotImplementedError
