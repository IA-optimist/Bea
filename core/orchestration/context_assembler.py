"""
core/orchestration/context_assembler.py — Build rich execution context for a mission.

Gathers relevant memory, skills, recent failures, and system health
into a single planning-ready context object.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import structlog

log = structlog.get_logger("orchestration.context")


@dataclass
class MissionContext:
    """Rich context assembled before mission execution."""
    mission_id: str = ""
    goal: str = ""
    classification: dict = field(default_factory=dict)

    # Retrieved context
    prior_skills: list[dict] = field(default_factory=list)
    relevant_memories: list[dict] = field(default_factory=list)
    recent_failures: list[dict] = field(default_factory=list)
    system_health: dict = field(default_factory=dict)

    # Planning inputs
    available_tools: list[str] = field(default_factory=list)
    suggested_approach: str = ""
    estimated_steps: int = 1

    assembled_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "mission_id": self.mission_id,
            "goal": self.goal[:200],
            "classification": self.classification,
            "prior_skills_count": len(self.prior_skills),
            "relevant_memories_count": len(self.relevant_memories),
            "recent_failures_count": len(self.recent_failures),
            "system_health_status": self.system_health.get("status", "unknown"),
            "suggested_approach": self.suggested_approach,
            "estimated_steps": self.estimated_steps,
        }

    def planning_prompt_context(self) -> str:
        """Format context for injection into planning prompts."""
        parts = []
        if self.prior_skills:
            parts.append("## Prior Skills")
            for s in self.prior_skills[:3]:
                parts.append(f"- {s.get('name', '?')}: {', '.join(s.get('steps', [])[:3])}")
        if self.relevant_memories:
            parts.append("## Relevant Memory")
            for m in self.relevant_memories[:3]:
                parts.append(f"- {str(m.get('content', ''))[:100]}")
        if self.recent_failures:
            parts.append("## Recent Failures (avoid repeating)")
            for f in self.recent_failures[:2]:
                parts.append(f"- {str(f.get('error', ''))[:80]}")
        return "\n".join(parts) if parts else ""


def assemble(
    mission_id: str,
    goal: str,
    classification: dict,
) -> MissionContext:
    """
    Assemble rich context for a mission. Non-critical — each retrieval
    is independently wrapped so failures don't block execution.
    """
    ctx = MissionContext(
        mission_id=mission_id,
        goal=goal,
        classification=classification,
    )

    # 1. Retrieve skills
    try:
        from core.skills import get_skill_service
        ctx.prior_skills = get_skill_service().retrieve_for_mission(goal, top_k=3)
    except Exception:
        _silent_log.debug("suppressed_exception", src='context_assembler.py')

    # 2. Retrieve relevant memory
    try:
        from core.memory_facade import get_memory_facade
        facade = get_memory_facade()
        entries = facade.search(goal, top_k=3)
        ctx.relevant_memories = [
            {"content": e.content[:200], "type": e.content_type, "score": e.score}
            for e in entries
        ]
    except Exception:
        _silent_log.debug("suppressed_exception", src='context_assembler.py')

    # 3. Recent failures
    try:
        from core.memory_facade import get_memory_facade
        facade = get_memory_facade()
        failures = facade.search("failure error", content_type="failure", top_k=2)
        ctx.recent_failures = [
            {"error": e.content[:100], "type": e.content_type}
            for e in failures
        ]
    except Exception:
        _silent_log.debug("suppressed_exception", src='context_assembler.py')

    # 4. System health
    try:
        from agents.monitoring_agent import MonitoringAgent
        from config.settings import get_settings
        agent = MonitoringAgent(get_settings())
        ctx.system_health = agent.health_sync()
    except Exception:
        ctx.system_health = {"status": "unknown"}

    # 5. Determine approach
    complexity = classification.get("complexity", "simple")
    if complexity == "trivial":
        ctx.suggested_approach = "direct_answer"
        ctx.estimated_steps = 1
    elif complexity == "simple":
        ctx.suggested_approach = "single_tool"
        ctx.estimated_steps = 2
    elif complexity == "moderate":
        ctx.suggested_approach = "multi_step_plan"
        ctx.estimated_steps = 4
    else:
        ctx.suggested_approach = "decompose_and_plan"
        ctx.estimated_steps = 6

    ctx.available_tools = classification.get("suggested_tools", [])

    # 6. Business reasoning override
    if classification.get("task_type") == "business":
        try:
            from core.skills.business_reasoning import OpportunityType
            ctx.suggested_approach = "business_structured_analysis"
            ctx.estimated_steps = 4
        except Exception:
            _silent_log.debug("suppressed_exception", src='context_assembler.py')

    log.info("context_assembled",
             mission_id=mission_id,
             skills=len(ctx.prior_skills),
             memories=len(ctx.relevant_memories),
             failures=len(ctx.recent_failures),
             approach=ctx.suggested_approach)

    return ctx
