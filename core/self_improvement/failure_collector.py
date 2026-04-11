"""
JARVIS MAX — Self-Improvement Controller V1
Module A : FailureCollector

Analyse le MissionStateStore et la MissionSystem pour produire des FailureEntry.
Persiste dans workspace/failure_log.jsonl (max 1000 lignes, rotation FIFO).
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from api.mission_store import MissionStateStore

_WORKSPACE_DIR  = Path(os.environ.get("WORKSPACE_DIR", "workspace"))
_FAILURE_LOG    = _WORKSPACE_DIR / "failure_log.jsonl"
_MAX_LOG_LINES  = 1000
_MAX_IN_MEMORY  = 100


@dataclass
class FailureEntry:
    issue_id:           str
    timestamp:          str
    mission_id:         str
    agent_name:         str          # "" si système
    severity:           str          # "low" | "medium" | "high" | "critical"
    category:           str          # voir catégories ci-dessous
    symptom:            str
    probable_root_cause: str
    evidence:           str
    affected_files:     list[str]    = field(default_factory=list)
    reproducible:       bool         = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "FailureEntry":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


class FailureCollector:
    """
    Analyse les missions du MissionStateStore et détecte les anomalies.
    Produit des FailureEntry structurées.
    """

    def __init__(self) -> None:
        self._entries: list[FailureEntry] = []

    # ── API publique ──────────────────────────────────────────────────────────

    def collect_from_store(self, mission_store: "MissionStateStore") -> list[FailureEntry]:
        """
        Analyse toutes les missions du store et retourne les FailureEntry détectées.
        Persiste dans failure_log.jsonl.
        """
        new_entries: list[FailureEntry] = []

        # Récupérer les missions depuis MissionSystem
        missions_by_id: dict = {}
        try:
            from core.mission_system import get_mission_system
            ms = get_mission_system()
            for m in ms.list_missions(limit=200):
                missions_by_id[m.mission_id] = m
        except Exception:
            _silent_log.debug("suppressed_exception", src='failure_collector.py')

        for mission_id, mission in missions_by_id.items():
            events = mission_store.get_log(mission_id)
            entries = self._analyze_mission(mission_id, mission, events)
            new_entries.extend(entries)

        # Mise à jour mémoire (max 100)
        self._entries = (self._entries + new_entries)[-_MAX_IN_MEMORY:]

        # Persistance FIFO
        if new_entries:
            self._persist(new_entries)

        return new_entries

    def get_recent(self, limit: int = 20) -> list[FailureEntry]:
        """Retourne les N dernières failures en mémoire."""
        return self._entries[-limit:]

    def load_from_disk(self, limit: int = 100) -> list[FailureEntry]:
        """Charge les dernières failures depuis le fichier JSONL."""
        entries: list[FailureEntry] = []
        try:
            if not _FAILURE_LOG.exists():
                return entries
            lines = _FAILURE_LOG.read_text("utf-8").strip().splitlines()
            for line in lines[-limit:]:
                try:
                    entries.append(FailureEntry.from_dict(json.loads(line)))
                except Exception:
                    _silent_log.debug("suppressed_exception", src='failure_collector.py')
        except Exception:
            _silent_log.debug("suppressed_exception", src='failure_collector.py')
        return entries

    # ── Analyse ───────────────────────────────────────────────────────────────

    def _analyze_mission(self, mission_id: str, mission, events: list) -> list[FailureEntry]:
        found: list[FailureEntry] = []

        final_output = getattr(mission, "final_output", "") or ""
        status       = getattr(mission, "status", "")
        complexity   = getattr(mission, "complexity", "medium")
        agents_sel   = getattr(mission, "agents_selected", []) or []
        created_at   = getattr(mission, "created_at", 0.0) or 0.0
        updated_at   = getattr(mission, "updated_at", 0.0) or 0.0

        # 1. final_output vide sur mission terminée (DONE)
        if str(status) in ("DONE", "MissionStatus.DONE") and not final_output.strip():
            found.append(self._make_entry(
                mission_id=mission_id,
                agent_name="",
                severity="high",
                category="empty_output",
                symptom="Mission DONE mais final_output vide ou absent",
                cause="emit_agent_result non appelé ou résultat non propagé dans set_final_output()",
                evidence=f"status={status}, final_output='{final_output[:100]}'",
            ))

        # 2. over_agents : > 4 agents sur mission complexity=low
        if len(agents_sel) > 4 and str(complexity).lower() == "low":
            found.append(self._make_entry(
                mission_id=mission_id,
                agent_name="",
                severity="medium",
                category="over_agents",
                symptom=f"{len(agents_sel)} agents sélectionnés pour complexité=low",
                cause="compute_complexity() sous-estime ou AgentSelector ignore la complexité",
                evidence=f"agents_selected={agents_sel}, complexity={complexity}",
                affected_files=["core/mission_system.py", "agents/crew.py"],
            ))

        # 3. timeout : durée > 60s (updated_at - created_at)
        if created_at and updated_at:
            duration_s = updated_at - created_at
            if duration_s > 60:
                found.append(self._make_entry(
                    mission_id=mission_id,
                    agent_name="",
                    severity="medium",
                    category="timeout",
                    symptom=f"Mission durée {duration_s:.1f}s > 60s",
                    cause="LLM lent ou agent bloqué sans circuit breaker actif",
                    evidence=f"created_at={created_at:.0f}, updated_at={updated_at:.0f}, duration={duration_s:.1f}s",
                ))

        # 4. Analyse des events
        error_event_count = 0
        for ev in events:
            ev_type = getattr(ev, "event_type", None)
            ev_type_str = ev_type.value if hasattr(ev_type, "value") else str(ev_type)
            agent_id = getattr(ev, "agent_id", "") or ""
            data = getattr(ev, "data", {}) or {}
            message = getattr(ev, "message", "") or ""

            # agent_failure : event_type ERROR (AGENT_FAILED)
            if ev_type_str == "error":
                error_event_count += 1
                found.append(self._make_entry(
                    mission_id=mission_id,
                    agent_name=agent_id,
                    severity="high",
                    category="agent_failure",
                    symptom=f"Agent {agent_id or 'inconnu'} a échoué",
                    cause="Exception non gérée dans BaseAgent.run() ou timeout",
                    evidence=message[:200],
                    affected_files=[f"agents/crew.py"],
                ))

            # json_parse_error : tentative de parse JSON échouée (heuristique)
            if "json" in message.lower() and ("error" in message.lower() or "invalid" in message.lower()):
                found.append(self._make_entry(
                    mission_id=mission_id,
                    agent_name=agent_id,
                    severity="low",
                    category="json_parse_error",
                    symptom="Erreur de parsing JSON dans un agent",
                    cause="Agent retourne du texte non-JSON alors qu'un JSON était attendu",
                    evidence=message[:200],
                ))

        # 5. memory_overflow : > 400 events dans la mission
        if len(events) > 400:
            found.append(self._make_entry(
                mission_id=mission_id,
                agent_name="",
                severity="medium",
                category="memory_overflow",
                symptom=f"{len(events)} events dans la mission (> 400)",
                cause="Mission longue ou boucle d'événements — risque de perte d'events (cap 500)",
                evidence=f"events_count={len(events)}",
                affected_files=["api/mission_store.py"],
            ))

        return found

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _make_entry(
        self,
        mission_id: str,
        agent_name: str,
        severity: str,
        category: str,
        symptom: str,
        cause: str,
        evidence: str,
        affected_files: list[str] | None = None,
    ) -> FailureEntry:
        return FailureEntry(
            issue_id=str(uuid.uuid4())[:8],
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            mission_id=mission_id,
            agent_name=agent_name,
            severity=severity,
            category=category,
            symptom=symptom,
            probable_root_cause=cause,
            evidence=evidence,
            affected_files=affected_files or [],
            reproducible=True,
        )

    # ── Persistance ───────────────────────────────────────────────────────────

    def _persist(self, entries: list[FailureEntry]) -> None:
        try:
            _FAILURE_LOG.parent.mkdir(parents=True, exist_ok=True)

            # Lire les lignes existantes
            existing: list[str] = []
            if _FAILURE_LOG.exists():
                existing = _FAILURE_LOG.read_text("utf-8").strip().splitlines()

            # Ajouter les nouvelles
            new_lines = [json.dumps(e.to_dict(), ensure_ascii=False) for e in entries]
            all_lines = existing + new_lines

            # Rotation FIFO : max 1000 lignes
            if len(all_lines) > _MAX_LOG_LINES:
                all_lines = all_lines[-_MAX_LOG_LINES:]

            _FAILURE_LOG.write_text("\n".join(all_lines) + "\n", "utf-8")
        except Exception:
            pass  # fail-open
