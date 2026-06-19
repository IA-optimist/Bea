"""
BEA MAX — Agent Contracts (Phase 3)
========================================
Schéma I/O standardisé pour tous les agents de BeaMax.

Règle : tout agent doit pouvoir produire un AgentContract via run_structured().
Les méthodes run() existantes sont conservées — run_structured() est additif.

Schémas :
    AgentContract   - sortie structurée canonique d'un agent
    ReviewResult    - résultat d'une peer review inter-agents
    DELEGATION_MAP  - graphe de délégation recommandée (agent → next agent)
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum


# ─────────────────────────────────────────────────────────────────────────────
# Status
# ─────────────────────────────────────────────────────────────────────────────

class AgentStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    ERROR   = "error"
    SKIPPED = "skipped"


# ─────────────────────────────────────────────────────────────────────────────
# AgentContract — sortie canonique d'un agent
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AgentContract:
    """
    Sortie structurée canonique de tout agent BeaMax.

    Champs obligatoires :
        agent_id    - nom de l'agent (ex: "scout-research")
        mission_id  - ID de la mission en cours
        output      - contenu produit par l'agent
        status      - AgentStatus enum

    Champs calculés / enrichis :
        confidence          - score de confiance 0.0–1.0
        reasoning_summary   - résumé du raisonnement de l'agent
        used_memory         - IDs des entrées mémoire utilisées
        generated_memory    - IDs des entrées mémoire créées
        next_recommended_agent - suggestion de délégation
        risk_level          - low | medium | high
        duration_ms         - temps d'exécution
        metadata            - dict arbitraire
    """
    agent_id:                str
    mission_id:              str
    output:                  str
    status:                  AgentStatus = AgentStatus.SUCCESS

    confidence:              float       = 1.0
    reasoning_summary:       str         = ""
    used_memory:             list[str]   = field(default_factory=list)
    generated_memory:        list[str]   = field(default_factory=list)
    next_recommended_agent:  str         = ""
    risk_level:              str         = "low"
    duration_ms:             int         = 0
    error:                   str         = ""
    metadata:                dict[str, object] = field(default_factory=dict)

    # Auto
    id:                      str         = field(default_factory=lambda: str(uuid.uuid4())[:10])
    timestamp:               float       = field(default_factory=time.time)

    @property
    def success(self) -> bool:
        return self.status == AgentStatus.SUCCESS

    @property
    def needs_review(self) -> bool:
        """True si la confiance est faible et une peer-review est recommandée."""
        return self.confidence < 0.65 or self.status == AgentStatus.PARTIAL

    def to_dict(self) -> dict[str, object]:
        return {
            "id":                      self.id,
            "agent_id":                self.agent_id,
            "mission_id":              self.mission_id,
            "status":                  self.status.value,
            "output":                  self.output[:2000],  # capped for serialization
            "confidence":              round(self.confidence, 3),
            "reasoning_summary":       self.reasoning_summary[:300],
            "used_memory":             self.used_memory,
            "generated_memory":        self.generated_memory,
            "next_recommended_agent":  self.next_recommended_agent,
            "risk_level":              self.risk_level,
            "duration_ms":             self.duration_ms,
            "error":                   self.error,
            "metadata":                self.metadata,
            "timestamp":               self.timestamp,
        }

    @classmethod
    def from_raw(
        cls,
        agent_id:   str,
        mission_id: str,
        output:     str,
        success:    bool  = True,
        error:      str   = "",
        duration_ms: int  = 0,
    ) -> "AgentContract":
        """
        Crée un AgentContract minimal depuis les données brutes de BaseAgent.run().
        Utilisé pour la migration progressive des agents existants.
        """
        status = AgentStatus.SUCCESS if success else AgentStatus.ERROR
        conf   = 0.8 if success else 0.0
        return cls(
            agent_id    = agent_id,
            mission_id  = mission_id,
            output      = output,
            status      = status,
            confidence  = conf,
            error       = error,
            duration_ms = duration_ms,
            next_recommended_agent = DELEGATION_MAP.get(agent_id, ""),
        )

    @classmethod
    def error_contract(cls, agent_id: str, mission_id: str, error: str) -> "AgentContract":
        """Crée un AgentContract d'erreur standardisé."""
        return cls(
            agent_id   = agent_id,
            mission_id = mission_id,
            output     = "",
            status     = AgentStatus.ERROR,
            confidence = 0.0,
            error      = error[:200],
            next_recommended_agent = DELEGATION_MAP.get(agent_id, ""),
        )


