"""
BEA MAX — Template Registry
================================
Central registry for all business agent templates.
Supports loading from Python modules and future YAML/JSON files.
"""
from __future__ import annotations

from business_agents.template_schema import BusinessAgentTemplate

# Built-in templates
from business_agents.templates.quote_agent import QUOTE_AGENT_TEMPLATE
from business_agents.templates.support_agent import SUPPORT_AGENT_TEMPLATE
from business_agents.templates.content_agent import CONTENT_AGENT_TEMPLATE


_TEMPLATES: dict[str, BusinessAgentTemplate] = {
    "quote_agent": QUOTE_AGENT_TEMPLATE,
    "support_agent": SUPPORT_AGENT_TEMPLATE,
    "content_agent": CONTENT_AGENT_TEMPLATE,
}


def register_template(template: BusinessAgentTemplate) -> None:
    """Register a new template. Validates before adding."""
    errors = template.validate()
    if errors:
        raise ValueError(f"Invalid template '{template.agent_name}': {errors}")
    _TEMPLATES[template.agent_name] = template


def get_template(name: str) -> BusinessAgentTemplate | None:
    return _TEMPLATES.get(name)


def list_templates() -> list[dict]:
    return [
        {
            "name": t.agent_name,
            "category": t.category,
            "business_type": t.business_type,
            "purpose": t.purpose,
            "version": t.version,
            "risk_profile": t.risk_profile,
            "capabilities": len(t.allowed_capabilities),
            "tools": len(t.required_tools),
        }
        for t in _TEMPLATES.values()
    ]


def get_all_templates() -> dict[str, BusinessAgentTemplate]:
    return dict(_TEMPLATES)
