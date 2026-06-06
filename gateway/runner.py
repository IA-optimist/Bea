"""gateway.runner — GatewayRunner : autorisation, routage de session, dispatch.

Le runner est agnostique de la plateforme et du cœur agent : on lui injecte un
`handler` (`MessageEvent -> str|Awaitable[str]`) qui encapsule l'appel à
`meta_orchestrator` (étape opt-in). Il applique une allowlist d'utilisateurs et
renvoie la réponse via l'adaptateur d'origine.
"""
from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import Optional, Union

from gateway.base import MessageEvent, PlatformAdapter

logger = logging.getLogger(__name__)

Handler = Callable[[MessageEvent], Union[str, Awaitable[str]]]

_UNAUTHORIZED_MSG = "Accès non autorisé."
_ERROR_MSG = "Une erreur interne est survenue."


class GatewayRunner:
    """Route les messages entrants vers le handler, avec garde d'autorisation."""

    def __init__(
        self,
        handler: Handler,
        allowlist: Optional[set[str]] = None,
    ) -> None:
        self._handler = handler
        # allowlist None => tout autorisé (dev) ; set (même vide) => restreint
        self._allowlist = allowlist
        self._adapters: dict[str, PlatformAdapter] = {}

    def register(self, adapter: PlatformAdapter) -> None:
        self._adapters[adapter.name] = adapter

    def is_authorized(self, user_id: str) -> bool:
        if self._allowlist is None:
            return True
        return user_id in self._allowlist

    async def handle(self, event: MessageEvent) -> Optional[str]:
        """Autorise puis exécute le handler ; renvoie la réponse texte (ou None)."""
        if not self.is_authorized(event.user_id):
            logger.info("gateway_unauthorized", extra={"user": event.user_id,
                                                        "platform": event.platform})
            return _UNAUTHORIZED_MSG
        try:
            resp = self._handler(event)
            if inspect.isawaitable(resp):
                resp = await resp
            return str(resp) if resp is not None else None
        except Exception:
            logger.debug("gateway_handler_failed", exc_info=True)
            return _ERROR_MSG

    async def dispatch(self, event: MessageEvent) -> Optional[str]:
        """Traite l'événement et renvoie la réponse via l'adaptateur d'origine."""
        response = await self.handle(event)
        if response is None:
            return None
        adapter = self._adapters.get(event.platform)
        if adapter is not None:
            try:
                await adapter.send(event.chat_id, response)
            except Exception:
                logger.debug("gateway_send_failed", exc_info=True)
        return response
