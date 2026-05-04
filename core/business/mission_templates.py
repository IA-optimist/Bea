"""
JARVIS MAX — Mission Templates
==================================
Built-in templates for common business missions.

Each template defines:
- Steps with agent assignments
- Required tools, connectors, identities
- Approval gates at critical points
- Risk levels per step

Templates are blueprints — instantiated into real Missions by the engine.
"""
from __future__ import annotations

from core.business.mission_schema import (
    Mission, MissionStep, Priority, RiskLevel,
)


# ═══════════════════════════════════════════════════════════════
# TEMPLATE DEFINITIONS
# ═══════════════════════════════════════════════════════════════

TEMPLATES: dict[str, dict] = {

    "market_research": {
        "title": "Market Research",
        "description": "Research market size, competitors, and customer personas for a given industry or product idea.",
        "priority": Priority.MEDIUM.value,
        "risk_level": RiskLevel.LOW.value,
        "steps": [
            {"name": "Define scope", "description": "Clarify target market, geography, and product category", "agent": "research"},
            {"name": "Market sizing", "description": "Estimate TAM, SAM, SOM using public data sources", "agent": "research", "required_tools": ["web_search"]},
            {"name": "Competitor analysis", "description": "Identify top 5-10 competitors, pricing, features", "agent": "research", "required_tools": ["web_search"]},
            {"name": "Customer personas", "description": "Define 3-5 ideal customer profiles with pain points", "agent": "research"},
            {"name": "Generate report", "description": "Compile findings into structured market report", "agent": "research", "required_tools": ["file_write"]},
        ],
    },

    "lead_generation": {
        "title": "Lead Generation Campaign",
        "description": "Set up and run an automated lead generation campaign with landing page, email sequences, and tracking.",
        "priority": Priority.HIGH.value,
        "risk_level": RiskLevel.MEDIUM.value,
        "steps": [
            {"name": "Define ICP", "description": "Define ideal customer profile and targeting criteria", "agent": "research"},
            {"name": "Create landing page", "description": "Generate landing page with value prop and signup form", "agent": "content", "required_tools": ["file_write"], "required_connectors": ["vercel"]},
            {"name": "Email sequence", "description": "Write 5-email nurture sequence for leads", "agent": "content", "required_tools": ["file_write"]},
            {"name": "Configure email", "description": "Set up email sending with configured identity", "agent": "ops", "required_connectors": ["gmail"], "required_identities": ["email"], "approval_required": True},
            {"name": "Deploy page", "description": "Deploy landing page to hosting provider", "agent": "ops", "required_connectors": ["vercel"], "approval_required": True},
            {"name": "Activate campaign", "description": "Start sending and tracking", "agent": "ops", "approval_required": True},
        ],
    },

    "saas_setup": {
        "title": "SaaS Product Setup",
        "description": "Set up a SaaS product with Stripe payments, domain, frontend deployment, and monitoring.",
        "priority": Priority.HIGH.value,
        "risk_level": RiskLevel.HIGH.value,
        "steps": [
            {"name": "Define product", "description": "Specify product name, tiers, pricing", "agent": "research"},
            {"name": "Setup Stripe", "description": "Create Stripe product and price objects", "agent": "ops", "required_connectors": ["stripe"], "required_identities": ["stripe"], "approval_required": True, "risk_level": RiskLevel.HIGH.value},
            {"name": "Create landing page", "description": "Generate marketing landing page with pricing", "agent": "content", "required_tools": ["file_write"]},
            {"name": "Configure domain", "description": "Set up domain DNS records", "agent": "ops", "required_connectors": ["cloudflare"], "required_identities": ["cloudflare"], "approval_required": True},
            {"name": "Deploy frontend", "description": "Deploy landing page to Vercel", "agent": "ops", "required_connectors": ["vercel"], "approval_required": True},
            {"name": "Setup monitoring", "description": "Configure uptime and error monitoring", "agent": "ops"},
            {"name": "Validation test", "description": "End-to-end test of signup + payment flow", "agent": "qa", "approval_required": True},
        ],
    },

    "landing_page": {
        "title": "Landing Page Creation",
        "description": "Design, build, and deploy a conversion-optimized landing page.",
        "priority": Priority.MEDIUM.value,
        "risk_level": RiskLevel.LOW.value,
        "steps": [
            {"name": "Define value prop", "description": "Clarify unique value proposition and target audience", "agent": "research"},
            {"name": "Generate copy", "description": "Write headline, subheading, CTAs, feature blocks", "agent": "content"},
            {"name": "Build page", "description": "Generate responsive HTML/CSS landing page", "agent": "coder", "required_tools": ["file_write"]},
            {"name": "Review", "description": "Review page for quality, mobile responsiveness", "agent": "reviewer"},
            {"name": "Deploy", "description": "Deploy to hosting provider", "agent": "ops", "required_connectors": ["vercel"], "approval_required": True},
        ],
    },

    "competitor_analysis": {
        "title": "Competitor Analysis",
        "description": "Deep analysis of competitors including pricing, features, strengths/weaknesses, and market positioning.",
        "priority": Priority.MEDIUM.value,
        "risk_level": RiskLevel.LOW.value,
        "steps": [
            {"name": "Identify competitors", "description": "Find top 5-10 direct and indirect competitors", "agent": "research", "required_tools": ["web_search"]},
            {"name": "Feature comparison", "description": "Build feature matrix across competitors", "agent": "research", "required_tools": ["web_search"]},
            {"name": "Pricing analysis", "description": "Map pricing tiers and strategies", "agent": "research"},
            {"name": "SWOT analysis", "description": "Strengths, weaknesses, opportunities, threats per competitor", "agent": "research"},
            {"name": "Generate report", "description": "Compile competitive analysis report with recommendations", "agent": "content", "required_tools": ["file_write"]},
        ],
    },

    "email_automation": {
        "title": "Email Automation Setup",
        "description": "Create and configure automated email workflows: welcome series, follow-ups, newsletters.",
        "priority": Priority.MEDIUM.value,
        "risk_level": RiskLevel.MEDIUM.value,
        "steps": [
            {"name": "Define workflows", "description": "Map email triggers, sequences, and segments", "agent": "research"},
            {"name": "Write emails", "description": "Create email templates for each workflow", "agent": "content", "required_tools": ["file_write"]},
            {"name": "Create account", "description": "Set up email sending identity", "agent": "ops", "required_identities": ["email"], "approval_required": True},
            {"name": "Configure automation", "description": "Set up triggers and scheduling rules", "agent": "ops", "required_connectors": ["gmail"]},
            {"name": "Test delivery", "description": "Send test emails and verify delivery", "agent": "qa", "required_connectors": ["gmail"], "approval_required": True},
            {"name": "Activate", "description": "Enable automation workflows", "agent": "ops", "approval_required": True},
        ],
    },

    "product_validation": {
        "title": "Product Validation",
        "description": "Validate a product idea through market research, MVP prototype, and user feedback collection.",
        "priority": Priority.HIGH.value,
        "risk_level": RiskLevel.MEDIUM.value,
        "steps": [
            {"name": "Problem validation", "description": "Research if the problem is real and worth solving", "agent": "research", "required_tools": ["web_search"]},
            {"name": "Solution hypothesis", "description": "Define minimum viable solution and success criteria", "agent": "research"},
            {"name": "Build MVP", "description": "Create minimal prototype or mockup", "agent": "coder", "required_tools": ["file_write"]},
            {"name": "Create landing page", "description": "Build signup page to gauge interest", "agent": "content", "required_tools": ["file_write"]},
            {"name": "Deploy test", "description": "Deploy MVP and landing page", "agent": "ops", "required_connectors": ["vercel"], "approval_required": True},
            {"name": "Collect feedback", "description": "Monitor signups and collect user feedback", "agent": "research"},
            {"name": "Analysis report", "description": "Analyze results and recommend go/no-go", "agent": "research", "required_tools": ["file_write"]},
        ],
    },
}


