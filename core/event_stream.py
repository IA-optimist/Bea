"""
BEA MAX v3 — Event Stream
Stockage append-only immuable de tous les événements d'une mission.
Permet Time-Travel, sauvegarde JSON et subscriptions asynchrones (ex: pour WebSockets).
"""
import json
import structlog
from collections import deque
from typing import Callable, Awaitable
from pydantic import TypeAdapter

from core.events import Event

log = structlog.get_logger()

# Parseur générique pydantic pour reconstruire un Event dynamique depuis dict
EventAdapter = TypeAdapter(Event)

_MAX_EVENTS = 500   # bounded deque — prevents unbounded memory growth


class EventStream:
    def __init__(self, mission_id: str):
        self.mission_id: str = mission_id
        self._events: deque[Event] = deque(maxlen=_MAX_EVENTS)

        # Callbacks asynchrones (ex: WebSocket.send_json)
        self._subscribers: list[Callable[[Event], Awaitable[None]]] = []

    def get_events(self, start: int = 0, limit: int | None = None) -> list[Event]:
        """Récupère l'historique (converti en list pour le slicing)."""
        events_list = list(self._events)
        end = start + limit if limit else None
        return events_list[start:end]

    async def append(self, event: Event) -> None:
        """Ajoute un événement et notifie tous les abonnés."""
        self._events.append(event)
        log.debug("event_stream_append", mission_id=self.mission_id, type=type(event).__name__)

        for sub in self._subscribers:
            try:
                await sub(event)
            except Exception as e:
                log.error("event_stream_subscriber_error", err=str(e)[:80])

    def subscribe(self, callback: Callable[[Event], Awaitable[None]]) -> None:
        """Abonne un listener aux nouveaux événements (ex: API websocket)."""
        if callback not in self._subscribers:
            self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[Event], Awaitable[None]]) -> None:
        """Retire un listener."""
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    # ── Time-Travel ─────────────────────────────────────────────

    async def rewind_to(self, event_id: str) -> bool:
        """
        Supprime tous les événements APRÈS l'event_id spécifié.
        Utilisé pour le Time-Travel (revenir à un point avant une erreur fatale).
        """
        events_list = list(self._events)
        index = next((i for i, e in enumerate(events_list) if e.id == event_id), -1)
        if index == -1:
            log.warning("rewind_failed_not_found", event_id=event_id)
            return False

        dropped = len(events_list) - (index + 1)
        self._events = deque(events_list[:index + 1], maxlen=_MAX_EVENTS)
        log.info("event_stream_rewind", mission_id=self.mission_id, target_id=event_id, dropped=dropped)

        # On pourrait émettre un RewindEvent spécial ici pour prévenir la UI
        # await self.append(Event(source="system", metadata={"type": "rewind", "target": event_id}))
        return True


# ── Global mission stream registry ────────────────────────────────────────────
# Canonical registry vit ici (core). L'API (api/ws.py) y réfère via ce module
# plutôt que d'avoir sa propre copie — évite le cycle core <-> api.

import time as _time

_MISSION_STREAMS: dict[str, "EventStream"] = {}

# Registre pour l'endpoint WebSocket (TTL-based), ex-api.ws.ACTIVE_STREAMS.
ACTIVE_WS_STREAMS: dict[str, dict] = {}
_WS_STREAM_TTL_S = 3_600  # 1 hour


def register_mission_stream(mission_id: str, stream: "EventStream") -> None:
    """Register an EventStream so agents/supervisor can look it up by mission_id."""
    _MISSION_STREAMS[mission_id] = stream


def deregister_mission_stream(mission_id: str) -> None:
    """Remove a mission's EventStream from the registry."""
    _MISSION_STREAMS.pop(mission_id, None)


def get_mission_stream(mission_id: str) -> "EventStream | None":
    """Retrieve the active EventStream for a mission (returns None if not found)."""
    return _MISSION_STREAMS.get(mission_id)


def _cleanup_stale_ws_streams() -> None:
    cutoff = _time.time() - _WS_STREAM_TTL_S
    stale = [k for k, v in ACTIVE_WS_STREAMS.items() if v["ts"] < cutoff]
    for k in stale:
        log.debug("ws_stream_ttl_evicted", mission_id=k)
        ACTIVE_WS_STREAMS.pop(k, None)


def register_ws_stream(mission_id: str, stream: "EventStream") -> None:
    """Register stream for the WebSocket endpoint lookup."""
    ACTIVE_WS_STREAMS[mission_id] = {"stream": stream, "ts": _time.time()}
    _cleanup_stale_ws_streams()


def deregister_ws_stream(mission_id: str) -> None:
    ACTIVE_WS_STREAMS.pop(mission_id, None)

    # ── Persistance Basique ─────────────────────────────────────

    def to_jsonl(self) -> str:
        """Exporte le stream complet au format JSONL."""
        lines = []
        for e in self._events:
            lines.append(e.model_dump_json())
        return "\n".join(lines)

    def load_jsonl(self, jsonl_content: str) -> None:
        """Reconstruit le stream depuis du JSONL (les 500 dernières lignes si > maxlen)."""
        self._events.clear()
        for line in jsonl_content.strip().splitlines():
            if not line:
                continue
            try:
                data = json.loads(line)
                # Il faudrait instancier la sous-classe exacte.
                # Pour simplifier, on stocke un Event mais en vrai il faudrait
                # matcher les union types via Action/Observation adapters.
                # (Une factorisation fine du parseur sera nécessaire pour re-hydrater correctement)
                # Fallback natif Pydantic :
                event = Event(**data)
                self._events.append(event)
            except Exception as e:
                log.error("event_stream_load_error", err=str(e)[:80])
