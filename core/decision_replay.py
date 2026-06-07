"""
BEA MAX — DecisionReplay
Permet de rejouer une session, comprendre les décisions et analyser les erreurs.

Rôle :
    Enregistre chaque décision importante de l'orchestrateur pour :
    1. Rejouer une session (dry-run) et comparer avec l'original
    2. Comprendre pourquoi un agent a été choisi
    3. Analyser les erreurs post-mortem
    4. Générer des explications pour l'utilisateur

Chaque "décision" est un événement structuré :
    - ROUTE    : choix de mode/agent par le TaskRouter
    - AGENT    : démarrage d'un agent
    - ACTION   : action préparée par PulseOps
    - MEMORY   : rappel ou stockage mémoire
    - EVAL     : évaluation d'une sortie
    - ERROR    : erreur survenue
    - IMPROVE  : patch généré/appliqué

Usage :
    replay = DecisionReplay(settings)

    # Enregistrer une décision
    replay.record(session_id, "AGENT", {
        "agent": "forge-builder",
        "task": "Générer le script de backup",
        "complexity": 0.72,
    })

    # Obtenir l'historique d'une session
    events = replay.get_session(session_id)

    # Rapport lisible
    report = replay.explain_session(session_id)
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
import structlog

log = structlog.get_logger()

_REPLAY_FILE  = "decision_replay.json"
_MAX_SESSIONS = 50    # sessions gardées
_MAX_EVENTS   = 200   # événements par session

# Types d'événements
EVENT_ROUTE   = "ROUTE"
EVENT_AGENT   = "AGENT"
EVENT_ACTION  = "ACTION"
EVENT_MEMORY  = "MEMORY"
EVENT_EVAL    = "EVAL"
EVENT_ERROR   = "ERROR"
EVENT_IMPROVE = "IMPROVE"
EVENT_PLAN    = "PLAN"
EVENT_RESULT  = "RESULT"


@dataclass
class DecisionEvent:
    """Un événement décisionnel dans une session."""
    id:         str
    session_id: str
    event_type: str
    ts:         float
    data:       dict = field(default_factory=dict)
    duration_ms: float = 0.0
    success:    bool  = True
    error:      str   = ""

    def to_dict(self) -> dict:
        return {
            "id":          self.id,
            "session_id":  self.session_id,
            "event_type":  self.event_type,
            "ts":          self.ts,
            "age_s":       round(time.time() - self.ts, 1),
            "data":        self.data,
            "duration_ms": self.duration_ms,
            "success":     self.success,
            "error":       self.error[:100] if self.error else "",
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DecisionEvent":
        return cls(
            id          = d.get("id", ""),
            session_id  = d.get("session_id", ""),
            event_type  = d.get("event_type", "UNKNOWN"),
            ts          = d.get("ts", time.time()),
            data        = d.get("data", {}),
            duration_ms = d.get("duration_ms", 0.0),
            success     = d.get("success", True),
            error       = d.get("error", ""),
        )


# ══════════════════════════════════════════════════════════════
# DECISION REPLAY
# ══════════════════════════════════════════════════════════════

class DecisionReplay:
    """
    Enregistreur et analyseur de décisions BeaMax.
    Persiste dans workspace/decision_replay.json.
    """

    def __init__(self, settings):
        self.s        = settings
        self._path    = self._resolve_path()
        self._sessions: dict[str, list[DecisionEvent]] = {}
        self._loaded  = False

    def _resolve_path(self) -> Path:
        base = Path(getattr(self.s, "workspace_dir", "/app/workspace"))
        base.mkdir(parents=True, exist_ok=True)
        return base / _REPLAY_FILE

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            if self._path.exists():
                raw = json.loads(self._path.read_text("utf-8"))
                for sid, events in raw.items():
                    self._sessions[sid] = [
                        DecisionEvent.from_dict(e) for e in events
                    ]
                log.debug("decision_replay_loaded", sessions=len(self._sessions))
        except Exception as e:
            log.warning("decision_replay_load_error", err=str(e))

    def _save(self) -> None:
        try:
            # Garder seulement les N dernières sessions
            recent = dict(list(self._sessions.items())[-_MAX_SESSIONS:])
            data   = {
                sid: [e.to_dict() for e in events[-_MAX_EVENTS:]]
                for sid, events in recent.items()
            }
            self._path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            log.warning("decision_replay_save_error", err=str(e))

    # ── API publique ──────────────────────────────────────

    def record(
        self,
        session_id:  str,
        event_type:  str,
        data:        dict | None = None,
        duration_ms: float = 0.0,
        success:     bool  = True,
        error:       str   = "",
    ) -> DecisionEvent:
        """Enregistre un événement décisionnel."""
        self._load()

        event = DecisionEvent(
            id          = str(uuid.uuid4())[:8],
            session_id  = session_id,
            event_type  = event_type,
            ts          = time.time(),
            data        = data or {},
            duration_ms = duration_ms,
            success     = success,
            error       = error,
        )

        if session_id not in self._sessions:
            self._sessions[session_id] = []

        events = self._sessions[session_id]
        events.append(event)

        # Limiter par session
        if len(events) > _MAX_EVENTS:
            self._sessions[session_id] = events[-_MAX_EVENTS:]

        # Persister de façon asynchrone (fire-and-forget)
        # → on sauvegarde toutes les 10 events pour éviter le spam I/O
        if len(events) % 10 == 0:
            self._save()

        return event

    def get_session(self, session_id: str) -> list[DecisionEvent]:
        """Retourne tous les événements d'une session."""
        self._load()
        return list(self._sessions.get(session_id, []))

    def explain_session(self, session_id: str) -> str:
        """
        Génère une explication lisible du déroulement d'une session.
        Utile pour le débogage et les explications utilisateur.
        """
        events = self.get_session(session_id)
        if not events:
            return f"Aucune donnée pour la session {session_id}"

        lines = [f"=== Replay Session {session_id} ==="]
        lines.append(f"Événements : {len(events)}")

        first_ts = events[0].ts if events else time.time()

        for ev in events:
            age     = round(ev.ts - first_ts, 1)
            status  = "OK" if ev.success else "FAIL"
            ms_str  = f" ({ev.duration_ms:.0f}ms)" if ev.duration_ms else ""
            err_str = f" | ERR: {ev.error[:60]}" if ev.error else ""

            # Résumé selon le type
            detail = self._summarize_event(ev)
            lines.append(f"  +{age:6.1f}s [{status}] {ev.event_type:<10} {detail}{ms_str}{err_str}")

        # Résumé final
        errors = [e for e in events if not e.success]
        lines.append(f"\nBilan: {len(events) - len(errors)} succes | {len(errors)} echecs")

        return "\n".join(lines)

    def get_recent_sessions(self, n: int = 10) -> list[dict]:
        """Retourne les N sessions les plus récentes avec résumé."""
        self._load()
        result = []
        for sid, events in list(self._sessions.items())[-n:]:
            if not events:
                continue
            first = events[0]
            last  = events[-1]
            errors = sum(1 for e in events if not e.success)
            result.append({
                "session_id": sid,
                "started_at": first.ts,
                "ended_at":   last.ts,
                "duration_s": round(last.ts - first.ts, 1),
                "events":     len(events),
                "errors":     errors,
                "mode":       first.data.get("mode", "?"),
            })
        return sorted(result, key=lambda x: x["started_at"], reverse=True)[:n]

    def get_errors(self, n: int = 20) -> list[dict]:
        """Retourne les N erreurs les plus récentes toutes sessions confondues."""
        self._load()
        all_errors = []
        for events in self._sessions.values():
            for ev in events:
                if not ev.success and ev.event_type not in (EVENT_MEMORY,):
                    all_errors.append(ev.to_dict())

        return sorted(all_errors, key=lambda x: x["ts"], reverse=True)[:n]

    def clear_session(self, session_id: str) -> None:
        """Supprime les événements d'une session."""
        if session_id in self._sessions:
            del self._sessions[session_id]
            self._save()

    def clear(self) -> None:
        """Vide tout l'historique (pour tests)."""
        self._sessions.clear()
        self._save()

    def flush(self) -> None:
        """Force la sauvegarde immédiate."""
        self._save()

    # ── Helpers ───────────────────────────────────────────

    def _summarize_event(self, ev: DecisionEvent) -> str:
        """Résumé court d'un événement selon son type."""
        d = ev.data
        if ev.event_type == EVENT_ROUTE:
            return f"mode={d.get('mode','?')} complexity={d.get('complexity',0):.2f}"
        if ev.event_type == EVENT_AGENT:
            return f"agent={d.get('agent','?')} task={str(d.get('task',''))[:40]}"
        if ev.event_type == EVENT_ACTION:
            return f"type={d.get('action_type','?')} target={d.get('target','?')[:30]}"
        if ev.event_type == EVENT_MEMORY:
            return f"op={d.get('op','?')} backend={d.get('backend','?')}"
        if ev.event_type == EVENT_EVAL:
            return f"agent={d.get('agent','?')} score={d.get('score',0):.1f}"
        if ev.event_type == EVENT_IMPROVE:
            return f"patch={d.get('patch_id','?')} result={d.get('result','?')}"
        if ev.event_type == EVENT_PLAN:
            return f"planner={d.get('planner','?')} agents={d.get('agents',[])}".replace("'","")
        if ev.event_type == EVENT_RESULT:
            return f"status={d.get('status','?')} agents_ok={d.get('agents_ok',0)}"
        if ev.event_type == EVENT_ERROR:
            return f"{d.get('error','?')[:50]}"
        return str(d)[:60]
