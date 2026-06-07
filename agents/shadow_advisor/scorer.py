"""
BEA MAX — Shadow-Advisor V2 Scorer
Calcul du score final d'un AdvisoryReport.

Logique opérationnelle :
  Base : 7.0 / 10 (parti d'un bon niveau avant critique)

  BONUS (+) :
    +0.5  par preuve présente (evidence non vide dans blocking_issues)
    +0.3  par test requis identifié (tests_required)
    +0.2  par amélioration concrète (improvements)
    +0.3  si justification ≥ 80 chars (explication sérieuse)
    +0.5  si aucun risque critique (rapport propre)

  MALUS (−) :
    −1.5  par blocage critique (severity=high)
    −0.8  par blocage medium
    −0.2  par blocage low
    −0.5  par incohérence détectée (inconsistencies)
    −0.4  par preuve manquante (missing_proofs)
    −1.0  si risque critique non traité (high severity sans mitigation)
    −0.3  si confidence < 0.4 (incertitude élevée)

  Règles absolues :
    - Score < 3.0 → décision forcée à NO-GO
    - Score ≥ 7.5 → décision forcée à GO (si aucun blocage critique)
    - 3.0 ≤ score < 7.5 → IMPROVE
    - Présence d'un blocage critical → score ≤ 4.9 max (cap)

Cohérence garantie :
    - GO  : score ≥ 6.0, aucun blocage critical
    - NO-GO : score ≤ 5.0 ou blocage critical présent
    - IMPROVE : 4.0 ≤ score ≤ 7.5
"""
from __future__ import annotations

from typing import Any

from agents.shadow_advisor.schema import AdvisoryReport, AdvisoryDecision, IssueSeverity