# ═══════════════════════════════════════════════════════════════
# TEMPLATE API
# ═══════════════════════════════════════════════════════════════

def list_templates() -> list[dict]:
    """List all available templates."""
    return [
        {
            "id": tid,
            "title": tpl["title"],
            "description": tpl["description"],
            "step_count": len(tpl["steps"]),
            "priority": tpl.get("priority", "medium"),
            "risk_level": tpl.get("risk_level", "medium"),
        }
        for tid, tpl in TEMPLATES.items()
    ]


def get_template(template_id: str) -> dict | None:
    """Get a template by ID."""
    return TEMPLATES.get(template_id)


def instantiate_template(template_id: str, objective: str = "", overrides: dict | None = None) -> Mission | None:
    """
    Create a Mission from a template.
    
    Overrides can include: title, description, priority, risk_level.
    """
    tpl = TEMPLATES.get(template_id)
    if not tpl:
        return None

    overrides = overrides or {}

    # Build steps
    steps = []
    for i, step_def in enumerate(tpl["steps"]):
        step = MissionStep(
            step_id=f"step-{i+1:02d}",
            name=step_def["name"],
            description=step_def.get("description", ""),
            agent=step_def.get("agent", ""),
            required_tools=step_def.get("required_tools", []),
            required_connectors=step_def.get("required_connectors", []),
            required_identities=step_def.get("required_identities", []),
            required_secrets=step_def.get("required_secrets", []),
            approval_required=step_def.get("approval_required", False),
            risk_level=step_def.get("risk_level", RiskLevel.LOW.value),
            depends_on=[f"step-{i:02d}"] if i > 0 else [],  # Sequential by default
        )
        steps.append(step)

    # Collect all requirements from steps
    all_tools = sorted(set(t for s in steps for t in s.required_tools))
    all_connectors = sorted(set(c for s in steps for c in s.required_connectors))
    all_identities = sorted(set(i for s in steps for i in s.required_identities))
    all_agents = sorted(set(s.agent for s in steps if s.agent))

    mission = Mission(
        title=overrides.get("title", tpl["title"]),
        description=overrides.get("description", tpl["description"]),
        objective=objective or tpl["description"],
        priority=overrides.get("priority", tpl.get("priority", Priority.MEDIUM.value)),
        risk_level=overrides.get("risk_level", tpl.get("risk_level", RiskLevel.MEDIUM.value)),
        template_id=template_id,
        steps=steps,
        assigned_agents=all_agents,
        required_tools=all_tools,
        required_connectors=all_connectors,
        required_identities=all_identities,
    )

    return mission
