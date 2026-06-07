"""
BEA BUSINESS LAYER — SaaS Builder : Schémas de données
Transforme une idée en spécification MVP SaaS complète avec artifacts.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import json


@dataclass
class SaasFeature:
    """Une feature du MVP SaaS."""
    id:          str
    name:        str
    description: str
    priority:    str    # "must" | "should" | "could" | "wont"
    effort:      str    # "xs" | "s" | "m" | "l" | "xl"
    user_story:  str    # "En tant que X, je veux Y pour Z"


@dataclass
class SaasPage:
    """Une page / écran de l'application."""
    name:        str
    route:       str
    description: str
    components:  list[str] = field(default_factory=list)
    auth_required: bool    = True


@dataclass
class TechStack:
    """Stack technique recommandée."""
    frontend:    str
    backend:     str
    database:    str
    auth:        str
    hosting:     str
    payments:    str
    extras:      list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "frontend": self.frontend,
            "backend":  self.backend,
            "database": self.database,
            "auth":     self.auth,
            "hosting":  self.hosting,
            "payments": self.payments,
            "extras":   self.extras,
        }


@dataclass
class SaasBlueprint:
    """Spécification MVP SaaS complète."""
    product_name:      str
    tagline:           str
    problem:           str
    solution:          str
    target_user:       str
    mvp_scope:         str          # ce qui EST dans le MVP (et ce qui n'y est pas)
    features:          list[SaasFeature] = field(default_factory=list)
    pages:             list[SaasPage]    = field(default_factory=list)
    tech_stack:        Optional[TechStack] = None
    data_model_hint:   str          = ""   # entités principales et relations
    api_endpoints:     list[str]    = field(default_factory=list)
    auth_strategy:     str          = ""
    monetization:      str          = ""
    launch_plan:       list[str]    = field(default_factory=list)
    build_time_weeks:  int          = 0
    solo_buildable:    bool         = True

    def to_dict(self) -> dict:
        return {
            "product_name":    self.product_name,
            "tagline":         self.tagline,
            "problem":         self.problem,
            "solution":        self.solution,
            "target_user":     self.target_user,
            "mvp_scope":       self.mvp_scope,
            "features":        [
                {
                    "id":          f.id,
                    "name":        f.name,
                    "description": f.description,
                    "priority":    f.priority,
                    "effort":      f.effort,
                    "user_story":  f.user_story,
                }
                for f in self.features
            ],
            "pages":           [
                {
                    "name":          p.name,
                    "route":         p.route,
                    "description":   p.description,
                    "components":    p.components,
                    "auth_required": p.auth_required,
                }
                for p in self.pages
            ],
            "tech_stack":      self.tech_stack.to_dict() if self.tech_stack else {},
            "data_model_hint": self.data_model_hint,
            "api_endpoints":   self.api_endpoints,
            "auth_strategy":   self.auth_strategy,
            "monetization":    self.monetization,
            "launch_plan":     self.launch_plan,
            "build_time_weeks": self.build_time_weeks,
            "solo_buildable":  self.solo_buildable,
        }

    def format_card(self) -> str:
        must_features = [f for f in self.features if f.priority == "must"]
        return (
            f"🛠 {self.product_name}\n"
            f"💡 {self.tagline}\n"
            f"👤 {self.target_user[:60]}\n"
            f"📋 {len(must_features)} features MUST | {len(self.pages)} pages\n"
            f"⏱ Build : ~{self.build_time_weeks} semaines solo\n"
            f"💰 {self.monetization[:80]}"
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


@dataclass
class SaasReport:
    """Rapport complet SaaS Builder."""
    source:     str
    blueprints: list[SaasBlueprint] = field(default_factory=list)
    synthesis:  str                  = ""
    raw_llm:    str                  = ""

    @property
    def best(self) -> Optional[SaasBlueprint]:
        return self.blueprints[0] if self.blueprints else None

    def to_dict(self) -> dict:
        return {
            "source":     self.source,
            "blueprints": [b.to_dict() for b in self.blueprints],
            "synthesis":  self.synthesis,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def summary_text(self) -> str:
        lines = [
            f"🛠 SaaS Builder : {self.source}",
            f"{len(self.blueprints)} blueprint(s) généré(s)",
            "",
        ]
        for b in self.blueprints:
            lines.append(b.format_card())
            lines.append("")
        if self.synthesis:
            lines.append(f"📝 Synthèse : {self.synthesis[:400]}")
        return "\n".join(lines)


def parse_saas_report(raw: str, source: str) -> SaasReport:
    """Parse la sortie JSON du LLM en SaasReport. Robuste aux erreurs."""
    import re

    report = SaasReport(source=source, raw_llm=raw)

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

    report.synthesis = data.get("synthesis", "")

    for bd in data.get("blueprints", []):
        features = [
            SaasFeature(
                id          = f.get("id", f"f{i}"),
                name        = f.get("name", ""),
                description = f.get("description", ""),
                priority    = f.get("priority", "should"),
                effort      = f.get("effort", "m"),
                user_story  = f.get("user_story", ""),
            )
            for i, f in enumerate(bd.get("features", []))
        ]
        pages = [
            SaasPage(
                name          = p.get("name", ""),
                route         = p.get("route", "/"),
                description   = p.get("description", ""),
                components    = p.get("components", []),
                auth_required = bool(p.get("auth_required", True)),
            )
            for p in bd.get("pages", [])
        ]
        ts_data = bd.get("tech_stack", {})
        tech_stack = TechStack(
            frontend = ts_data.get("frontend", ""),
            backend  = ts_data.get("backend", ""),
            database = ts_data.get("database", ""),
            auth     = ts_data.get("auth", ""),
            hosting  = ts_data.get("hosting", ""),
            payments = ts_data.get("payments", ""),
            extras   = ts_data.get("extras", []),
        ) if ts_data else None

        blueprint = SaasBlueprint(
            product_name     = bd.get("product_name",    "MVP"),
            tagline          = bd.get("tagline",         ""),
            problem          = bd.get("problem",         ""),
            solution         = bd.get("solution",        ""),
            target_user      = bd.get("target_user",     ""),
            mvp_scope        = bd.get("mvp_scope",       ""),
            features         = features,
            pages            = pages,
            tech_stack       = tech_stack,
            data_model_hint  = bd.get("data_model_hint", ""),
            api_endpoints    = bd.get("api_endpoints",   []),
            auth_strategy    = bd.get("auth_strategy",   ""),
            monetization     = bd.get("monetization",    ""),
            launch_plan      = bd.get("launch_plan",     []),
            build_time_weeks = int(bd.get("build_time_weeks", 0)),
            solo_buildable   = bool(bd.get("solo_buildable", True)),
        )
        report.blueprints.append(blueprint)

    return report
