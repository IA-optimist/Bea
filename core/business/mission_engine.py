"""
BEA MAX — Business Mission Engine
========================================
Top-level orchestrator for structured multi-step business missions.

Combines:
- Mission schema (data models)
- Mission templates (blueprints)
- Mission runner (execution)
- Mission memory (learning)
- Mission audit (compliance)
- Dependency validation
- Approval integration

This is the single entry point for all mission operations.
"""
from __future__ import annotations

import logging

from core.business.mission_schema import (
    Mission, MissionStep, MissionStatus, StepStatus, Priority, RiskLevel,
    DependencyCheckResult,
)
from core.business.mission_templates import (
    list_templates, get_template, instantiate_template, TEMPLATES,
)
from core.business.mission_runner import (
    MissionRunner, StepExecutor, DependencyValidator,
)
from core.business.mission_memory import MissionMemory, MissionMemoryEntry
from core.business.mission_audit import MissionAuditLog, AuditEvent

logger = logging.getLogger(__name__)


class MissionEngine:
    """
    Business Mission Engine — the unified API for mission lifecycle.
    
    Usage:
        engine = MissionEngine()
        mission = engine.create_from_template("saas_setup", objective="Launch my SaaS")
        deps = engine.check_dependencies(mission.mission_id)
        if deps.valid:
            engine.start(mission.mission_id)
            while not engine.get(mission.mission_id).is_terminal:
                engine.execute_next(mission.mission_id)
    """

    def __init__(
        self,
        tool_executor=None,
        approval_notifier=None,
        available_connectors: set[str] | None = None,
        available_secrets: set[str] | None = None,
        available_identities: set[str] | None = None,
        available_agents: set[str] | None = None,
        available_tools: set[str] | None = None,
        memory_path: str = "",
    ):
        # State
        self._missions: dict[str, Mission] = {}

        # Sub-systems
        self._audit = MissionAuditLog()
        self._memory = MissionMemory(storage_path=memory_path)

        self._validator = DependencyValidator(
            available_connectors=available_connectors,
            available_secrets=available_secrets,
            available_identities=available_identities,
            available_agents=available_agents,
            available_tools=available_tools,
        )

        self._step_executor = StepExecutor(
            tool_executor=tool_executor,
            approval_notifier=approval_notifier,
        )

        self._runner = MissionRunner(
            step_executor=self._step_executor,
            audit=self._audit,
            dependency_validator=self._validator,
        )

    # ═══════════════════════════════════════════════════════════════
    # CREATE
    # ═══════════════════════════════════════════════════════════════

    def create(
        self,
        title: str,
        objective: str,
        description: str = "",
        priority: str = Priority.MEDIUM.value,
        risk_level: str = RiskLevel.MEDIUM.value,
        steps: list[dict] | None = None,
    ) -> Mission:
        """Create a custom mission from scratch."""
        mission = Mission(
            title=title,
            objective=objective,
            description=description or objective,
            priority=priority,
            risk_level=risk_level,
        )

        if steps:
            for i, step_def in enumerate(steps):
                step = MissionStep(
                    step_id=step_def.get("step_id", f"step-{i+1:02d}"),
                    name=step_def.get("name", f"Step {i+1}"),
                    description=step_def.get("description", ""),
                    agent=step_def.get("agent", ""),
                    required_tools=step_def.get("required_tools", []),
                    required_connectors=step_def.get("required_connectors", []),
                    required_identities=step_def.get("required_identities", []),
                    required_secrets=step_def.get("required_secrets", []),
                    depends_on=step_def.get("depends_on", [f"step-{i:02d}"] if i > 0 else []),
                    approval_required=step_def.get("approval_required", False),
                    risk_level=step_def.get("risk_level", RiskLevel.LOW.value),
                    timeout_seconds=step_def.get("timeout_seconds", 300),
                )
                mission.steps.append(step)

            # Collect assignments
            mission.assigned_agents = sorted(set(s.agent for s in mission.steps if s.agent))
            mission.required_tools = sorted(set(t for s in mission.steps for t in s.required_tools))
            mission.required_connectors = sorted(set(c for s in mission.steps for c in s.required_connectors))
            mission.required_identities = sorted(set(i for s in mission.steps for i in s.required_identities))

        self._missions[mission.mission_id] = mission
        self._audit.log(
            AuditEvent.MISSION_CREATED, mission.mission_id,
            details={"title": title, "steps": len(mission.steps)},
        )
        return mission

    def create_from_template(
        self,
        template_id: str,
        objective: str = "",
        overrides: dict | None = None,
    ) -> Mission | None:
        """Create a mission from a built-in template."""
        mission = instantiate_template(template_id, objective, overrides)
        if not mission:
            return None

        self._missions[mission.mission_id] = mission
        self._audit.log(
            AuditEvent.MISSION_CREATED, mission.mission_id,
            details={"template": template_id, "steps": len(mission.steps)},
        )
        return mission

    # ═══════════════════════════════════════════════════════════════
    # LIFECYCLE
    # ═══════════════════════════════════════════════════════════════

    def check_dependencies(self, mission_id: str) -> DependencyCheckResult:
        """Check if all mission dependencies are available."""
        mission = self._missions.get(mission_id)
        if not mission:
            return DependencyCheckResult(valid=False, suggestions=["Mission not found"])
        return self._runner.validate_dependencies(mission)

    def plan(self, mission_id: str) -> Mission | None:
        """Plan the mission (draft → planned)."""
        mission = self._missions.get(mission_id)
        if not mission:
            return None
        return self._runner.plan(mission)

    def start(self, mission_id: str) -> Mission | None:
        """Start or resume the mission."""
        mission = self._missions.get(mission_id)
        if not mission:
            return None

        # Auto-plan if still draft
        if mission.status == MissionStatus.DRAFT.value:
            self._runner.plan(mission)

        return self._runner.start(mission)

    def execute_next(self, mission_id: str) -> dict:
        """Execute the next available step."""
        mission = self._missions.get(mission_id)
        if not mission:
            return {"executed": False, "reason": "Mission not found"}
        result = self._runner.execute_next_step(mission)

        # Record to memory on completion/failure
        if mission.is_terminal:
            self._record_memory(mission)

        return result

    def run(self, mission_id: str, max_iterations: int = 50) -> Mission | None:
        """Run mission to completion (or until approval needed)."""
        mission = self._missions.get(mission_id)
        if not mission:
            return None
        mission = self._runner.run_to_completion(mission, max_iterations)

        if mission.is_terminal:
            self._record_memory(mission)

        return mission

    def approve(self, mission_id: str, step_id: str) -> bool:
        """Approve a waiting step."""
        mission = self._missions.get(mission_id)
        if not mission:
            return False
        return self._runner.approve_step(mission, step_id)

    def deny(self, mission_id: str, step_id: str) -> bool:
        """Deny a waiting step (skips it)."""
        mission = self._missions.get(mission_id)
        if not mission:
            return False
        return self._runner.deny_step(mission, step_id)

    def pause(self, mission_id: str) -> bool:
        """Pause a running mission."""
        mission = self._missions.get(mission_id)
        if not mission:
            return False
        return self._runner.pause(mission)

    def cancel(self, mission_id: str) -> bool:
        """Cancel a mission."""
        mission = self._missions.get(mission_id)
        if not mission:
            return False
        return self._runner.cancel(mission)

    def retry_step(self, mission_id: str, step_id: str) -> bool:
        """Retry a failed step."""
        mission = self._missions.get(mission_id)
        if not mission:
            return False
        return self._runner.retry_step(mission, step_id)

    # ═══════════════════════════════════════════════════════════════
    # QUERIES
    # ═══════════════════════════════════════════════════════════════

    def get(self, mission_id: str) -> Mission | None:
        return self._missions.get(mission_id)

    def list_missions(
        self,
        status: str = "",
        priority: str = "",
        limit: int = 50,
    ) -> list[dict]:
        """List missions with optional filters."""
        missions = list(self._missions.values())
        if status:
            missions = [m for m in missions if m.status == status]
        if priority:
            missions = [m for m in missions if m.priority == priority]
        missions.sort(key=lambda m: m.created_at, reverse=True)
        return [m.to_summary() for m in missions[:limit]]

    def get_mission_detail(self, mission_id: str) -> dict | None:
        """Get full mission detail with steps, logs, results."""
        mission = self._missions.get(mission_id)
        if not mission:
            return None
        return mission.to_dict()

    def get_mission_logs(self, mission_id: str) -> list[dict]:
        """Get mission execution logs."""
        mission = self._missions.get(mission_id)
        if not mission:
            return []
        return mission.logs

    def get_audit_trail(self, mission_id: str) -> list[dict]:
        """Get audit trail for a mission."""
        return self._audit.get_mission_log(mission_id)

    # ── Templates ──

    def get_templates(self) -> list[dict]:
        """List available mission templates."""
        templates = list_templates()
        # Enrich with memory stats
        for tpl in templates:
            stats = self._memory.get_template_stats(tpl["id"])
            tpl["past_runs"] = stats.get("runs", 0)
            tpl["success_rate"] = stats.get("success_rate", 0)
        return templates

    def get_template_detail(self, template_id: str) -> dict | None:
        """Get full template with steps and stats."""
        tpl = get_template(template_id)
        if not tpl:
            return None
        stats = self._memory.get_template_stats(template_id)
        return {**tpl, "stats": stats}

    # ── Memory / Analytics ──

    def get_memory(self, limit: int = 20) -> list[dict]:
        """Get recent mission memory entries."""
        return self._memory.get_recent(limit)

    def get_agent_performance(self) -> dict:
        """Get aggregate agent performance across missions."""
        return self._memory.get_agent_stats()

    def get_stats(self) -> dict:
        """Get engine statistics."""
        missions = list(self._missions.values())
        return {
            "total_missions": len(missions),
            "active": sum(1 for m in missions if m.is_active),
            "completed": sum(1 for m in missions if m.status == MissionStatus.COMPLETED.value),
            "failed": sum(1 for m in missions if m.status == MissionStatus.FAILED.value),
            "waiting_approval": sum(1 for m in missions if m.status == MissionStatus.WAITING_APPROVAL.value),
            "templates": len(TEMPLATES),
            "memory_entries": self._memory.total_missions,
            "memory_success_rate": self._memory.success_rate,
            "audit_records": self._audit.total_records,
            "audit_chain_valid": self._audit.verify_chain(),
        }

    # ── Private ──

    def _record_memory(self, mission: Mission) -> None:
        """Record mission result to memory for future optimization."""
        # Compute agent performance
        agent_perf: dict[str, dict] = {}
        for step in mission.steps:
            if not step.agent:
                continue
            if step.agent not in agent_perf:
                agent_perf[step.agent] = {"steps": 0, "success": 0, "total_duration": 0}
            agent_perf[step.agent]["steps"] += 1
            if step.status == StepStatus.COMPLETED.value:
                agent_perf[step.agent]["success"] += 1
            if step.duration_ms > 0:
                agent_perf[step.agent]["total_duration"] += step.duration_ms
        # Compute avg duration
        for agent, perf in agent_perf.items():
            perf["avg_duration"] = perf["total_duration"] / max(perf["steps"], 1)

        entry = MissionMemoryEntry(
            mission_id=mission.mission_id,
            mission_title=mission.title,
            template_id=mission.template_id,
            status=mission.status,
            total_steps=len(mission.steps),
            completed_steps=len(mission.completed_steps),
            failed_steps=len(mission.failed_steps),
            duration_seconds=mission.duration_seconds,
            failures=[
                {"step": s.name, "error": s.error[:200], "retry_count": s.retry_count}
                for s in mission.failed_steps
            ],
            agent_performance=agent_perf,
        )
        self._memory.record(entry)
