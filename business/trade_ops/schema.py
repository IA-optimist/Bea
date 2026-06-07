"""
BEA BUSINESS LAYER — Trade Ops : Schémas de données
Modélise un agent IA métier spécialisé pour les métiers de terrain / TPE.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import json


@dataclass
class TradeAgentConfig:
    """Configuration d'un agent IA spécialisé pour un métier."""
    agent_name:      str
    sector:          str          # ex: "chauffage", "electricite", "maconnerie"
    company_name:    str
    system_prompt:   str          # prompt système final (peut être long)
    capabilities:    list[str]    = field(default_factory=list)
    knowledge_keys:  list[str]    = field(default_factory=list)  # clés knowledge base
    suggested_workflows: list[str] = field(default_factory=list)
    tools_needed:    list[str]    = field(default_factory=list)
    deployment_mode: str          = "api"  # "web"|"api"|"whatsapp"|"generic"

    def to_dict(self) -> dict:
        return {
            "agent_name":          self.agent_name,
            "sector":              self.sector,
            "company_name":        self.company_name,
            "capabilities":        self.capabilities,
            "knowledge_keys":      self.knowledge_keys,
            "suggested_workflows": self.suggested_workflows,
            "tools_needed":        self.tools_needed,
            "deployment_mode":     self.deployment_mode,
            "system_prompt_length": len(self.system_prompt),
        }


@dataclass
class TradeOpsSpec:
    """Spécification complète d'un agent Trade Ops généré."""
    trade:            str          # métier ciblé
    company_name:     str
    agent_config:     TradeAgentConfig
    use_cases:        list[str]    = field(default_factory=list)
    roi_estimate:     str          = ""
    setup_steps:      list[str]    = field(default_factory=list)
    monthly_value:    str          = ""   # valeur mensuelle estimée pour l'entreprise
    build_complexity: str          = "low"  # "low"|"medium"|"high"
    raw_llm:          str          = ""
    synthesis:        str          = ""

    def to_dict(self) -> dict:
        return {
            "trade":          self.trade,
            "company_name":   self.company_name,
            "agent_config":   self.agent_config.to_dict(),
            "use_cases":      self.use_cases,
            "roi_estimate":   self.roi_estimate,
            "setup_steps":    self.setup_steps,
            "monthly_value":  self.monthly_value,
            "build_complexity": self.build_complexity,
            "synthesis":      self.synthesis,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def format_card(self) -> str:
        return (
            f"🏗️ Agent IA Métier : {self.trade}\n"
            f"🏢 Client : {self.company_name}\n"
            f"⚡ {len(self.use_cases)} cas d'usage\n"
            f"📈 Valeur mensuelle : {self.monthly_value}\n"
            f"🔨 Complexité : {self.build_complexity}\n"
            f"💡 ROI : {self.roi_estimate[:80]}"
        )

    def summary_text(self) -> str:
        lines = [
            self.format_card(),
            "",
            "📋 Cas d'usage :",
            *[f"  • {uc}" for uc in self.use_cases[:5]],
            "",
            "🚀 Étapes de mise en place :",
            *[f"  {i+1}. {s}" for i, s in enumerate(self.setup_steps[:5])],
        ]
        if self.synthesis:
            lines += ["", f"📝 {self.synthesis[:300]}"]
        return "\n".join(lines)


def parse_trade_ops_spec(raw: str, trade: str, company_name: str,
                         system_prompt: str = "") -> TradeOpsSpec:
    """Parse la sortie JSON du LLM en TradeOpsSpec. Robuste aux erreurs."""
    import re

    dummy_config = TradeAgentConfig(
        agent_name   = f"agent-{trade.lower().replace(' ', '-')}",
        sector       = trade,
        company_name = company_name,
        system_prompt= system_prompt,
    )
    spec = TradeOpsSpec(trade=trade, company_name=company_name,
                        agent_config=dummy_config, raw_llm=raw)

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
            spec.synthesis = raw[:500]
            return spec
        try:
            data = json.loads(m.group(0))
        except Exception:
            spec.synthesis = raw[:500]
            return spec

    spec.synthesis      = data.get("synthesis", "")
    spec.use_cases      = data.get("use_cases", [])
    spec.roi_estimate   = data.get("roi_estimate", "")
    spec.setup_steps    = data.get("setup_steps", [])
    spec.monthly_value  = data.get("monthly_value", "")
    spec.build_complexity = data.get("build_complexity", "low")

    ac_data = data.get("agent_config", {})
    if ac_data:
        spec.agent_config = TradeAgentConfig(
            agent_name      = ac_data.get("agent_name", dummy_config.agent_name),
            sector          = ac_data.get("sector", trade),
            company_name    = company_name,
            system_prompt   = system_prompt or ac_data.get("system_prompt", ""),
            capabilities    = ac_data.get("capabilities", []),
            knowledge_keys  = ac_data.get("knowledge_keys", []),
            suggested_workflows = ac_data.get("suggested_workflows", []),
            tools_needed    = ac_data.get("tools_needed", []),
            deployment_mode = ac_data.get("deployment_mode", "api"),
        )

    return spec
