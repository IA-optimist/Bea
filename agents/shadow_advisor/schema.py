"""
BEA MAX — Shadow-Advisor V2 Schema
Schéma strict pour toutes les sorties du shadow-advisor.

Format JSON imposé — aucune réponse libre autorisée.

Décision :
  GO      → Décision/plan/code validé, risques acceptables
  IMPROVE → Potentiel réel mais blocages ou manques à corriger
  NO-GO   → Risques critiques, incohérences majeures ou preuves absentes

Score final (0.0 → 10.0) :
  Calculé par AdvisoryScorer — voir scorer.py
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ── Enums ─────────────────────────────────────────────────────────────────────

class AdvisoryDecision(str, Enum):
    GO      = "GO"
    IMPROVE = "IMPROVE"
    NO_GO   = "NO-GO"


class IssueSeverity(str, Enum):
    LOW    = "low"
    MEDIUM = "medium"
    HIGH   = "high"


class IssueType(str, Enum):
    TECHNIQUE = "technique"
    LOGIQUE   = "logique"
    MEMOIRE   = "memoire"
    SECURITE  = "securite"
    BUSINESS  = "business"
    TEST      = "test"


# ── Structures atomiques ──────────────────────────────────────────────────────

@dataclass
class BlockingIssue:
    type: str           # IssueType
    description: str
    severity: str       # IssueSeverity
    evidence: str = ""

    def is_critical(self) -> bool:
        return self.severity == IssueSeverity.HIGH

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "description": self.description,
            "severity": self.severity,
            "evidence": self.evidence,
        }


@dataclass
class Risk:
    type: str
    description: str
    severity: str
    probability: str = "medium"   # low | medium | high
    impact: str = "medium"        # low | medium | high

    def risk_score(self) -> float:
        """Score numérique P×I pour tri."""
        _map = {"low": 0.3, "medium": 0.6, "high": 0.9}
        p = _map.get(self.probability.lower(), 0.5)
        i = _map.get(self.impact.lower(), 0.5)
        return p * i

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "description": self.description,
            "severity": self.severity,
            "probability": self.probability,
            "impact": self.impact,
        }


# ── Rapport d'advisory ────────────────────────────────────────────────────────

@dataclass
class AdvisoryReport:
    decision: str                                    # GO | IMPROVE | NO-GO
    confidence: float                                # 0.0 → 1.0
    blocking_issues: list[BlockingIssue] = field(default_factory=list)
    risks: list[Risk] = field(default_factory=list)
    weak_points: list[str] = field(default_factory=list)
    inconsistencies: list[str] = field(default_factory=list)
    missing_proofs: list[str] = field(default_factory=list)
    improvements: list[str] = field(default_factory=list)
    tests_required: list[str] = field(default_factory=list)
    final_score: float = 5.0                         # 0.0 → 10.0
    justification: str = ""
    raw_output: str = ""                             # sortie LLM brute
    parse_error: str = ""                            # vide si parsing OK

    def __post_init__(self):
        # Normalisation decision
        d = str(self.decision).upper().strip()
        if d in ("NO-GO", "NOGO", "NO_GO"):
            self.decision = AdvisoryDecision.NO_GO
        elif d == "IMPROVE":
            self.decision = AdvisoryDecision.IMPROVE
        elif d == "GO":
            self.decision = AdvisoryDecision.GO
        else:
            self.decision = AdvisoryDecision.IMPROVE  # défaut conservatif

        # Clamp
        self.confidence  = max(0.0, min(1.0, float(self.confidence or 0.5)))
        self.final_score = max(0.0, min(10.0, float(self.final_score or 5.0)))

    # ── Properties utiles ─────────────────────────────────────────────────────

    def is_valid_parse(self) -> bool:
        return not self.parse_error

    def has_critical_issues(self) -> bool:
        return any(i.is_critical() for i in self.blocking_issues)

    def critical_issue_count(self) -> int:
        return sum(1 for i in self.blocking_issues if i.is_critical())

    def is_actionable(self) -> bool:
        """Rapport exploitable = au moins 1 risque, 1 faiblesse, 1 amélioration."""
        return (
            bool(self.risks or self.weak_points)
            and bool(self.improvements)
            and bool(self.justification)
        )

    def top_risk(self) -> Risk | None:
        if not self.risks:
            return None
        return max(self.risks, key=lambda r: r.risk_score())

    def blocking_count(self) -> int:
        return len(self.blocking_issues)

    def summary_line(self) -> str:
        """Ligne de résumé compacte."""
        crit = self.critical_issue_count()
        # .value pour Python 3.11+ où f"{StrEnum}" donne "Class.MEMBER" et non la valeur
        dec = self.decision.value if hasattr(self.decision, "value") else str(self.decision)
        return (
            f"[{dec}] score={self.final_score:.1f}/10 "
            f"conf={self.confidence:.0%} "
            f"issues={self.blocking_count()} (crit={crit}) "
            f"risks={len(self.risks)}"
        )

    def to_dict(self) -> dict:
        dec = self.decision.value if hasattr(self.decision, "value") else str(self.decision)
        return {
            "decision": dec,
            "confidence": round(self.confidence, 3),
            "blocking_issues": [i.to_dict() for i in self.blocking_issues],
            "risks": [r.to_dict() for r in self.risks],
            "weak_points": self.weak_points,
            "inconsistencies": self.inconsistencies,
            "missing_proofs": self.missing_proofs,
            "improvements": self.improvements,
            "tests_required": self.tests_required,
            "final_score": round(self.final_score, 2),
            "justification": self.justification,
        }

    def to_prompt_feedback(self) -> str:
        """
        Retourne un bloc compact injectable en feedback dans les prompts agents.
        Utilisé pour propager la critique dans la session.
        """
        dec = self.decision.value if hasattr(self.decision, "value") else str(self.decision)
        lines = [f"## Shadow-Advisor — {dec} ({self.final_score:.1f}/10)"]
        lines.append(f"*{self.justification[:200]}*")

        if self.blocking_issues:
            lines.append("\n**Blocages critiques :**")
            for issue in self.blocking_issues[:3]:
                lines.append(f"- [{issue.severity.upper()}] {issue.description}")

        if self.risks:
            lines.append("\n**Risques principaux :**")
            for r in self.risks[:2]:
                lines.append(f"- {r.description} (P={r.probability}/I={r.impact})")

        if self.improvements:
            lines.append("\n**Améliorations prioritaires :**")
            for imp in self.improvements[:3]:
                lines.append(f"- {imp}")

        return "\n".join(lines)


# ── Parseur ───────────────────────────────────────────────────────────────────

# Valeurs légales pour les enums
_VALID_SEVERITIES = {"low", "medium", "high"}
_VALID_PROBABILITIES = {"low", "medium", "high"}


def parse_advisory(raw: str) -> AdvisoryReport:
    """
    Parse la sortie brute du LLM en AdvisoryReport.

    Stratégies (par ordre de priorité) :
      1. JSON pur dans la réponse (```json ... ``` ou { ... })
      2. JSON partiel avec reconstruction des champs manquants
      3. Fallback : rapport d'erreur structuré (jamais d'exception)
    """
    raw = raw.strip() if raw else ""

    # Extraction du bloc JSON
    json_str = _extract_json(raw)
    if not json_str:
        return _fallback_report(raw, "Aucun JSON trouvé dans la réponse LLM")

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        # Tentative de réparation JSON simple
        data = _repair_json(json_str)
        if data is None:
            return _fallback_report(raw, f"JSON invalide : {e}")

    # Construction du rapport
    try:
        blocking = [
            BlockingIssue(
                type=_norm_str(b.get("type", "logique"), IssueType.LOGIQUE),
                description=str(b.get("description", ""))[:300],
                severity=_norm_str(b.get("severity", "medium"), IssueSeverity.MEDIUM),
                evidence=str(b.get("evidence", ""))[:200],
            )
            for b in data.get("blocking_issues", [])
            if isinstance(b, dict) and b.get("description")
        ]

        risks = [
            Risk(
                type=str(r.get("type", "général"))[:50],
                description=str(r.get("description", ""))[:300],
                severity=_norm_str(r.get("severity", "medium"), IssueSeverity.MEDIUM),
                probability=_norm_str(r.get("probability", "medium"), "medium", _VALID_PROBABILITIES),
                impact=_norm_str(r.get("impact", "medium"), "medium", _VALID_PROBABILITIES),
            )
            for r in data.get("risks", [])
            if isinstance(r, dict) and r.get("description")
        ]

        report = AdvisoryReport(
            decision=str(data.get("decision", "IMPROVE")),
            confidence=_to_float(data.get("confidence"), 0.5),
            blocking_issues=blocking,
            risks=risks,
            weak_points=_to_str_list(data.get("weak_points")),
            inconsistencies=_to_str_list(data.get("inconsistencies")),
            missing_proofs=_to_str_list(data.get("missing_proofs")),
            improvements=_to_str_list(data.get("improvements")),
            tests_required=_to_str_list(data.get("tests_required")),
            final_score=_to_float(data.get("final_score"), 5.0),
            justification=str(data.get("justification", ""))[:500],
            raw_output=raw,
        )
        return report

    except Exception as e:
        return _fallback_report(raw, f"Erreur construction rapport : {e}")


def validate_advisory_structure(report: AdvisoryReport) -> list[str]:
    """
    Vérifie que le rapport est complet et cohérent.
    Retourne la liste des violations (vide = rapport valide).
    """
    violations: list[str] = []

    if not report.is_valid_parse():
        violations.append(f"Erreur de parsing : {report.parse_error}")
        return violations  # Pas la peine de continuer

    dec_val = report.decision.value if hasattr(report.decision, "value") else str(report.decision)
    if dec_val not in ("GO", "IMPROVE", "NO-GO"):
        violations.append(f"Décision invalide : {dec_val}")

    if not report.risks and not report.blocking_issues:
        violations.append("Rapport sans risques ni blocages — critique vide")

    if not report.improvements:
        violations.append("Aucune amélioration proposée — rapport non actionnable")

    if not report.justification or len(report.justification) < 20:
        violations.append("Justification absente ou trop courte")

    if not (0.0 <= report.confidence <= 1.0):
        violations.append(f"Confidence hors bornes : {report.confidence}")

    if not (0.0 <= report.final_score <= 10.0):
        violations.append(f"Score hors bornes : {report.final_score}")

    # Cohérence décision ↔ score (comparaison par .value pour Python 3.11+)
    dec_val = report.decision.value if hasattr(report.decision, "value") else str(report.decision)

    if dec_val == "GO" and report.final_score < 6.0:
        violations.append(f"Incohérence : GO mais score={report.final_score:.1f} < 6.0")

    if dec_val == "NO-GO" and report.final_score > 5.0:
        violations.append(f"Incohérence : NO-GO mais score={report.final_score:.1f} > 5.0")

    if report.has_critical_issues() and dec_val == "GO":
        violations.append("Incohérence : GO avec des issues critiques non résolues")

    return violations


# ── Helpers privés ────────────────────────────────────────────────────────────

def _extract_json(text: str) -> str | None:
    """Extrait le premier bloc JSON valide de la réponse."""
    # 1. Bloc ```json ... ```
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return m.group(1).strip()

    # 2. Objet JSON standalone (cherche { ... } le plus large)
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]

    return None


def _repair_json(s: str) -> dict | None:
    """Tentatives de réparation JSON simples."""
    # Trailing comma avant } ou ]
    s = re.sub(r",(\s*[}\]])", r"\1", s)
    # Guillemets simples → doubles
    s = s.replace("'", '"')
    try:
        return json.loads(s)
    except Exception:
        return None


def _norm_str(value: Any, default: Any, valid_set: set | None = None) -> str:
    """Normalise une valeur string vers un ensemble de valeurs valides."""
    v = str(value).lower().strip() if value else str(default)
    if valid_set and v not in valid_set:
        return str(default).lower()
    return v


def _to_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v)[:300] for v in value if v]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _fallback_report(raw: str, error: str) -> AdvisoryReport:
    """Rapport d'erreur structuré — jamais d'exception."""
    r = AdvisoryReport.__new__(AdvisoryReport)
    r.decision = AdvisoryDecision.IMPROVE
    r.confidence = 0.0
    r.blocking_issues = [BlockingIssue(
        type=IssueType.LOGIQUE,
        description="Impossible de parser la réponse shadow-advisor",
        severity=IssueSeverity.HIGH,
        evidence=error,
    )]
    r.risks = []
    r.weak_points = ["Réponse LLM non structurée"]
    r.inconsistencies = ["Format de sortie invalide"]
    r.missing_proofs = []
    r.improvements = ["Réessayer avec un modèle qui supporte mieux le JSON structuré"]
    r.tests_required = []
    r.final_score = 0.0
    r.justification = f"Parsing échoué : {error}"
    r.raw_output = raw
    r.parse_error = error
    return r
