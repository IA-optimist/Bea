"""
BEA MAX — Memory Schemas
============================
Schéma de métadonnées unifié pour toutes les entrées mémoire de BeaMax.

Règle d'or : TOUTE entrée mémoire doit être normalisable en MemoryEntry.
Les modules mémoire existants gardent leur stockage interne, mais
l'interface MemoryBus expose et injecte les données via ce schéma.

4 Couches mémoire :
    WORKING     - contexte court terme d'une mission active
    EPISODIC    - historique des missions et résultats (AgentMemory, MemoryStore)
    SEMANTIC    - connaissance sémantique par embeddings (VectorMemory, pgvector)
    PROCEDURAL  - stratégies, patterns, skills (KnowledgeMemory, PatchMemory)
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, cast


class MemoryLayer(str, Enum):
    WORKING    = "working"     # court terme, mission en cours
    EPISODIC   = "episodic"    # missions passées, résultats agents
    SEMANTIC   = "semantic"    # connaissances vectorielles
    PROCEDURAL = "procedural"  # stratégies, patterns, patches


class MemoryType(str, Enum):
    # Working
    MISSION_CONTEXT = "mission_context"
    AGENT_OUTPUT    = "agent_output"
    TASK_STATE      = "task_state"

    # Episodic
    MISSION_RESULT  = "mission_result"
    FAILURE         = "failure"
    PATCH_HISTORY   = "patch_history"

    # Semantic
    KNOWLEDGE       = "knowledge"
    CODE_SNIPPET    = "code_snippet"
    DOCUMENTATION   = "documentation"

    # Procedural
    STRATEGY        = "strategy"
    BEST_PRACTICE   = "best_practice"
    WORKFLOW        = "workflow"


@dataclass
class MemoryEntry:
    """
    Entrée mémoire normalisée — schéma commun à toutes les couches.

    Champs obligatoires :
        text            - contenu textuel
        memory_type     - type de l'entrée (MemoryType)
        layer           - couche cible (MemoryLayer)

    Champs optionnels mais fortement recommandés :
        mission_id      - ID de la mission source
        agent_id        - nom de l'agent qui a produit l'entrée
        confidence      - score de confiance 0.0–1.0
        tags            - liste de tags pour filtrage
        source          - origine (ex: "scout-research", "forge-builder", "user")
        metadata        - dict arbitraire de contexte additionnel

    Champs auto-générés :
        id              - UUID unique
        timestamp       - epoch float
    """
    text:         str
    memory_type:  MemoryType
    layer:        MemoryLayer

    # Contexte
    mission_id:   str   = ""
    agent_id:     str   = ""
    confidence:   float = 1.0
    tags:         list[str] = field(default_factory=list)
    source:       str   = ""
    metadata:     dict[str, object] = field(default_factory=dict)

    # Auto
    id:           str   = field(default_factory=lambda: str(uuid.uuid4())[:12])
    timestamp:    float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, object]:
        return {
            "id":          self.id,
            "text":        self.text,
            "memory_type": self.memory_type.value,
            "layer":       self.layer.value,
            "mission_id":  self.mission_id,
            "agent_id":    self.agent_id,
            "confidence":  round(self.confidence, 3),
            "tags":        self.tags,
            "source":      self.source,
            "metadata":    self.metadata,
            "timestamp":   self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> "MemoryEntry":
        return cls(
            id          = cast(str, d.get("id", str(uuid.uuid4())[:12])),
            text        = cast(str, d.get("text", "")),
            memory_type = MemoryType(cast(str, d.get("memory_type", MemoryType.KNOWLEDGE.value))),
            layer       = MemoryLayer(cast(str, d.get("layer", MemoryLayer.SEMANTIC.value))),
            mission_id  = cast(str, d.get("mission_id", "")),
            agent_id    = cast(str, d.get("agent_id", "")),
            confidence  = float(cast(Any, d.get("confidence", 1.0))),
            tags        = cast(list[str], d.get("tags", [])),
            source      = cast(str, d.get("source", "")),
            metadata    = cast(dict[str, object], d.get("metadata", {})),
            timestamp   = float(cast(Any, d.get("timestamp", time.time()))),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Layer routing table
# Détermine quelle(s) couche(s) un memory_type cible par défaut
# ─────────────────────────────────────────────────────────────────────────────

LAYER_FOR_TYPE: dict[MemoryType, MemoryLayer] = {
    MemoryType.MISSION_CONTEXT: MemoryLayer.WORKING,
    MemoryType.AGENT_OUTPUT:    MemoryLayer.WORKING,
    MemoryType.TASK_STATE:      MemoryLayer.WORKING,

    MemoryType.MISSION_RESULT:  MemoryLayer.EPISODIC,
    MemoryType.FAILURE:         MemoryLayer.EPISODIC,
    MemoryType.PATCH_HISTORY:   MemoryLayer.EPISODIC,

    MemoryType.KNOWLEDGE:       MemoryLayer.SEMANTIC,
    MemoryType.CODE_SNIPPET:    MemoryLayer.SEMANTIC,
    MemoryType.DOCUMENTATION:   MemoryLayer.SEMANTIC,

    MemoryType.STRATEGY:        MemoryLayer.PROCEDURAL,
    MemoryType.BEST_PRACTICE:   MemoryLayer.PROCEDURAL,
    MemoryType.WORKFLOW:        MemoryLayer.PROCEDURAL,
}


def normalize_metadata(raw: dict[str, object] | None, entry: MemoryEntry) -> dict[str, object]:
    """
    Normalise un dict de métadonnées arbitraire en injectant
    les champs standards de MemoryEntry.
    Utilisé avant tout stockage dans VectorMemory ou MemoryStore.
    """
    meta = dict(raw or {})
    meta.setdefault("memory_type", entry.memory_type.value)
    meta.setdefault("layer",       entry.layer.value)
    meta.setdefault("mission_id",  entry.mission_id)
    meta.setdefault("agent_id",    entry.agent_id)
    meta.setdefault("confidence",  entry.confidence)
    meta.setdefault("source",      entry.source)
    meta.setdefault("timestamp",   entry.timestamp)
    return meta