# ─────────────────────────────────────────────────────────────────────────────
# ReviewResult — résultat d'une peer review inter-agents
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ReviewResult:
    """
    Résultat d'une peer review d'un AgentContract par un autre agent.

    Dimensions évaluées (0.0–10.0) :
        quality         - qualité générale de l'output
        consistency     - cohérence avec le contexte mission
        risk            - niveau de risque des actions proposées
        completeness    - couverture de la tâche demandée
    """
    reviewer_id:    str
    reviewed_id:    str     # agent_id de l'auteur
    contract_id:    str     # id du AgentContract revu

    quality:        float = 0.0
    consistency:    float = 0.0
    risk:           float = 0.0
    completeness:   float = 0.0

    overall_score:  float = 0.0   # 0.0–10.0
    approved:       bool  = True  # False = demande de révision
    feedback:       str   = ""
    suggested_next: str   = ""

    timestamp:      float = field(default_factory=time.time)

    @classmethod
    def from_scores(
        cls,
        reviewer_id:  str,
        reviewed_id:  str,
        contract_id:  str,
        quality:      float,
        consistency:  float,
        risk:         float,
        completeness: float,
        feedback:     str = "",
        pass_score:   float = 6.0,
    ) -> "ReviewResult":
        overall = round((quality + consistency + (10 - risk) + completeness) / 4, 2)
        return cls(
            reviewer_id   = reviewer_id,
            reviewed_id   = reviewed_id,
            contract_id   = contract_id,
            quality       = quality,
            consistency   = consistency,
            risk          = risk,
            completeness  = completeness,
            overall_score = overall,
            approved      = overall >= pass_score,
            feedback      = feedback,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "reviewer_id":   self.reviewer_id,
            "reviewed_id":   self.reviewed_id,
            "contract_id":   self.contract_id,
            "quality":       self.quality,
            "consistency":   self.consistency,
            "risk":          self.risk,
            "completeness":  self.completeness,
            "overall_score": self.overall_score,
            "approved":      self.approved,
            "feedback":      self.feedback,
            "suggested_next": self.suggested_next,
            "timestamp":     self.timestamp,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Delegation Map — graphe de délégation recommandée
# Utilisé par AgentContract.next_recommended_agent et MetaOrchestrator
# ─────────────────────────────────────────────────────────────────────────────

DELEGATION_MAP: dict[str, str] = {
    # Research pipeline
    "scout-research":   "map-planner",
    "map-planner":      "forge-builder",

    # Code pipeline
    "forge-builder":    "lens-reviewer",
    "lens-reviewer":    "pulse-ops",

    # Debug pipeline
    "debug-agent":      "forge-builder",

    # Workflow pipeline
    "workflow-agent":   "pulse-ops",

    # Monitoring
    "monitoring-agent": "debug-agent",

    # Self-improvement
    "self_improve":     "forge-builder",

    # Fallback
    "shadow-advisor":   "",     # terminal — no delegation
    "synthesizer":      "",     # terminal — produces final report
    "vault-memory":     "",     # terminal — memory only
}


# ─────────────────────────────────────────────────────────────────────────────
# Context size limits (to prevent prompt explosion)
# ─────────────────────────────────────────────────────────────────────────────

MEMORY_CONTEXT_MAX_CHARS = 2000   # max chars injected into agent prompt
MEMORY_CONTEXT_MAX_ITEMS = 5      # max memory items retrieved


# ─────────────────────────────────────────────────────────────────────────────
# Peer review threshold
# Below this confidence, peer review is triggered (if reviewer available)
# ─────────────────────────────────────────────────────────────────────────────

PEER_REVIEW_THRESHOLD    = 0.65   # confidence below which review is triggered
PEER_REVIEW_PASS_SCORE   = 6.0    # overall score below which output is flagged
