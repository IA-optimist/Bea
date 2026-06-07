"""
BEA BUSINESS LAYER — Offer Designer : Schémas de données
Transforme une opportunité en offre commerciale structurée et vendable.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import json


@dataclass
class PricingTier:
    """Un palier de prix pour l'offre."""
    name:        str    # ex: "Starter", "Pro", "Enterprise"
    price_month: float  # prix mensuel en €
    price_year:  float  # prix annuel en € (0 si non applicable)
    description: str    # ce qui est inclus
    ideal_for:   str    # profil client idéal


@dataclass
class OfferDesign:
    """Une offre commerciale complète et actionnable."""
    title:              str
    tagline:            str           # 1 phrase de vente accrocheuse
    problem_statement:  str           # reformulation du problème côté client
    value_proposition:  str           # pourquoi cette offre, pourquoi maintenant
    target_persona:     str           # persona précis (prénom, poste, entreprise type)
    offer_type:         str           # "saas" | "service" | "productized" | "hybrid"
    delivery_mode:      str           # comment l'offre est délivrée
    key_features:       list[str]     = field(default_factory=list)
    differentiators:    list[str]     = field(default_factory=list)
    objection_answers:  dict[str, str] = field(default_factory=dict)  # objection → réponse
    pricing_tiers:      list[PricingTier] = field(default_factory=list)
    monetization_model: str           = ""   # description narrative du modèle
    upsell_path:        str           = ""   # chemin d'upsell naturel
    landing_headline:   str           = ""   # titre de landing page suggéré
    cta:                str           = ""   # call-to-action principal
    sales_script_opener: str          = ""   # ouverture de script de vente

    def to_dict(self) -> dict:
        return {
            "title":               self.title,
            "tagline":             self.tagline,
            "problem_statement":   self.problem_statement,
            "value_proposition":   self.value_proposition,
            "target_persona":      self.target_persona,
            "offer_type":          self.offer_type,
            "delivery_mode":       self.delivery_mode,
            "key_features":        self.key_features,
            "differentiators":     self.differentiators,
            "objection_answers":   self.objection_answers,
            "pricing_tiers":       [
                {
                    "name":        t.name,
                    "price_month": t.price_month,
                    "price_year":  t.price_year,
                    "description": t.description,
                    "ideal_for":   t.ideal_for,
                }
                for t in self.pricing_tiers
            ],
            "monetization_model":  self.monetization_model,
            "upsell_path":         self.upsell_path,
            "landing_headline":    self.landing_headline,
            "cta":                 self.cta,
            "sales_script_opener": self.sales_script_opener,
        }

    def format_card(self) -> str:
        tiers_str = " | ".join(
            f"{t.name} {t.price_month}€/m" for t in self.pricing_tiers
        )
        return (
            f"💼 {self.title}\n"
            f"🎯 {self.tagline}\n"
            f"👤 Persona : {self.target_persona[:80]}\n"
            f"💰 Prix : {tiers_str or self.monetization_model}\n"
            f"🚀 CTA : {self.cta}"
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


@dataclass
class OfferReport:
    """Rapport complet de design d'offre."""
    source_opportunity: str        # titre de l'opportunité d'origine
    offers:             list[OfferDesign] = field(default_factory=list)
    recommended:        Optional[str]     = None   # titre de l'offre recommandée
    synthesis:          str               = ""
    raw_llm:            str               = ""

    @property
    def best(self) -> Optional[OfferDesign]:
        if not self.offers:
            return None
        if self.recommended:
            for o in self.offers:
                if o.title == self.recommended:
                    return o
        return self.offers[0]

    def to_dict(self) -> dict:
        return {
            "source_opportunity": self.source_opportunity,
            "offers":             [o.to_dict() for o in self.offers],
            "recommended":        self.recommended,
            "synthesis":          self.synthesis,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def summary_text(self) -> str:
        lines = [
            f"💼 Offer Design : {self.source_opportunity}",
            f"{len(self.offers)} offre(s) conçue(s)",
            "",
        ]
        for o in self.offers:
            lines.append(o.format_card())
            lines.append("")
        if self.synthesis:
            lines.append(f"📝 Synthèse : {self.synthesis[:400]}")
        return "\n".join(lines)


def parse_offer_report(raw: str, source_opportunity: str) -> OfferReport:
    """Parse la sortie JSON du LLM en OfferReport. Robuste aux erreurs."""
    import re

    report = OfferReport(source_opportunity=source_opportunity, raw_llm=raw)

    json_str = raw.strip()
    if "```" in json_str:
        m = re.search(r"```(?:json)?\s*([\s\S]+?)```", json_str)
        if m:
            json_str = m.group(1).strip()

    try:
        data = json.loads(json_str)
    except Exception:
        m = re.search(r"\{[\s\S]+\}", json_str)
        if not m:
            report.synthesis = raw[:500]
            return report
        try:
            data = json.loads(m.group(0))
        except Exception:
            report.synthesis = raw[:500]
            return report

    report.synthesis  = data.get("synthesis", "")
    report.recommended = data.get("recommended", None)

    for od in data.get("offers", []):
        tiers = [
            PricingTier(
                name=t.get("name", ""),
                price_month=float(t.get("price_month", 0)),
                price_year=float(t.get("price_year", 0)),
                description=t.get("description", ""),
                ideal_for=t.get("ideal_for", ""),
            )
            for t in od.get("pricing_tiers", [])
        ]
        offer = OfferDesign(
            title              = od.get("title",              "Offre"),
            tagline            = od.get("tagline",            ""),
            problem_statement  = od.get("problem_statement",  ""),
            value_proposition  = od.get("value_proposition",  ""),
            target_persona     = od.get("target_persona",     ""),
            offer_type         = od.get("offer_type",         "service"),
            delivery_mode      = od.get("delivery_mode",      ""),
            key_features       = od.get("key_features",       []),
            differentiators    = od.get("differentiators",    []),
            objection_answers  = od.get("objection_answers",  {}),
            pricing_tiers      = tiers,
            monetization_model = od.get("monetization_model", ""),
            upsell_path        = od.get("upsell_path",        ""),
            landing_headline   = od.get("landing_headline",   ""),
            cta                = od.get("cta",                ""),
            sales_script_opener= od.get("sales_script_opener",""),
        )
        report.offers.append(offer)

    return report
