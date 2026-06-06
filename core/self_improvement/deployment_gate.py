"""
JARVIS MAX — Self-Improvement Controller V1
Module E : DeploymentGate

Évalue si un PatchCandidate peut être déployé selon le mode système.
"""
from __future__ import annotations

import structlog
log = structlog.get_logger(__name__)

from dataclasses import asdict, dataclass

from core.self_improvement.patch_builder import PatchCandidate
from core.self_improvement.protected_paths import is_protected


@dataclass
class GateDecision:
    patch_id:               str
    system_mode:            str
    decision:               str    # "APPROVED" | "PENDING_VALIDATION" | "REJECTED"
    reason:                 str
    rollback_ready:         bool
    requires_human_approval: bool

    def to_dict(self) -> dict:
        return asdict(self)


class DeploymentGate:
    """
    Décide si un patch peut être déployé selon le mode système.

    MANUAL     → toujours PENDING_VALIDATION
    SUPERVISED → APPROVED si auto_applicable + confidence > 0.75
    AUTO       → APPROVED si risk="low" + confidence > 0.85 + auto_applicable
    """

    def evaluate(
        self,
        patch: PatchCandidate,
        system_mode: str,
    ) -> GateDecision:
        mode = system_mode.upper()

        # Garde-fou absolu : fichiers protégés
        if self._touches_protected_files(patch.files_affected):
            protected = [f for f in patch.files_affected if is_protected(f)]
            return GateDecision(
                patch_id=patch.patch_id,
                system_mode=mode,
                decision="REJECTED",
                reason=f"Fichiers protégés détectés : {protected}. Modification interdite.",
                rollback_ready=False,
                requires_human_approval=False,
            )

        # Récupérer confidence depuis la justification (encodée dans le patch)
        confidence = self._extract_confidence(patch.justification)
        risk_level = self._extract_risk(patch.justification)

        if mode == "MANUAL":
            return GateDecision(
                patch_id=patch.patch_id,
                system_mode=mode,
                decision="PENDING_VALIDATION",
                reason="Mode MANUAL — validation humaine obligatoire pour tout patch.",
                rollback_ready=True,
                requires_human_approval=True,
            )

        elif mode == "SUPERVISED":
            if patch.auto_applicable and confidence > 0.75:
                return GateDecision(
                    patch_id=patch.patch_id,
                    system_mode=mode,
                    decision="APPROVED",
                    reason=f"Mode SUPERVISED — auto_applicable=True, confidence={confidence:.2f} > 0.75.",
                    rollback_ready=True,
                    requires_human_approval=False,
                )
            else:
                reason = []
                if not patch.auto_applicable:
                    reason.append("auto_applicable=False")
                if confidence <= 0.75:
                    reason.append(f"confidence={confidence:.2f} ≤ 0.75")
                return GateDecision(
                    patch_id=patch.patch_id,
                    system_mode=mode,
                    decision="PENDING_VALIDATION",
                    reason=f"Mode SUPERVISED — {', '.join(reason)}. Validation requise.",
                    rollback_ready=True,
                    requires_human_approval=True,
                )

        elif mode == "AUTO":
            if risk_level == "low" and confidence > 0.85 and patch.auto_applicable:
                return GateDecision(
                    patch_id=patch.patch_id,
                    system_mode=mode,
                    decision="APPROVED",
                    reason=(
                        f"Mode AUTO — risk=low, confidence={confidence:.2f} > 0.85, "
                        f"auto_applicable=True."
                    ),
                    rollback_ready=True,
                    requires_human_approval=False,
                )
            else:
                reason = []
                if risk_level != "low":
                    reason.append(f"risk={risk_level}")
                if confidence <= 0.85:
                    reason.append(f"confidence={confidence:.2f} ≤ 0.85")
                if not patch.auto_applicable:
                    reason.append("auto_applicable=False")
                return GateDecision(
                    patch_id=patch.patch_id,
                    system_mode=mode,
                    decision="PENDING_VALIDATION",
                    reason=f"Mode AUTO — critères insuffisants : {', '.join(reason)}.",
                    rollback_ready=True,
                    requires_human_approval=True,
                )

        else:
            return GateDecision(
                patch_id=patch.patch_id,
                system_mode=mode,
                decision="PENDING_VALIDATION",
                reason=f"Mode inconnu '{mode}' — validation humaine par précaution.",
                rollback_ready=True,
                requires_human_approval=True,
            )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _touches_protected_files(self, files: list[str]) -> bool:
        return any(is_protected(f) for f in files)

    def _extract_confidence(self, justification: str) -> float:
        """Extrait confidence=X.XX depuis la justification encodée par PatchBuilder."""
        import re
        m = re.search(r"confidence=([0-9.]+)", justification)
        if m:
            try:
                return float(m.group(1))
            except ValueError as _exc:
                log.warning("swallowed_exception", action="deployment_gate_swallow", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
        return 0.5

    def _extract_risk(self, justification: str) -> str:
        """Extrait le niveau de risque depuis la justification."""
        j = justification.lower()
        if "low risk" in j or "[low" in j:
            return "low"
        if "medium risk" in j or "[medium" in j:
            return "medium"
        if "high risk" in j or "[high" in j:
            return "high"
        return "medium"
