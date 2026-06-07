"""
BEA BUSINESS LAYER — Venture Builder : Schémas de données
Source unique des types pour l'analyse d'opportunités business.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import json


@dataclass
class VentureScore:
    """Scores d'évaluation d'une opportunité (1-10 chacun)."""
    pain:        float = 0.0   # Douleur du problème
    frequency:   float = 0.0   # Fréquence du besoin
    ease_sale:   float = 0.0   # Facilité de vente
    retention:   float = 0.0   # Potentiel de rétention / abonnement
    automation:  float = 0.0   # Potentiel d'automatisation
    saas:        float = 0.0   # Potentiel SaaS
    ai_fit:      float = 0.0   # Pertinence IA métier

    @property
    def global_score(self) -> float:
        """Score composite pondéré (pain + frequency ont plus de poids)."""
        weights = [2.0, 1.5, 1.0, 1.0, 1.2, 1.0, 1.0]
        values  = [self.pain, self.frequency, self.ease_sale,
                   self.retention, self.automation, self.saas, self.ai_fit]
        total_w = sum(weights)
        return round(sum(v * w for v, w in zip(values, weights)) / total_w, 1)

    @property
    def tier(self) -> str:
        s = self.global_score
        if s >= 7.5: return "A"
        if s >= 6.0: return "B"
        if s >= 4.5: return "C"
        return "D"

    def to_dict(self) -> dict:
        return {
            "pain":       self.pain,
            "frequency":  self.frequency,
            "ease_sale":  self.ease_sale,
            "retention":  self.retention,
            "automation": self.automation,
            "saas":       self.saas,
            "ai_fit":     self.ai_fit,
            "global":     self.global_score,
            "tier":       self.tier,
        }


@dataclass
class VentureOpportunity:
    """Une opportunité business identifiée."""
    title:             str
    problem:           str            # Problème identifié
    target:            str            # Segment cible
    offer_idea:        str            # Offre possible
    difficulty:        str            # "low" | "medium" | "high"
    short_term:        str            # Potentiel court terme (< 3 mois)
    long_term:         str            # Potentiel long terme (> 6 mois)
    mvp_recommendation: str          # Recommandation MVP concrète
    scores:            VentureScore  = field(default_factory=VentureScore)
    monetization:      str           = ""   # modèle de monétisation
    competitors:       list[str]     = field(default_factory=list)
    risks:             list[str]     = field(default_factory=list)
    first_steps:       list[str]     = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "title":              self.title,
            "problem":            self.problem,
            "target":             self.target,
            "offer_idea":         self.offer_idea,
            "difficulty":         self.difficulty,
            "short_term":         self.short_term,
            "long_term":          self.long_term,
            "mvp_recommendation": self.mvp_recommendation,
            "scores":             self.scores.to_dict(),
            "monetization":       self.monetization,
            "competitors":        self.competitors,
            "risks":              self.risks,
            "first_steps":        self.first_steps,
        }

    def format_card(self) -> str:
        s = self.scores
        return (
            f"🎯 {self.title} [{s.tier} — {s.global_score}/10]\n"
            f"📌 Problème : {self.problem[:100]}\n"
            f"👥 Cible : {self.target}\n"
            f"💡 Offre : {self.offer_idea[:100]}\n"
            f"⚡ MVP : {self.mvp_recommendation[:120]}\n"
            f"📊 Pain:{s.pain} Freq:{s.frequency} Vente:{s.ease_sale} "
            f"SaaS:{s.saas} IA:{s.ai_fit}"
        )


@dataclass
class VentureReport:
    """Rapport complet d'analyse d'opportunités."""
    query:         str
    sector:        str
    opportunities: list[VentureOpportunity] = field(default_factory=list)
    raw_llm:       str                      = ""   # sortie brute du LLM
    synthesis:     str                      = ""   # synthèse narrative

    @property
    def best(self) -> Optional[VentureOpportunity]:
        if not self.opportunities:
            return None
        return max(self.opportunities, key=lambda o: o.scores.global_score)

    @property
    def tier_a(self) -> list[VentureOpportunity]:
        return [o for o in self.opportunities if o.scores.tier == "A"]

    def to_dict(self) -> dict:
        return {
            "query":         self.query,
            "sector":        self.sector,
            "opportunities": [o.to_dict() for o in self.opportunities],
            "synthesis":     self.synthesis,
            "best":          self.best.title if self.best else None,
            "tier_a_count":  len(self.tier_a),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def summary_text(self) -> str:
        lines = [
            f"📊 Analyse venture : {self.query}",
            f"Secteur : {self.sector}",
            f"{len(self.opportunities)} opportunité(s) identifiée(s)",
            "",
        ]
        for i, op in enumerate(
            sorted(self.opportunities, key=lambda o: o.scores.global_score, reverse=True)[:5],
            start=1
        ):
            lines.append(op.format_card())
            lines.append("")
        if self.synthesis:
            lines.append(f"📝 Synthèse : {self.synthesis[:400]}")
        return "\n".join(lines)


def parse_venture_report(raw: str, query: str) -> VentureReport:
    """
    Parse la sortie JSON du LLM en VentureReport.
    Robuste : retourne un rapport vide si parsing impossible.
    """
    import re

    report = VentureReport(query=query, sector="", raw_llm=raw)

    # Extraire le JSON du markdown si besoin
    json_str = raw.strip()
    if "```" in json_str:
        m = re.search(r"```(?:json)?\s*([\s\S]+?)```", json_str)
        if m:
            json_str = m.group(1).strip()

    try:
        data = json.loads(json_str)
    except Exception:
        # Tentative de trouver un JSON dans le texte
        m = re.search(r"\{[\s\S]+\}", json_str)
        if not m:
            report.synthesis = raw[:500]
            return report
        try:
            data = json.loads(m.group(0))
        except Exception:
            report.synthesis = raw[:500]
            return report

    report.sector    = data.get("sector", "")
    report.synthesis = data.get("synthesis", "")

    for op_data in data.get("opportunities", []):
        scores_data = op_data.get("scores", {})
        scores = VentureScore(
            pain       = float(scores_data.get("pain",       5)),
            frequency  = float(scores_data.get("frequency",  5)),
            ease_sale  = float(scores_data.get("ease_sale",  5)),
            retention  = float(scores_data.get("retention",  5)),
            automation = float(scores_data.get("automation", 5)),
            saas       = float(scores_data.get("saas",       5)),
            ai_fit     = float(scores_data.get("ai_fit",     5)),
        )
        opp = VentureOpportunity(
            title              = op_data.get("title",              "Opportunité"),
            problem            = op_data.get("problem",            ""),
            target             = op_data.get("target",             ""),
            offer_idea         = op_data.get("offer_idea",         ""),
            difficulty         = op_data.get("difficulty",         "medium"),
            short_term         = op_data.get("short_term",         ""),
            long_term          = op_data.get("long_term",          ""),
            mvp_recommendation = op_data.get("mvp_recommendation", ""),
            scores             = scores,
            monetization       = op_data.get("monetization",       ""),
            competitors        = op_data.get("competitors",        []),
            risks              = op_data.get("risks",              []),
            first_steps        = op_data.get("first_steps",        []),
        )
        report.opportunities.append(opp)

    return report
