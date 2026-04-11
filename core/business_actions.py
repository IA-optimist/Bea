"""
core/business_actions.py — Business Action Layer.

Turns structured business agent outputs into real workspace artifacts.
All actions are scoped to the workspace directory.
All risky actions are approval-gated.
All actions emit cognitive events.
All actions are fail-open for journaling.

Architecture:
  - BusinessAction: dataclass defining action spec
  - BusinessActionExecutor: takes agent output → produces real artifacts
  - Each action writes to workspace/business/<project_slug>/
  - Actions are registered in ACTION_REGISTRY for discovery
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
import structlog
from dataclasses import dataclass, field
from pathlib import Path

log = structlog.get_logger("business_actions")

_WORKSPACE = Path(os.environ.get("WORKSPACE_DIR", "workspace"))
_BUSINESS_DIR = _WORKSPACE / "business"


# ── Action Definition ─────────────────────────────────────────

@dataclass
class BusinessAction:
    """Specification for a business action."""
    action_id: str
    name: str
    description: str
    agent: str  # which business agent produces input for this
    risk_level: str = "low"  # low, medium, high
    requires_approval: bool = False
    required_tools: list[str] = field(default_factory=list)
    required_secrets: list[str] = field(default_factory=list)
    output_type: str = "files"  # files, trigger, report
    expected_outputs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "action_id": self.action_id,
            "name": self.name,
            "description": self.description,
            "agent": self.agent,
            "risk_level": self.risk_level,
            "requires_approval": self.requires_approval,
            "output_type": self.output_type,
            "expected_outputs": self.expected_outputs,
        }


# ── Action Registry ───────────────────────────────────────────

# ── Skill-to-Action mapping ────────────────────────────────────

ACTION_SKILLS: dict[str, list[str]] = {
    "venture.research_workspace": ["market_research.basic", "persona.basic"],
    "offer.package": ["offer_design.basic", "persona.basic"],
    "workflow.blueprint": ["automation_opportunity.basic"],
    "saas.mvp_spec": ["saas_scope.basic", "persona.basic", "acquisition.basic"],
    "workflow.n8n_trigger": [],
}


ACTION_REGISTRY: dict[str, BusinessAction] = {
    "venture.research_workspace": BusinessAction(
        action_id="venture.research_workspace",
        name="Create Venture Research Workspace",
        description="Analyze a sector and produce a structured research dossier with opportunities, competitive landscape, and recommended next steps.",
        agent="venture",
        risk_level="low",
        required_tools=["file_create", "create_directory"],
        output_type="files",
        expected_outputs=[
            "README.md",
            "opportunities.json",
            "analysis.md",
            "next-steps.md",
        ],
    ),
    "offer.package": BusinessAction(
        action_id="offer.package",
        name="Generate Offer Package",
        description="Transform a business opportunity into a complete offer package with pricing, personas, objection handling, and launch checklist.",
        agent="offer",
        risk_level="low",
        required_tools=["file_create", "create_directory"],
        output_type="files",
        expected_outputs=[
            "README.md",
            "offer-spec.json",
            "pricing.md",
            "personas.md",
            "objections.md",
            "launch-checklist.md",
        ],
    ),
    "workflow.blueprint": BusinessAction(
        action_id="workflow.blueprint",
        name="Generate Workflow Blueprint",
        description="Design business workflows with automation specs, n8n hints, and implementation roadmap.",
        agent="workflow",
        risk_level="low",
        required_tools=["file_create", "create_directory"],
        output_type="files",
        expected_outputs=[
            "README.md",
            "workflows.json",
            "automation-spec.md",
            "implementation-plan.md",
        ],
    ),
    "saas.mvp_spec": BusinessAction(
        action_id="saas.mvp_spec",
        name="Generate SaaS MVP Specification",
        description="Produce a complete MVP specification package with features, user stories, tech stack, and development roadmap.",
        agent="saas",
        risk_level="low",
        required_tools=["file_create", "create_directory"],
        output_type="files",
        expected_outputs=[
            "README.md",
            "mvp-spec.json",
            "features.md",
            "user-stories.md",
            "tech-stack.md",
            "roadmap.md",
        ],
    ),
    "workflow.n8n_trigger": BusinessAction(
        action_id="workflow.n8n_trigger",
        name="Trigger n8n Workflow",
        description="Trigger an existing n8n workflow via webhook URL. Requires approval.",
        agent="workflow",
        risk_level="medium",
        requires_approval=True,
        required_tools=["http_post_json"],
        required_secrets=["N8N_WEBHOOK_URL"],
        output_type="trigger",
        expected_outputs=["trigger-result.json"],
    ),
}


# ── Dependency checker ────────────────────────────────────────

def check_action_readiness(action_id: str) -> dict:
    """
    Check if an action has all dependencies met.

    Returns:
        {
            "action_id": str,
            "ready": bool,
            "missing_tools": list[str],
            "missing_secrets": list[str],
            "requires_approval": bool,
        }
    """
    action = ACTION_REGISTRY.get(action_id)
    if not action:
        return {"action_id": action_id, "ready": False, "error": "Unknown action"}

    missing_secrets = []
    for secret in action.required_secrets:
        if not os.environ.get(secret):
            missing_secrets.append(secret)

    # Tools are always available (built into ToolExecutor)
    # but we check if they're registered
    missing_tools = []
    try:
        from core.tool_executor import ToolExecutor
        te = ToolExecutor()
        for tool in action.required_tools:
            if tool not in te._tools:
                missing_tools.append(tool)
    except Exception:
        pass  # Can't check — assume available

    return {
        "action_id": action_id,
        "ready": len(missing_tools) == 0 and len(missing_secrets) == 0,
        "missing_tools": missing_tools,
        "missing_secrets": missing_secrets,
        "requires_approval": action.requires_approval,
        "risk_level": action.risk_level,
    }


# ── Slug helper ───────────────────────────────────────────────

def _slugify(text: str) -> str:
    """Convert text to a safe directory name."""
    s = text.lower().strip()
    s = re.sub(r'[^\w\s-]', '', s)
    s = re.sub(r'[\s_]+', '-', s)
    return s[:60] or "project"


# ── Business Action Executor ──────────────────────────────────

class BusinessActionExecutor:
    """
    Executes business actions by turning structured agent output into
    real workspace artifacts.

    Usage:
        executor = BusinessActionExecutor()
        result = executor.execute("venture.research_workspace", agent_output, mission_id="m1")
    """

    def execute(
        self,
        action_id: str,
        agent_output: dict,
        mission_id: str = "",
        project_name: str = "",
    ) -> dict:
        """
        Execute a business action.

        Returns:
            {
                "ok": bool,
                "action_id": str,
                "project_dir": str,
                "files_created": list[str],
                "error": str,
            }
        """
        action = ACTION_REGISTRY.get(action_id)
        if not action:
            return {"ok": False, "action_id": action_id, "error": f"Unknown action: {action_id}"}

        # Emit cognitive event: action started
        self._emit_event(action, mission_id, "started")

        try:
            # Determine project directory
            slug = _slugify(project_name or agent_output.get("sector", "")
                           or agent_output.get("product_name", "")
                           or agent_output.get("title", "")
                           or action.agent)
            timestamp = time.strftime("%Y%m%d-%H%M")
            project_dir = _BUSINESS_DIR / f"{slug}-{timestamp}"
            project_dir.mkdir(parents=True, exist_ok=True)

            # Approval gate for risky actions
            if action.requires_approval:
                try:
                    from core.cognitive_events.emitter import emit_approval_requested
                    emit_approval_requested(
                        mission_id=mission_id,
                        item_id=f"ba-{action_id}-{uuid.uuid4().hex[:8]}",
                        action=f"Execute business action: {action.name}",
                    )
                except Exception:
                    _silent_log.debug("suppressed_exception", src='business_actions.py')
                # For now, approval-gated actions produce a spec file
                # instead of executing. Real execution requires explicit
                # API call with approval_override=True.
                if not self._check_approval(action_id, mission_id):
                    spec_file = project_dir / "approval-required.md"
                    spec_content = f"# Approval Required\n\n"
                    spec_content += f"**Action:** {action.name}\n"
                    spec_content += f"**Risk:** {action.risk_level}\n"
                    spec_content += f"**Reason:** This action modifies external systems.\n\n"
                    spec_content += f"Approve via API: POST /api/v3/business-actions/execute "
                    spec_content += f"with approval_override=true\n"
                    self._write(spec_file, spec_content)

                    self._emit_event(action, mission_id, "awaiting_approval")
                    return {
                        "ok": True,
                        "action_id": action_id,
                        "project_dir": str(project_dir),
                        "files_created": ["approval-required.md"],
                        "awaiting_approval": True,
                        "error": "",
                    }

            # Dispatch to specific action handler
            handler_name = f"_execute_{action.agent}"
            # Some actions have action-specific handlers (e.g., n8n_trigger)
            if "." in action_id:
                specific = f"_execute_{action_id.replace('.', '_')}"
                if hasattr(self, specific):
                    handler_name = specific
            handler = getattr(self, handler_name, None)
            if not handler:
                return {"ok": False, "action_id": action_id,
                        "error": f"No handler for agent: {action.agent}"}

            # Load skill contexts and record usage (fail-open)
            skills_used = []
            try:
                from core.skills.domain_loader import get_domain_registry
                from core.skills.skill_feedback import get_feedback_store, SkillFeedback
                skill_ids = ACTION_SKILLS.get(action_id, [])
                registry = get_domain_registry()
                for sid in skill_ids:
                    skill = registry.get(sid)
                    if skill:
                        skills_used.append(sid)
                        get_feedback_store().record(SkillFeedback(
                            skill_id=sid, signal="success",
                            quality_score=1.0, mission_id=mission_id,
                            details=f"Used by action {action_id}",
                        ))
            except Exception:
                _silent_log.debug("suppressed_exception", src='business_actions.py')

            files = handler(action, agent_output, project_dir)

            # Write skill usage manifest
            if skills_used:
                try:
                    manifest = {
                        "action_id": action_id,
                        "skills_used": skills_used,
                        "timestamp": time.strftime("%Y-%m-%d %H:%M"),
                    }
                    self._write(
                        project_dir / "skills-used.json",
                        json.dumps(manifest, indent=2),
                    )
                    files.append("skills-used.json")
                except Exception:
                    _silent_log.debug("suppressed_exception", src='business_actions.py')

            # Emit cognitive event: action completed
            self._emit_event(action, mission_id, "completed",
                           files_created=len(files), project_dir=str(project_dir))

            log.info("business_action.completed",
                    action_id=action_id, project_dir=str(project_dir),
                    files=len(files))

            return {
                "ok": True,
                "action_id": action_id,
                "project_dir": str(project_dir),
                "files_created": files,
                "error": "",
            }

        except Exception as e:
            self._emit_event(action, mission_id, "failed", error=str(e)[:200])
            log.error("business_action.failed", action_id=action_id, err=str(e)[:200])
            return {"ok": False, "action_id": action_id, "error": str(e)[:200]}

    # ── Venture handler ───────────────────────────────────────

    def _execute_venture(
        self, action: BusinessAction, output: dict, project_dir: Path
    ) -> list[str]:
        """Create venture research workspace from VentureReport."""
        files = []

        # README.md
        sector = output.get("sector", "Unknown Sector")
        synthesis = output.get("synthesis", "")
        opps = output.get("opportunities", [])

        readme = f"# Venture Research: {sector}\n\n"
        readme += f"**Generated:** {time.strftime('%Y-%m-%d %H:%M')}\n\n"
        readme += f"## Synthesis\n\n{synthesis}\n\n"
        readme += f"## Opportunities ({len(opps)})\n\n"
        for i, opp in enumerate(opps, 1):
            title = opp.get("title", f"Opportunity {i}")
            score = opp.get("score", 0)
            readme += f"### {i}. {title} (score: {score}/10)\n\n"
            readme += f"**Problem:** {opp.get('problem', 'N/A')}\n\n"
            readme += f"**Target:** {opp.get('target', 'N/A')}\n\n"
            readme += f"**Offer idea:** {opp.get('offer_idea', 'N/A')}\n\n"
            readme += f"**Difficulty:** {opp.get('difficulty', 'N/A')}\n\n---\n\n"

        self._write(project_dir / "README.md", readme)
        files.append("README.md")

        # opportunities.json
        self._write(project_dir / "opportunities.json",
                   json.dumps(opps, indent=2, ensure_ascii=False))
        files.append("opportunities.json")

        # analysis.md — deeper breakdown
        analysis = f"# Sector Analysis: {sector}\n\n"
        analysis += f"## Market Overview\n\n{synthesis}\n\n"
        analysis += f"## Opportunity Details\n\n"
        for opp in opps:
            analysis += f"### {opp.get('title', '')}\n\n"
            analysis += f"- **Short term:** {opp.get('short_term', 'N/A')}\n"
            analysis += f"- **Long term:** {opp.get('long_term', 'N/A')}\n"
            analysis += f"- **Revenue model:** {opp.get('revenue_model', 'N/A')}\n"
            analysis += f"- **Competitors:** {opp.get('existing_competitors', 'N/A')}\n\n"
        self._write(project_dir / "analysis.md", analysis)
        files.append("analysis.md")

        # next-steps.md
        best = opps[0] if opps else {}
        steps = f"# Next Steps\n\n"
        steps += f"## Recommended Focus: {best.get('title', 'TBD')}\n\n"
        steps += f"### Week 1-2: Validation\n"
        steps += f"- [ ] Interview 5 potential customers in target segment\n"
        steps += f"- [ ] Research competitor pricing and features\n"
        steps += f"- [ ] Draft value proposition canvas\n\n"
        steps += f"### Week 3-4: MVP Design\n"
        steps += f"- [ ] Define minimum viable offer\n"
        steps += f"- [ ] Create landing page or demo\n"
        steps += f"- [ ] Set up measurement (analytics, CRM)\n\n"
        steps += f"### Month 2: First Revenue\n"
        steps += f"- [ ] Launch to first 10 customers\n"
        steps += f"- [ ] Collect feedback and iterate\n"
        steps += f"- [ ] Establish recurring revenue baseline\n"
        self._write(project_dir / "next-steps.md", steps)
        files.append("next-steps.md")

        return files

    # ── Offer handler ─────────────────────────────────────────

    def _execute_offer(
        self, action: BusinessAction, output: dict, project_dir: Path
    ) -> list[str]:
        """Create offer package from OfferReport."""
        files = []
        offers = output.get("offers", [])
        synthesis = output.get("synthesis", "")
        recommended = output.get("recommended", "")

        # README.md
        readme = f"# Offer Package: {recommended or 'Business Offer'}\n\n"
        readme += f"**Generated:** {time.strftime('%Y-%m-%d %H:%M')}\n\n"
        readme += f"## Strategy\n\n{synthesis}\n\n"
        readme += f"## Offers ({len(offers)})\n\n"
        for o in offers:
            readme += f"### {o.get('title', 'Offer')}\n"
            readme += f"> {o.get('tagline', '')}\n\n"
            readme += f"**Type:** {o.get('offer_type', 'N/A')} | "
            readme += f"**Delivery:** {o.get('delivery_mode', 'N/A')}\n\n"
        self._write(project_dir / "README.md", readme)
        files.append("README.md")

        # offer-spec.json
        self._write(project_dir / "offer-spec.json",
                   json.dumps(output, indent=2, ensure_ascii=False))
        files.append("offer-spec.json")

        # pricing.md
        pricing = "# Pricing Strategy\n\n"
        for o in offers:
            pricing += f"## {o.get('title', '')}\n\n"
            p = o.get("pricing", {})
            if isinstance(p, dict):
                pricing += f"- **Model:** {p.get('model', 'N/A')}\n"
                pricing += f"- **Price:** {p.get('price', 'N/A')}\n"
                pricing += f"- **Billing:** {p.get('billing_cycle', 'N/A')}\n"
                pricing += f"- **Free trial:** {p.get('free_trial', 'N/A')}\n\n"
            else:
                pricing += f"- **Price:** {p}\n\n"
        self._write(project_dir / "pricing.md", pricing)
        files.append("pricing.md")

        # personas.md
        personas = "# Target Personas\n\n"
        for o in offers:
            personas += f"## {o.get('title', '')}\n\n"
            personas += f"**Target:** {o.get('target_persona', 'N/A')}\n\n"
            personas += f"**Problem:** {o.get('problem_statement', 'N/A')}\n\n"
            personas += f"**Value:** {o.get('value_proposition', 'N/A')}\n\n---\n\n"
        self._write(project_dir / "personas.md", personas)
        files.append("personas.md")

        # objections.md
        objections = "# Objection Handling\n\n"
        for o in offers:
            objs = o.get("objection_handling", [])
            if objs:
                objections += f"## {o.get('title', '')}\n\n"
                for obj in objs:
                    if isinstance(obj, dict):
                        objections += f"### ❓ {obj.get('objection', '')}\n"
                        objections += f"**Response:** {obj.get('response', '')}\n\n"
                    else:
                        objections += f"- {obj}\n"
                objections += "\n"
        self._write(project_dir / "objections.md", objections)
        files.append("objections.md")

        # launch-checklist.md
        checklist = "# Launch Checklist\n\n"
        checklist += "## Pre-Launch\n"
        checklist += "- [ ] Finalize offer copy and pricing\n"
        checklist += "- [ ] Create landing page / sales deck\n"
        checklist += "- [ ] Set up payment processing\n"
        checklist += "- [ ] Prepare onboarding materials\n\n"
        checklist += "## Launch\n"
        checklist += "- [ ] Announce to initial target list\n"
        checklist += "- [ ] Monitor first 48h metrics\n"
        checklist += "- [ ] Collect early feedback\n\n"
        checklist += "## Post-Launch (Week 1)\n"
        checklist += "- [ ] Follow up with all leads\n"
        checklist += "- [ ] Iterate on objections received\n"
        checklist += "- [ ] Document conversion rate\n"
        self._write(project_dir / "launch-checklist.md", checklist)
        files.append("launch-checklist.md")

        return files

    # ── Workflow handler ──────────────────────────────────────

    def _execute_workflow(
        self, action: BusinessAction, output: dict, project_dir: Path
    ) -> list[str]:
        """Create workflow blueprint from WorkflowReport."""
        files = []
        workflows = output.get("workflows", [])
        synthesis = output.get("synthesis", "")

        # README.md
        readme = f"# Workflow Blueprint\n\n"
        readme += f"**Generated:** {time.strftime('%Y-%m-%d %H:%M')}\n\n"
        readme += f"## Overview\n\n{synthesis}\n\n"
        readme += f"## Workflows ({len(workflows)})\n\n"
        for w in workflows:
            readme += f"### {w.get('name', 'Workflow')}\n"
            readme += f"{w.get('description', '')}\n\n"
            readme += f"**Trigger:** {w.get('trigger', 'N/A')}\n"
            readme += f"**Goal:** {w.get('goal', 'N/A')}\n\n"
        self._write(project_dir / "README.md", readme)
        files.append("README.md")

        # workflows.json
        self._write(project_dir / "workflows.json",
                   json.dumps(workflows, indent=2, ensure_ascii=False))
        files.append("workflows.json")

        # automation-spec.md
        auto = "# Automation Specification\n\n"
        for w in workflows:
            auto += f"## {w.get('name', '')}\n\n"
            steps = w.get("steps", [])
            for s in steps:
                actor = s.get("actor", "unknown")
                icon = {"human": "👤", "ai": "🤖", "automation": "⚡", "system": "🔧"}.get(actor, "•")
                auto += f"- {icon} **{s.get('name', '')}** ({actor}): {s.get('description', '')}\n"
                if s.get("tool_hint"):
                    auto += f"  - Tool: `{s['tool_hint']}`\n"
                if s.get("n8n_node"):
                    auto += f"  - n8n: `{s['n8n_node']}`\n"
            auto += f"\n**Automation potential:** {w.get('automation_potential', 'N/A')}\n"
            auto += f"**Estimated ROI:** {w.get('roi_estimate', 'N/A')}\n\n---\n\n"
        self._write(project_dir / "automation-spec.md", auto)
        files.append("automation-spec.md")

        # implementation-plan.md
        plan = "# Implementation Plan\n\n"
        plan += "## Phase 1: Quick Wins (Week 1-2)\n"
        for w in workflows:
            for s in w.get("steps", []):
                if s.get("actor") == "automation" and s.get("tool_hint"):
                    plan += f"- [ ] Automate: {s.get('name', '')} using {s.get('tool_hint', '')}\n"
        plan += "\n## Phase 2: Integration (Week 3-4)\n"
        plan += "- [ ] Connect automation tools to business systems\n"
        plan += "- [ ] Set up monitoring and error handling\n"
        plan += "- [ ] Train team on new workflows\n\n"
        plan += "## Phase 3: Optimization (Month 2+)\n"
        plan += "- [ ] Measure time savings vs baseline\n"
        plan += "- [ ] Iterate on bottlenecks\n"
        plan += "- [ ] Expand automation coverage\n"
        self._write(project_dir / "implementation-plan.md", plan)
        files.append("implementation-plan.md")

        return files

    # ── SaaS handler ──────────────────────────────────────────

    def _execute_saas(
        self, action: BusinessAction, output: dict, project_dir: Path
    ) -> list[str]:
        """Create SaaS MVP spec from SaasReport."""
        files = []
        blueprints = output.get("blueprints", [])
        synthesis = output.get("synthesis", "")
        bp = blueprints[0] if blueprints else output

        product_name = bp.get("product_name", "SaaS Product")

        # README.md
        readme = f"# {product_name} — MVP Specification\n\n"
        readme += f"**Generated:** {time.strftime('%Y-%m-%d %H:%M')}\n\n"
        readme += f"> {bp.get('tagline', '')}\n\n"
        readme += f"## Vision\n\n{synthesis}\n\n"
        readme += f"## Problem\n\n{bp.get('problem', 'N/A')}\n\n"
        readme += f"## Solution\n\n{bp.get('solution', 'N/A')}\n\n"
        readme += f"## MVP Scope\n\n{bp.get('mvp_scope', 'N/A')}\n"
        self._write(project_dir / "README.md", readme)
        files.append("README.md")

        # mvp-spec.json
        self._write(project_dir / "mvp-spec.json",
                   json.dumps(bp, indent=2, ensure_ascii=False))
        files.append("mvp-spec.json")

        # features.md
        features_md = f"# Features — {product_name}\n\n"
        for f in bp.get("features", []):
            prio = f.get("priority", "should")
            icon = {"must": "🔴", "should": "🟡", "could": "🟢", "wont": "⚪"}.get(prio, "•")
            features_md += f"{icon} **{f.get('name', '')}** ({prio}, effort: {f.get('effort', '?')})\n"
            features_md += f"  {f.get('description', '')}\n\n"
        self._write(project_dir / "features.md", features_md)
        files.append("features.md")

        # user-stories.md
        stories = f"# User Stories — {product_name}\n\n"
        stories += f"**Target user:** {bp.get('target_user', 'N/A')}\n\n"
        for f in bp.get("features", []):
            story = f.get("user_story", "")
            if story:
                stories += f"- {story}\n"
        self._write(project_dir / "user-stories.md", stories)
        files.append("user-stories.md")

        # tech-stack.md
        tech = bp.get("tech_stack", {})
        tech_md = f"# Tech Stack — {product_name}\n\n"
        if isinstance(tech, dict):
            for k, v in tech.items():
                tech_md += f"- **{k}:** {v}\n"
        elif isinstance(tech, list):
            for item in tech:
                tech_md += f"- {item}\n"
        else:
            tech_md += f"{tech}\n"
        self._write(project_dir / "tech-stack.md", tech_md)
        files.append("tech-stack.md")

        # roadmap.md
        roadmap = f"# Development Roadmap — {product_name}\n\n"
        roadmap += "## Sprint 1 (Week 1-2): Core\n"
        must_features = [f for f in bp.get("features", []) if f.get("priority") == "must"]
        for f in must_features[:5]:
            roadmap += f"- [ ] {f.get('name', '')}\n"
        roadmap += "\n## Sprint 2 (Week 3-4): Polish\n"
        should_features = [f for f in bp.get("features", []) if f.get("priority") == "should"]
        for f in should_features[:5]:
            roadmap += f"- [ ] {f.get('name', '')}\n"
        roadmap += "\n## Sprint 3 (Week 5-6): Launch\n"
        roadmap += "- [ ] Deploy to production\n"
        roadmap += "- [ ] Onboard beta users\n"
        roadmap += "- [ ] Set up analytics and monitoring\n"
        self._write(project_dir / "roadmap.md", roadmap)
        files.append("roadmap.md")

        return files

    # ── Helpers ────────────────────────────────────────────────

    # ── n8n trigger handler ──────────────────────────────────

    def _execute_workflow_n8n_trigger(
        self, action: BusinessAction, output: dict, project_dir: Path
    ) -> list[str]:
        """Trigger an n8n workflow via webhook."""
        files = []
        webhook_url = os.environ.get("N8N_WEBHOOK_URL", "")
        if not webhook_url:
            # No webhook URL — produce spec only
            spec = "# n8n Trigger — Not Configured\n\n"
            spec += "Set `N8N_WEBHOOK_URL` environment variable to enable.\n"
            self._write(project_dir / "trigger-result.json",
                       json.dumps({"status": "not_configured", "reason": "N8N_WEBHOOK_URL not set"}))
            files.append("trigger-result.json")
            return files

        # Trigger the webhook
        import urllib.request
        payload = json.dumps(output).encode("utf-8")
        try:
            req = urllib.request.Request(
                webhook_url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = resp.read().decode("utf-8")[:2000]
                status = resp.status
        except Exception as e:
            result = str(e)[:500]
            status = 0

        trigger_result = {
            "status": "triggered" if status == 200 else "failed",
            "http_status": status,
            "response": result[:500],
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._write(project_dir / "trigger-result.json",
                   json.dumps(trigger_result, indent=2))
        files.append("trigger-result.json")
        return files

    def _check_approval(self, action_id: str, mission_id: str) -> bool:
        """Check if action has been pre-approved. Always False for now."""
        # In future: check approval store for this action+mission
        return False

    def _write(self, path: Path, content: str) -> None:
        """Write content to file, creating parent dirs."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, "utf-8")

    def _emit_event(self, action: BusinessAction, mission_id: str,
                    status: str, **extra) -> None:
        """Emit cognitive event for business action (fail-open)."""
        try:
            from core.cognitive_events.emitter import emit
            from core.cognitive_events.types import EventType, EventSeverity
            sev = EventSeverity.INFO if status != "failed" else EventSeverity.WARNING
            emit(
                EventType.SYSTEM_EVENT,
                summary=f"Business action {action.action_id}: {status}",
                source="business_actions",
                mission_id=mission_id,
                severity=sev,
                payload={
                    "action_id": action.action_id,
                    "agent": action.agent,
                    "status": status,
                    "risk_level": action.risk_level,
                    **{k: str(v)[:200] for k, v in extra.items()},
                },
                tags=["business", action.agent],
            )
        except Exception:
            _silent_log.debug("suppressed_exception", src='business_actions.py')


# ── Singleton ─────────────────────────────────────────────────

_executor: BusinessActionExecutor | None = None


def get_business_executor() -> BusinessActionExecutor:
    global _executor
    if _executor is None:
        _executor = BusinessActionExecutor()
    return _executor


def list_actions() -> list[dict]:
    """List all registered business actions."""
    return [a.to_dict() for a in ACTION_REGISTRY.values()]
