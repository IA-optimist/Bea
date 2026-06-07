"""
BEA MAX — Self-Improvement Controller V1
Module B : ImprovementPlanner

Analyse les FailureEntry et génère des ImprovementProposal rule-based (sans LLM).
Persiste dans workspace/improvement_proposals.json (max 50, FIFO).
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from core.self_improvement.failure_collector import FailureEntry

_WORKSPACE_DIR     = Path(os.environ.get("WORKSPACE_DIR", "workspace"))
_PROPOSALS_PATH    = _WORKSPACE_DIR / "improvement_proposals.json"
_MAX_PROPOSALS     = 50

# Mots interdits dans fix_proposed
_FORBIDDEN_WORDS = (
    "refonte", "migration DB", "architecture globale",
    "supprimer sécurité", "refactor complet",
)


@dataclass
class ImprovementProposal:
    proposal_id:     str
    created_at:      str
    problem:         str
    probable_cause:  str
    fix_proposed:    str
    files_to_modify: list[str]    = field(default_factory=list)
    risk_level:      str          = "low"    # "low" | "medium" | "high"
    expected_impact: str          = ""
    ram_cpu_cost:    str          = "negligible"  # "negligible" | "low" | "medium" | "high"
    tests_required:  list[str]    = field(default_factory=list)
    rollback_plan:   str          = ""
    confidence_score: float       = 0.5      # 0.0 → 1.0
    status:          str          = "pending"  # "pending" | "approved" | "rejected" | "applied"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ImprovementProposal":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


class ImprovementPlanner:
    """
    Génère des ImprovementProposal à partir de FailureEntry.
    Logique entièrement rule-based — pas de LLM.
    """

    def plan_from_failures(self, failures: list[FailureEntry]) -> list[ImprovementProposal]:
        """
        Analyse les failures et retourne des proposals non-dupliquées.
        Persiste dans improvement_proposals.json.
        """
        proposals: list[ImprovementProposal] = []
        seen_categories: set[str] = set()

        for failure in failures:
            # Dédupliquer par catégorie (une proposition par type de problème)
            key = f"{failure.category}:{failure.agent_name}"
            if key in seen_categories:
                continue
            seen_categories.add(key)

            p = self._generate_proposal(failure)
            if p is not None:
                proposals.append(p)

        if proposals:
            self._persist(proposals)

        return proposals

    def load_proposals(self, limit: int = 50) -> list[ImprovementProposal]:
        """Charge les proposals depuis le fichier JSON."""
        try:
            if not _PROPOSALS_PATH.exists():
                return []
            data = json.loads(_PROPOSALS_PATH.read_text("utf-8"))
            items = data if isinstance(data, list) else []
            return [ImprovementProposal.from_dict(d) for d in items[-limit:]]
        except Exception:
            return []

    # ── Génération rule-based ─────────────────────────────────────────────────

    def _generate_proposal(self, failure: FailureEntry) -> ImprovementProposal | None:
        cat = failure.category

        if cat == "empty_output":
            fix = (
                "Vérifier que emit_agent_result est bien appelé dans l'agent concerné, "
                "et que set_final_output() reçoit le résultat non-vide."
            )
            p = ImprovementProposal(
                proposal_id=str(uuid.uuid4())[:8],
                created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                problem=f"Mission {failure.mission_id[:8]} terminée avec final_output vide",
                probable_cause=failure.probable_root_cause,
                fix_proposed=fix,
                files_to_modify=["api/event_emitter.py", "api/main.py"],
                risk_level="low",
                expected_impact="Élimination des réponses vides — meilleure UX",
                ram_cpu_cost="negligible",
                tests_required=["test_mission_simple", "test_final_output_not_empty"],
                rollback_plan="Aucun rollback requis — ajout de vérification seulement",
                confidence_score=0.8,
            )

        elif cat == "over_agents":
            fix = (
                "Ajuster compute_complexity() pour mieux détecter les requêtes simples, "
                "ou ajouter un cap max_agents=2 pour complexity=low dans AgentSelector."
            )
            p = ImprovementProposal(
                proposal_id=str(uuid.uuid4())[:8],
                created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                problem=f"Mission {failure.mission_id[:8]} : trop d'agents pour complexity=low",
                probable_cause=failure.probable_root_cause,
                fix_proposed=fix,
                files_to_modify=["core/mission_system.py"],
                risk_level="low",
                expected_impact="Réduction latence et coût LLM sur les requêtes simples",
                ram_cpu_cost="negligible",
                tests_required=["test_capability_query", "test_simple_mission_agent_count"],
                rollback_plan="Annuler la modification de compute_complexity() ou du cap",
                confidence_score=0.9,
            )

        elif cat == "timeout":
            fix = (
                "Ajouter un timeout explicite de 30s par agent dans BaseAgent.run() "
                "via asyncio.wait_for(), et activer le circuit breaker Ollama."
            )
            p = ImprovementProposal(
                proposal_id=str(uuid.uuid4())[:8],
                created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                problem=f"Mission {failure.mission_id[:8]} durée > 60s",
                probable_cause=failure.probable_root_cause,
                fix_proposed=fix,
                files_to_modify=["agents/crew.py", "core/llm_factory.py"],
                risk_level="medium",
                expected_impact="Réduction des timeouts non gérés, UX plus réactive",
                ram_cpu_cost="negligible",
                tests_required=["test_health", "test_mission_simple"],
                rollback_plan="Supprimer le wrapper asyncio.wait_for() ajouté",
                confidence_score=0.7,
            )

        elif cat == "agent_failure":
            agent = failure.agent_name or "inconnu"
            fix = (
                f"Vérifier les logs de l'agent '{agent}' — s'assurer que emit_agent_result "
                f"est appelé même en cas d'erreur, et que le fallback cloud est actif."
            )
            p = ImprovementProposal(
                proposal_id=str(uuid.uuid4())[:8],
                created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                problem=f"Agent '{agent}' a échoué dans mission {failure.mission_id[:8]}",
                probable_cause=failure.probable_root_cause,
                fix_proposed=fix,
                files_to_modify=["agents/crew.py"],
                risk_level="low",
                expected_impact="Résilience accrue — moins de missions en échec silencieux",
                ram_cpu_cost="negligible",
                tests_required=["test_mission_simple", "test_health"],
                rollback_plan="Revenir au comportement précédent (sans le fix d'erreur)",
                confidence_score=0.75,
            )

        elif cat == "memory_overflow":
            fix = (
                "Activer une rotation automatique des events en cours de mission "
                "(warning à 300 events, purge des AGENT_PROGRESS anciens > 200 events)."
            )
            p = ImprovementProposal(
                proposal_id=str(uuid.uuid4())[:8],
                created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                problem=f"Mission {failure.mission_id[:8]} : {failure.evidence}",
                probable_cause=failure.probable_root_cause,
                fix_proposed=fix,
                files_to_modify=["api/mission_store.py"],
                risk_level="low",
                expected_impact="Prévention de la perte d'events importants (cap 500)",
                ram_cpu_cost="negligible",
                tests_required=["test_ram_bounds", "test_api_missions_list"],
                rollback_plan="Désactiver la rotation intermédiaire (garder seulement le cap 500)",
                confidence_score=0.8,
            )

        elif cat == "json_parse_error":
            fix = (
                "Ajouter un fallback text dans le parseur de réponse d'agent "
                "pour accepter les réponses non-JSON."
            )
            p = ImprovementProposal(
                proposal_id=str(uuid.uuid4())[:8],
                created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                problem=f"Erreur JSON parse dans agent {failure.agent_name or 'inconnu'}",
                probable_cause=failure.probable_root_cause,
                fix_proposed=fix,
                files_to_modify=["api/event_emitter.py"],
                risk_level="low",
                expected_impact="Moins d'erreurs silencieuses sur les sorties non-JSON",
                ram_cpu_cost="negligible",
                tests_required=["test_mission_simple"],
                rollback_plan="Revenir au parser strict",
                confidence_score=0.7,
            )

        else:
            # Catégorie inconnue — proposal générique
            fix = f"Investiguer la catégorie '{cat}' — voir evidence: {failure.evidence[:100]}"
            p = ImprovementProposal(
                proposal_id=str(uuid.uuid4())[:8],
                created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                problem=failure.symptom,
                probable_cause=failure.probable_root_cause,
                fix_proposed=fix,
                files_to_modify=failure.affected_files,
                risk_level="low",
                expected_impact="À évaluer",
                ram_cpu_cost="negligible",
                tests_required=["test_health"],
                rollback_plan="Aucun changement appliqué automatiquement",
                confidence_score=0.4,
            )

        # Vérifier les mots interdits
        if self._has_forbidden_words(p.fix_proposed):
            return None

        return p

    def _has_forbidden_words(self, text: str) -> bool:
        t = text.lower()
        return any(w.lower() in t for w in _FORBIDDEN_WORDS)

    # ── Persistance ───────────────────────────────────────────────────────────

    def _persist(self, new_proposals: list[ImprovementProposal]) -> None:
        try:
            _PROPOSALS_PATH.parent.mkdir(parents=True, exist_ok=True)

            existing: list[dict] = []
            if _PROPOSALS_PATH.exists():
                try:
                    data = json.loads(_PROPOSALS_PATH.read_text("utf-8"))
                    existing = data if isinstance(data, list) else []
                except Exception:
                    existing = []

            combined = existing + [p.to_dict() for p in new_proposals]

            # FIFO : max 50
            if len(combined) > _MAX_PROPOSALS:
                combined = combined[-_MAX_PROPOSALS:]

            _PROPOSALS_PATH.write_text(
                json.dumps(combined, indent=2, ensure_ascii=False), "utf-8"
            )
        except Exception:
            import logging as _lg; _lg.getLogger(__name__).debug("swallowed_exception", exc_info=True)
