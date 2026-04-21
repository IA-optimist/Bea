"""
JARVIS BUSINESS LAYER — Workflow Architect : Schémas de données
Modélise des workflows business avec étapes, outils, automatisations et ROI.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import json


@dataclass
class WorkflowStep:
    """Une étape dans un workflow business."""
    id:            str
    name:          str
    description:   str
    actor:         str        # "human" | "ai" | "automation" | "system"
    tools:         list[str]  = field(default_factory=list)
    inputs:        list[str]  = field(default_factory=list)
    outputs:       list[str]  = field(default_factory=list)
    duration_min:  int        = 0     # durée estimée en minutes
    can_automate:  bool       = False
    automation_tip: str       = ""


@dataclass
class BusinessWorkflow:
    """Un workflow business complet avec métriques et recommandations."""
    name:             str
    description:      str
    trigger:          str        # ce qui déclenche le workflow
    goal:             str        # résultat final attendu
    steps:            list[WorkflowStep] = field(default_factory=list)
    total_duration_min: int      = 0
    automation_ratio: float      = 0.0   # % des étapes automatisables
    roi_estimate:     str        = ""    # estimation narrative du ROI
    tools_required:   list[str]  = field(default_factory=list)
    integrations:     list[str]  = field(default_factory=list)
    kpis:             list[str]  = field(default_factory=list)
    n8n_blueprint_hint: str      = ""   # suggestion de blueprint n8n

    def to_dict(self) -> dict:
        return {
            "name":               self.name,
            "description":        self.description,
            "trigger":            self.trigger,
            "goal":               self.goal,
            "steps":              [
                {
                    "id":             s.id,
                    "name":           s.name,
                    "description":    s.description,
                    "actor":          s.actor,
                    "tools":          s.tools,
                    "inputs":         s.inputs,
                    "outputs":        s.outputs,
                    "duration_min":   s.duration_min,
                    "can_automate":   s.can_automate,
                    "automation_tip": s.automation_tip,
                }
                for s in self.steps
            ],
            "total_duration_min": self.total_duration_min,
            "automation_ratio":   self.automation_ratio,
            "roi_estimate":       self.roi_estimate,
            "tools_required":     self.tools_required,
            "integrations":       self.integrations,
            "kpis":               self.kpis,
            "n8n_blueprint_hint": self.n8n_blueprint_hint,
        }

    def format_card(self) -> str:
        human_steps  = sum(1 for s in self.steps if s.actor == "human")
        auto_steps   = sum(1 for s in self.steps if s.can_automate)
        return (
            f"⚙️ {self.name}\n"
            f"🎯 {self.goal[:80]}\n"
            f"📋 {len(self.steps)} étapes | {human_steps} humain | {auto_steps} automatisables\n"
            f"⏱ Durée totale : {self.total_duration_min} min\n"
            f"📈 ROI : {self.roi_estimate[:80]}"
        )


@dataclass
class WorkflowReport:
    """Rapport complet d'architecture de workflows."""
    context:    str
    workflows:  list[BusinessWorkflow] = field(default_factory=list)
    synthesis:  str                    = ""
    raw_llm:    str                    = ""

    def to_dict(self) -> dict:
        return {
            "context":   self.context,
            "workflows": [w.to_dict() for w in self.workflows],
            "synthesis": self.synthesis,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def summary_text(self) -> str:
        lines = [
            f"⚙️ Workflow Architecture : {self.context}",
            f"{len(self.workflows)} workflow(s) conçu(s)",
            "",
        ]
        for w in self.workflows:
            lines.append(w.format_card())
            lines.append("")
        if self.synthesis:
            lines.append(f"📝 Synthèse : {self.synthesis[:400]}")
        return "\n".join(lines)


def parse_workflow_report(raw: str, context: str) -> WorkflowReport:
    """Parse la sortie JSON du LLM en WorkflowReport. Robuste aux erreurs."""
    import re

    report = WorkflowReport(context=context, raw_llm=raw)

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

    for wd in data.get("workflows", []):
        steps = [
            WorkflowStep(
                id            = s.get("id", f"step_{i}"),
                name          = s.get("name", ""),
                description   = s.get("description", ""),
                actor         = s.get("actor", "human"),
                tools         = s.get("tools", []),
                inputs        = s.get("inputs", []),
                outputs       = s.get("outputs", []),
                duration_min  = int(s.get("duration_min", 0)),
                can_automate  = bool(s.get("can_automate", False)),
                automation_tip= s.get("automation_tip", ""),
            )
            for i, s in enumerate(wd.get("steps", []))
        ]
        total_dur    = sum(s.duration_min for s in steps)
        auto_count   = sum(1 for s in steps if s.can_automate)
        auto_ratio   = round(auto_count / len(steps), 2) if steps else 0.0

        workflow = BusinessWorkflow(
            name              = wd.get("name",             "Workflow"),
            description       = wd.get("description",      ""),
            trigger           = wd.get("trigger",          ""),
            goal              = wd.get("goal",             ""),
            steps             = steps,
            total_duration_min= wd.get("total_duration_min", total_dur),
            automation_ratio  = wd.get("automation_ratio",  auto_ratio),
            roi_estimate      = wd.get("roi_estimate",      ""),
            tools_required    = wd.get("tools_required",    []),
            integrations      = wd.get("integrations",      []),
            kpis              = wd.get("kpis",              []),
            n8n_blueprint_hint= wd.get("n8n_blueprint_hint",""),
        )
        report.workflows.append(workflow)

    return report
