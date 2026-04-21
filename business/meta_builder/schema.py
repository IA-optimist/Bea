"""
JARVIS BUSINESS LAYER — Meta Builder : Schémas de données
Clone/duplique des configurations multi-agents pour un nouveau contexte métier.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import json


@dataclass
class AgentCloneSpec:
    """Spécification d'un agent cloné pour un nouveau contexte."""
    original_agent: str    # agent source (ex: "venture-builder")
    cloned_name:    str    # nouveau nom
    new_sector:     str    # nouveau secteur/contexte
    prompt_delta:   str    # ce qui change dans le prompt système
    new_system_prompt: str = ""   # prompt final (si généré)


@dataclass
class MetaBuildPlan:
    """Plan de duplication d'un système multi-agents."""
    source_system:    str   # ce qui est cloné ("jarvis-business" par ex)
    target_context:   str   # nouveau contexte (ex: "agence immobilière")
    target_name:      str   # nom du nouveau système
    agents_to_clone:  list[AgentCloneSpec] = field(default_factory=list)
    shared_schemas:   list[str]            = field(default_factory=list)
    new_templates:    list[str]            = field(default_factory=list)
    deploy_steps:     list[str]            = field(default_factory=list)
    estimated_effort: str                  = ""
    synthesis:        str                  = ""
    raw_llm:          str                  = ""

    def to_dict(self) -> dict:
        return {
            "source_system":    self.source_system,
            "target_context":   self.target_context,
            "target_name":      self.target_name,
            "agents_to_clone":  [
                {
                    "original_agent": a.original_agent,
                    "cloned_name":    a.cloned_name,
                    "new_sector":     a.new_sector,
                    "prompt_delta":   a.prompt_delta,
                }
                for a in self.agents_to_clone
            ],
            "shared_schemas":   self.shared_schemas,
            "new_templates":    self.new_templates,
            "deploy_steps":     self.deploy_steps,
            "estimated_effort": self.estimated_effort,
            "synthesis":        self.synthesis,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def summary_text(self) -> str:
        lines = [
            f"🔄 Meta Builder : {self.source_system} → {self.target_name}",
            f"📋 {len(self.agents_to_clone)} agent(s) à cloner",
            f"⏱ Effort estimé : {self.estimated_effort}",
            "",
        ]
        for a in self.agents_to_clone:
            lines.append(f"  ↳ {a.original_agent} → {a.cloned_name} ({a.new_sector})")
        if self.deploy_steps:
            lines += ["", "🚀 Étapes :"]
            lines += [f"  {i+1}. {s}" for i, s in enumerate(self.deploy_steps[:5])]
        if self.synthesis:
            lines += ["", f"📝 {self.synthesis[:300]}"]
        return "\n".join(lines)


def parse_meta_build_plan(raw: str, source: str, target: str) -> MetaBuildPlan:
    """Parse la sortie JSON du LLM en MetaBuildPlan."""
    import re

    plan = MetaBuildPlan(source_system=source, target_context=target,
                         target_name=target, raw_llm=raw)

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
            plan.synthesis = raw[:500]
            return plan
        try:
            data = json.loads(m.group(0))
        except Exception:
            plan.synthesis = raw[:500]
            return plan

    plan.target_name      = data.get("target_name", target)
    plan.synthesis        = data.get("synthesis", "")
    plan.estimated_effort = data.get("estimated_effort", "")
    plan.shared_schemas   = data.get("shared_schemas", [])
    plan.new_templates    = data.get("new_templates", [])
    plan.deploy_steps     = data.get("deploy_steps", [])

    for ac in data.get("agents_to_clone", []):
        plan.agents_to_clone.append(AgentCloneSpec(
            original_agent = ac.get("original_agent", ""),
            cloned_name    = ac.get("cloned_name",    ""),
            new_sector     = ac.get("new_sector",     ""),
            prompt_delta   = ac.get("prompt_delta",   ""),
        ))

    return plan