class AdvisoryScorer:
    """
    Calcule et recalibre le score d'un AdvisoryReport.

    Usage :
        scorer = AdvisoryScorer()
        report = scorer.score(report)   # retourne le rapport avec score corrigé
        explanation = scorer.explain(report)  # explication humaine du score
    """

    BASE_SCORE = 7.0

    # Bonus
    BONUS_EVIDENCE_PER  = 0.50
    BONUS_TEST_PER      = 0.30
    BONUS_IMPROVEMENT   = 0.20
    BONUS_JUSTIFICATION = 0.30
    BONUS_NO_CRITICAL   = 0.50

    # Malus
    MALUS_BLOCK_HIGH    = 1.50
    MALUS_BLOCK_MEDIUM  = 0.80
    MALUS_BLOCK_LOW     = 0.20
    MALUS_INCONSISTENCY = 0.50
    MALUS_MISSING_PROOF = 0.40
    MALUS_RISK_CRITICAL = 1.00
    MALUS_LOW_CONFIDENCE= 0.30

    # Caps
    CAP_WITH_CRITICAL   = 4.9   # si blocage critical → score ≤ 4.9
    THRESHOLD_NO_GO     = 3.0
    THRESHOLD_GO        = 7.5

    def score(self, report: AdvisoryReport) -> AdvisoryReport:
        """
        Recalcule le score final et recalibre la décision du rapport.
        Modifie report.final_score et report.decision in-place.
        Retourne le rapport modifié.
        """
        score = self.BASE_SCORE
        steps: list[tuple[str, float]] = [("BASE", score)]

        # ── BONUS ─────────────────────────────────────────────────────────
        evidences = sum(
            1 for i in report.blocking_issues if i.evidence and len(i.evidence) > 5
        )
        if evidences:
            bonus = min(evidences * self.BONUS_EVIDENCE_PER, 1.5)
            score += bonus
            steps.append((f"BONUS preuves ×{evidences}", bonus))

        if report.tests_required:
            bonus = min(len(report.tests_required) * self.BONUS_TEST_PER, 1.0)
            score += bonus
            steps.append((f"BONUS tests ×{len(report.tests_required)}", bonus))

        if report.improvements:
            bonus = min(len(report.improvements) * self.BONUS_IMPROVEMENT, 0.8)
            score += bonus
            steps.append((f"BONUS améliorations ×{len(report.improvements)}", bonus))

        if len(report.justification) >= 80:
            score += self.BONUS_JUSTIFICATION
            steps.append(("BONUS justification", self.BONUS_JUSTIFICATION))

        has_critical = report.has_critical_issues()
        if not has_critical:
            score += self.BONUS_NO_CRITICAL
            steps.append(("BONUS aucun critique", self.BONUS_NO_CRITICAL))

        # ── MALUS ─────────────────────────────────────────────────────────
        for issue in report.blocking_issues:
            # Extraction robuste de la valeur de sévérité —
            # issue.severity peut être une str "high" OU un IssueSeverity Enum.
            # str(Enum) donne "IssueSeverity.HIGH" en Python 3.11+ → ne pas utiliser str().
            _raw_sev = issue.severity
            sev = (_raw_sev.value if hasattr(_raw_sev, "value") else str(_raw_sev)).lower()
            if sev == IssueSeverity.HIGH.value:        # "high"
                score -= self.MALUS_BLOCK_HIGH
                steps.append((f"MALUS blocage HIGH: {issue.description[:30]}", -self.MALUS_BLOCK_HIGH))
            elif sev == IssueSeverity.MEDIUM.value:    # "medium"
                score -= self.MALUS_BLOCK_MEDIUM
                steps.append(("MALUS blocage MEDIUM", -self.MALUS_BLOCK_MEDIUM))
            else:                                      # "low" + tout autre cas
                score -= self.MALUS_BLOCK_LOW
                steps.append(("MALUS blocage LOW", -self.MALUS_BLOCK_LOW))

        if report.inconsistencies:
            malus = min(len(report.inconsistencies) * self.MALUS_INCONSISTENCY, 2.0)
            score -= malus
            steps.append((f"MALUS incohérences ×{len(report.inconsistencies)}", -malus))

        if report.missing_proofs:
            malus = min(len(report.missing_proofs) * self.MALUS_MISSING_PROOF, 1.5)
            score -= malus
            steps.append((f"MALUS preuves manquantes ×{len(report.missing_proofs)}", -malus))

        # Risques critiques sans mitigation — même extraction robuste
        def _sev_val(s: Any) -> str:
            return (s.value if hasattr(s, "value") else str(s)).lower()

        critical_risks = [r for r in report.risks if _sev_val(r.severity) == "high"]
        if critical_risks:
            malus = min(len(critical_risks) * self.MALUS_RISK_CRITICAL, 2.0)
            score -= malus
            steps.append((f"MALUS risques critiques ×{len(critical_risks)}", -malus))

        if report.confidence < 0.4:
            score -= self.MALUS_LOW_CONFIDENCE
            steps.append(("MALUS faible confidence", -self.MALUS_LOW_CONFIDENCE))

        # ── Caps ──────────────────────────────────────────────────────────
        if has_critical:
            score = min(score, self.CAP_WITH_CRITICAL)
            steps.append((f"CAP avec blocage critique → max {self.CAP_WITH_CRITICAL}", 0))

        # Clamp [0, 10]
        score = max(0.0, min(10.0, score))

        # ── Décision basée sur le score ────────────────────────────────────
        decision = self._decide(score, has_critical)

        report.final_score = round(score, 2)
        report.decision    = decision
        report._score_steps = steps  # pour explain()

        return report

    def explain(self, report: AdvisoryReport) -> str:
        """Explication lisible du calcul de score."""
        lines = [f"Score final : {report.final_score:.2f}/10 → {report.decision}"]
        steps = getattr(report, "_score_steps", [])
        for label, delta in steps:
            sign = "+" if delta >= 0 else ""
            lines.append(f"  {sign}{delta:+.2f}  {label}")
        lines.append(f"  → DÉCISION : {report.decision}")
        return "\n".join(lines)

    def _decide(self, score: float, has_critical: bool) -> AdvisoryDecision:
        if has_critical or score < self.THRESHOLD_NO_GO:
            return AdvisoryDecision.NO_GO
        if score >= self.THRESHOLD_GO:
            return AdvisoryDecision.GO
        return AdvisoryDecision.IMPROVE
