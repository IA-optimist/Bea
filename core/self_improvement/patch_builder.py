"""
BEA MAX — Self-Improvement Controller V1
Module C : PatchBuilder

Transforme un ImprovementProposal en PatchCandidate structuré.
V1 : description uniquement, pas de génération de code automatique.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass

from core.self_improvement.improvement_planner import ImprovementProposal
from core.self_improvement.protected_paths import is_protected

# Mots interdits dans fix_proposed — doublon de sécurité
_FORBIDDEN_WORDS = (
    "refonte", "migration DB", "architecture globale",
    "supprimer sécurité", "refactor complet",
)


@dataclass
class PatchCandidate:
    patch_id:             str
    proposal_id:          str
    created_at:           str
    diff_description:     str     # description lisible du diff à appliquer
    files_affected:       list[str]
    justification:        str
    rollback_description: str
    auto_applicable:      bool    # True seulement si risk_level="low" et confidence > 0.75
    status:               str     = "draft"  # "draft" | "ready" | "applied" | "rolled_back"

    def to_dict(self) -> dict:
        return asdict(self)


class PatchBuilder:
    """
    Produit un PatchCandidate structuré à partir d'un ImprovementProposal.

    V1 — Ne génère PAS de code automatiquement.
    Produit uniquement la description + le flag auto_applicable.
    """

    def build_patch(self, proposal: ImprovementProposal) -> PatchCandidate | None:
        """
        Construit un PatchCandidate depuis un proposal.
        Retourne None si le proposal contient des mots interdits.
        """
        # Vérifier les mots interdits
        if self._has_forbidden_words(proposal.fix_proposed):
            return None

        # Bloquer les fichiers protégés
        if any(is_protected(f) for f in (proposal.files_to_modify or [])):
            return None

        auto_applicable = (
            proposal.risk_level == "low"
            and proposal.confidence_score > 0.75
        )

        diff_description = self._build_diff_description(proposal)

        status = "ready" if auto_applicable else "draft"

        return PatchCandidate(
            patch_id=str(uuid.uuid4())[:8],
            proposal_id=proposal.proposal_id,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            diff_description=diff_description,
            files_affected=list(proposal.files_to_modify),
            justification=(
                f"[{proposal.risk_level.upper()} risk, confidence={proposal.confidence_score:.2f}] "
                f"{proposal.expected_impact}"
            ),
            rollback_description=proposal.rollback_plan,
            auto_applicable=auto_applicable,
            status=status,
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_diff_description(self, proposal: ImprovementProposal) -> str:
        files = ", ".join(proposal.files_to_modify) if proposal.files_to_modify else "à déterminer"
        return (
            f"Problème : {proposal.problem}\n"
            f"Fix proposé : {proposal.fix_proposed}\n"
            f"Fichiers concernés : {files}\n"
            f"Impact attendu : {proposal.expected_impact}\n"
            f"Tests requis : {', '.join(proposal.tests_required)}\n"
            f"NOTE V1 : Ce patch est une description — le code réel doit être écrit manuellement."
        )

    def _has_forbidden_words(self, text: str) -> bool:
        t = text.lower()
        return any(w.lower() in t for w in _FORBIDDEN_WORDS)
