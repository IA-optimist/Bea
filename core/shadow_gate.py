"""
JARVIS MAX — Shadow Gate v1
Vérrou mandatory devant le ShadowAdvisor.

Règles d'intégration :
  - Aucune décision critique sans passer par ShadowAdvisor
  - Blocage automatique si decision = NO-GO
  - Blocage automatique si score < SCORE_BLOCK_THRESHOLD
  - Injection automatique des anti-patterns et erreurs passées dans le contexte

Résultat GateResult :
  - allowed : bool       → True si on peut continuer
  - reason  : str        → pourquoi bloqué ou autorisé
  - decision: str        → GO | IMPROVE | NO-GO
  - score   : float      → score du rapport
  - memory_ctx: str      → contexte mémoire injecté
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import structlog

log = structlog.get_logger()

# Seuils de blocage
SCORE_BLOCK_THRESHOLD = 3.5    # score < 3.5 → blocage
SCORE_WARN_THRESHOLD  = 5.5    # score < 5.5 → avertissement (non bloquant)
DECISION_BLOCKED      = {"NO-GO", "NO_GO", "NOGO"}


# ── Résultat de passage par la gate ───────────────────────────────────────────

@dataclass
class GateResult:
    allowed:    bool
    reason:     str
    decision:   str    = "UNKNOWN"
    score:      float  = 0.0
    memory_ctx: str    = ""

    def is_blocked(self) -> bool:
        return not self.allowed

    def has_warning(self) -> bool:
        return self.allowed and self.score < SCORE_WARN_THRESHOLD

    def __str__(self) -> str:
        status = "ALLOWED" if self.allowed else "BLOCKED"
        return f"[Gate:{status}] decision={self.decision} score={self.score:.1f} — {self.reason}"


# ── Shadow Gate ───────────────────────────────────────────────────────────────

class ShadowGate:
    """
    Vérrou Shadow Advisor.

    Usage typique dans l'orchestrateur :

        gate = ShadowGate()
        result = gate.check(session)
        if result.is_blocked():
            log.warning("shadow_gate_blocked", reason=result.reason)
            return result.reason
        # continuer...

    Usage avec mission string (hors session) :
        result = gate.check_advisory(report_dict)
    """

    def check(self, session: Any) -> GateResult:
        """
        Vérifie si la session peut continuer après l'avis shadow-advisor.
        Lit session.metadata["shadow_advisory"], ["shadow_score"], ["shadow_decision"].
        """
        try:
            meta     = getattr(session, "metadata", {}) or {}
            advisory = meta.get("shadow_advisory")
            score    = float(meta.get("shadow_score", 0.0))
            decision = str(meta.get("shadow_decision", "UNKNOWN")).upper().strip()

            if advisory is None:
                # Pas encore de rapport shadow — autoriser mais avertir
                log.warning(
                    "shadow_gate_no_report",
                    sid=getattr(session, "session_id", "?"),
                )
                return GateResult(
                    allowed=True,
                    reason="Aucun rapport shadow-advisor disponible (avertissement)",
                    decision="UNKNOWN",
                    score=0.0,
                    memory_ctx=self._build_memory_ctx(session),
                )

            return self._evaluate(decision, score, session)

        except Exception as exc:
            log.error("shadow_gate_error", err=str(exc))
            # En cas d'erreur technique → autoriser (fail-open pour éviter blocage systématique)
            return GateResult(
                allowed=True,
                reason=f"Erreur technique shadow gate : {exc}",
                decision="ERROR",
                score=0.0,
            )

    def check_advisory(self, report_dict: dict) -> GateResult:
        """
        Vérifie un dict AdvisoryReport directement (sans session).
        Utile pour les tests et pipelines alternatifs.
        """
        decision = str(report_dict.get("decision", "UNKNOWN")).upper().strip()
        score    = float(report_dict.get("final_score", 0.0))
        return self._evaluate(decision, score, session=None)

    # ── Internals ─────────────────────────────────────────────────────────────

    def _evaluate(self, decision: str, score: float, session: Any) -> GateResult:
        """Logique de décision centrale."""
        # Normalise decision
        decision_norm = decision.replace("-", "_").replace(" ", "_")
        is_no_go = (
            decision in DECISION_BLOCKED
            or decision_norm in DECISION_BLOCKED
        )

        # Blocage NO-GO
        if is_no_go:
            reason = (
                f"Shadow Advisor a rendu un verdict NO-GO "
                f"(score={score:.1f}/10). Toutes les décisions critiques sont bloquées."
            )
            log.warning(
                "shadow_gate_blocked_no_go",
                decision=decision,
                score=score,
                sid=getattr(session, "session_id", "?") if session else "?",
            )
            return GateResult(
                allowed=False,
                reason=reason,
                decision=decision,
                score=score,
                memory_ctx=self._build_memory_ctx(session) if session else "",
            )

        # Blocage score trop bas
        if score < SCORE_BLOCK_THRESHOLD:
            reason = (
                f"Score shadow trop bas ({score:.1f}/10 < {SCORE_BLOCK_THRESHOLD}). "
                f"Décision : {decision}. Corrections requises avant de continuer."
            )
            log.warning(
                "shadow_gate_blocked_low_score",
                score=score,
                threshold=SCORE_BLOCK_THRESHOLD,
                sid=getattr(session, "session_id", "?") if session else "?",
            )
            return GateResult(
                allowed=False,
                reason=reason,
                decision=decision,
                score=score,
                memory_ctx=self._build_memory_ctx(session) if session else "",
            )

        # Autorisé
        memory_ctx = self._build_memory_ctx(session) if session else ""

        if score < SCORE_WARN_THRESHOLD:
            reason = (
                f"Autorisé avec avertissement : score={score:.1f}/10 "
                f"(< {SCORE_WARN_THRESHOLD}), décision={decision}. "
                f"Amélioration recommandée."
            )
        else:
            reason = f"Shadow Gate OK : decision={decision}, score={score:.1f}/10."

        log.info(
            "shadow_gate_allowed",
            decision=decision,
            score=score,
            warned=score < SCORE_WARN_THRESHOLD,
        )
        return GateResult(
            allowed=True,
            reason=reason,
            decision=decision,
            score=score,
            memory_ctx=memory_ctx,
        )

    def _build_memory_ctx(self, session: Any) -> str:
        """
        Construit le contexte mémoire à injecter dans le prochain cycle.
        Récupère anti-patterns et erreurs depuis VaultMemory.
        """
        try:
            from memory.vault_memory import get_vault_memory
            vm = get_vault_memory()
            if session is not None:
                (
                    getattr(session, "mission_summary", "")
                    or getattr(session, "user_input", "")
                )

            errors       = vm.get_by_type("error", max_k=3)
            anti_patterns = vm.get_by_type("anti_pattern", max_k=3)

            if not errors and not anti_patterns:
                return ""

            lines = ["## Erreurs passées connues (mémoire Vault)"]
            for e in errors[:2]:
                lines.append(f"- [ERROR] {e.content[:150]}")
            for ap in anti_patterns[:2]:
                lines.append(f"- [ANTI-PATTERN] {ap.content[:150]}")

            return "\n".join(lines)
        except Exception:
            return ""


# ── Singleton ─────────────────────────────────────────────────────────────────

_gate_instance: ShadowGate|None = None


def get_shadow_gate() -> ShadowGate:
    global _gate_instance
    if _gate_instance is None:
        _gate_instance = ShadowGate()
    return _gate_instance


def gate_check(session: Any) -> GateResult:
    """
    Raccourci : vérifie si une session peut passer la shadow gate.

    Usage :
        from core.shadow_gate import gate_check
        result = gate_check(session)
        if result.is_blocked():
            return result.reason
    """
    return get_shadow_gate().check(session)
