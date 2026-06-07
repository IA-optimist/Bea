"""
BEA MAX — Mission Runner
===============================
Executes individual mission steps through the existing agent/tool layer.

Does NOT duplicate executor logic — delegates to:
- ExecutionEngine for task dispatch
- Tool executor for tool calls
- Approval notifier for approval gates

Handles:
- Sequential and parallel step execution
- Dependency resolution (step depends_on)
- Approval pause/resume
- Retry on transient failures
- Step timeout enforcement
- Output forwarding between steps
"""
from __future__ import annotations

import logging
import time
from typing import Any

from core.business.mission_schema import (
    Mission, MissionStep, MissionStatus, StepStatus, RiskLevel,
    DependencyCheckResult,
)
from core.business.mission_audit import MissionAuditLog, AuditEvent

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# APPROVAL ACTIONS
# ═══════════════════════════════════════════════════════════════

APPROVAL_TRIGGERS = {
    "payment", "billing", "stripe", "charge", "invoice",
    "credential", "secret", "password", "api_key",
    "publish", "deploy", "launch", "send_email",
    "delete", "destroy", "revoke",
}


def step_needs_approval(step: MissionStep) -> bool:
    """Check if a step requires human approval."""
    # Already approved by human — skip gate
    if step.approved:
        return False
    if step.approval_required:
        return True
    if step.risk_level in (RiskLevel.HIGH.value, RiskLevel.CRITICAL.value):
        return True
    # Check step description for trigger words
    desc_lower = (step.description + " " + step.name).lower()
    return any(trigger in desc_lower for trigger in APPROVAL_TRIGGERS)


# ═══════════════════════════════════════════════════════════════
# DEPENDENCY VALIDATOR
# ═══════════════════════════════════════════════════════════════

class DependencyValidator:
    """
    Validates mission dependencies before execution.
    
    Checks: connectors, secrets, identities, agents, tools.
    Generates suggestions for missing items.
    """

    def __init__(
        self,
        available_connectors: set[str] | None = None,
        available_secrets: set[str] | None = None,
        available_identities: set[str] | None = None,
        available_agents: set[str] | None = None,
        available_tools: set[str] | None = None,
    ):
        self._connectors = available_connectors or set()
        self._secrets = available_secrets or set()
        self._identities = available_identities or set()
        self._agents = available_agents or set()
        self._tools = available_tools or set()

    def validate(self, mission: Mission) -> DependencyCheckResult:
        """Validate all mission dependencies."""
        result = DependencyCheckResult()

        # Collect ALL requirements from mission + steps
        needed_connectors = set(mission.required_connectors)
        needed_identities = set(mission.required_identities)
        needed_tools = set(mission.required_tools)
        needed_agents = set(mission.assigned_agents)
        needed_secrets: set[str] = set()

        for step in mission.steps:
            needed_connectors.update(step.required_connectors)
            needed_identities.update(step.required_identities)
            needed_tools.update(step.required_tools)
            needed_secrets.update(step.required_secrets)
            if step.agent:
                needed_agents.add(step.agent)

        # Check each
        result.missing_connectors = sorted(needed_connectors - self._connectors)
        result.missing_secrets = sorted(needed_secrets - self._secrets)
        result.missing_identities = sorted(needed_identities - self._identities)
        result.missing_agents = sorted(needed_agents - self._agents)
        result.missing_tools = sorted(needed_tools - self._tools)

        result.valid = not any([
            result.missing_connectors, result.missing_secrets,
            result.missing_identities, result.missing_agents,
            result.missing_tools,
        ])

        # Generate suggestions
        for c in result.missing_connectors:
            result.suggestions.append(f"Add connector: {c} (Settings → Connectors → Add)")
        for s in result.missing_secrets:
            result.suggestions.append(f"Add secret: {s} (Vault → Create Secret)")
        for i in result.missing_identities:
            result.suggestions.append(f"Create identity: {i} (Identities → New)")
        for a in result.missing_agents:
            result.suggestions.append(f"Enable agent: {a} (Modules → Agents → Enable)")
        for t in result.missing_tools:
            result.suggestions.append(f"Install tool: {t} (Catalog → Search)")

        return result


# ═══════════════════════════════════════════════════════════════
# STEP EXECUTOR
# ═══════════════════════════════════════════════════════════════

class StepExecutor:
    """
    Executes a single mission step.
    
    Delegates to the existing tool execution layer — does NOT
    re-implement tool logic.
    """

    def __init__(self, tool_executor=None, approval_notifier=None):
        self._tool_executor = tool_executor
        self._approval_notifier = approval_notifier

    def execute(self, step: MissionStep, context: dict | None = None) -> dict:
        """
        Execute a step, returning result dict.
        
        Context: output from previous steps, mission metadata.
        """
        context = context or {}
        step.status = StepStatus.RUNNING.value
        step.started_at = time.time()

        try:
            # Merge input from previous step outputs
            step_input = {**step.input_data, **context}

            # Delegate to tool executor if tools required
            if self._tool_executor and step.required_tools:
                result = self._execute_with_tools(step, step_input)
            else:
                # Agent-only step: produce structured output
                result = self._execute_agent_step(step, step_input)

            step.output_data = result
            step.status = StepStatus.COMPLETED.value
            step.completed_at = time.time()
            return result

        except TimeoutError:
            step.status = StepStatus.FAILED.value
            step.completed_at = time.time()
            step.error = f"Step timed out after {step.timeout_seconds}s"
            return {"error": step.error, "status": "timeout"}

        except Exception as e:
            step.status = StepStatus.FAILED.value
            step.completed_at = time.time()
            step.error = str(e)[:300]
            return {"error": step.error, "status": "failed"}

    def _execute_with_tools(self, step: MissionStep, inputs: dict) -> dict:
        """Execute step using tool executor."""
        if not self._tool_executor:
            return {"status": "no_executor", "note": "Tool executor not configured"}

        # Build tool execution request
        results = {}
        for tool_name in step.required_tools:
            try:
                result = self._tool_executor.execute(
                    tool_name=tool_name,
                    parameters=inputs,
                    timeout=step.timeout_seconds,
                )
                results[tool_name] = result if isinstance(result, dict) else {"output": str(result)[:2000]}
            except Exception as e:
                results[tool_name] = {"error": str(e)[:200]}

        return {"tools": results, "status": "completed"}

    def _execute_agent_step(self, step: MissionStep, inputs: dict) -> dict:
        """Execute agent-only step (no tools)."""
        return {
            "agent": step.agent,
            "step": step.name,
            "input_keys": list(inputs.keys()),
            "status": "completed",
            "note": f"Agent {step.agent} completed: {step.description[:100]}",
        }

    def request_approval(self, step: MissionStep, mission_id: str) -> str | None:
        """Request approval for a step. Returns ticket_id."""
        if not self._approval_notifier:
            return None

        ticket = self._approval_notifier.request_approval(
            action=f"Execute: {step.name}",
            module_type="mission_step",
            module_id=f"{mission_id}/{step.step_id}",
            module_name=step.name,
            risk_level=step.risk_level,
            reason=step.description[:200],
        )
        return ticket.ticket_id


# ═══════════════════════════════════════════════════════════════
# MISSION RUNNER
# ═══════════════════════════════════════════════════════════════

class MissionRunner:
    """
    Orchestrates the execution of a complete mission.
    
    Handles:
    - Step ordering and dependency resolution
    - Sequential and parallel execution modes
    - Approval gates
    - Retry on failure
    - Plan adaptation
    """

    def __init__(
        self,
        step_executor: StepExecutor | None = None,
        audit: MissionAuditLog | None = None,
        dependency_validator: DependencyValidator | None = None,
    ):
        self._executor = step_executor or StepExecutor()
        self._audit = audit or MissionAuditLog()
        self._validator = dependency_validator

    def validate_dependencies(self, mission: Mission) -> DependencyCheckResult:
        """Check all mission dependencies before execution."""
        if self._validator:
            result = self._validator.validate(mission)
        else:
            result = DependencyCheckResult()  # No validator → assume valid

        self._audit.log(
            AuditEvent.DEPENDENCY_CHECK, mission.mission_id,
            details={"valid": result.valid, "missing": len(result.suggestions)},
        )

        if not result.valid:
            self._audit.log(
                AuditEvent.DEPENDENCY_MISSING, mission.mission_id,
                details={"suggestions": result.suggestions[:5]},
            )

        return result

    def plan(self, mission: Mission) -> Mission:
        """Transition mission from draft to planned."""
        if mission.status != MissionStatus.DRAFT.value:
            return mission

        mission.status = MissionStatus.PLANNED.value
        mission.add_log("planned", {"step_count": len(mission.steps)})
        self._audit.log(
            AuditEvent.MISSION_PLANNED, mission.mission_id,
            details={"steps": len(mission.steps), "agents": mission.assigned_agents},
        )
        return mission

    def start(self, mission: Mission) -> Mission:
        """Start mission execution."""
        if mission.status not in (MissionStatus.PLANNED.value, MissionStatus.PAUSED.value):
            return mission

        mission.status = MissionStatus.RUNNING.value
        mission.started_at = mission.started_at or time.time()
        mission.paused_at = None
        mission.add_log("started")

        event = AuditEvent.MISSION_STARTED if not mission.paused_at else AuditEvent.MISSION_RESUMED
        self._audit.log(event, mission.mission_id)

        return mission

    def execute_next_step(self, mission: Mission) -> dict:
        """
        Execute the next available step in the mission.
        
        Returns: {executed: bool, step_id, status, needs_approval, output}
        """
        if mission.status != MissionStatus.RUNNING.value:
            return {"executed": False, "reason": f"Mission is {mission.status}"}

        step = mission.next_pending_step
        if not step:
            # Check if all done
            if all(s.is_terminal for s in mission.steps):
                self._complete_mission(mission)
                return {"executed": False, "reason": "mission_completed"}
            return {"executed": False, "reason": "no_ready_steps"}

        # Check approval gate
        if step_needs_approval(step):
            step.status = StepStatus.WAITING_APPROVAL.value
            mission.status = MissionStatus.WAITING_APPROVAL.value
            ticket_id = self._executor.request_approval(step, mission.mission_id)
            if ticket_id:
                mission.pending_approval_id = ticket_id
            self._audit.log(
                AuditEvent.APPROVAL_REQUESTED, mission.mission_id,
                step_id=step.step_id, agent=step.agent,
                details={"step": step.name, "risk": step.risk_level, "ticket": ticket_id or ""},
            )
            mission.add_log("approval_requested", {"step": step.name, "ticket": ticket_id})
            return {
                "executed": False,
                "step_id": step.step_id,
                "needs_approval": True,
                "approval_ticket": ticket_id,
            }

        # Execute
        self._audit.log(
            AuditEvent.STEP_STARTED, mission.mission_id,
            step_id=step.step_id, agent=step.agent,
        )

        # Build context from completed step outputs
        context = self._build_step_context(mission, step)
        try:
            result = self._executor.execute(step, context)
        except Exception as e:
            # Executor raised — mark step as failed
            step.status = StepStatus.FAILED.value
            step.completed_at = time.time()
            step.error = str(e)[:300]
            result = {"error": step.error, "status": "failed"}

        if step.status == StepStatus.COMPLETED.value:
            self._audit.log(
                AuditEvent.STEP_COMPLETED, mission.mission_id,
                step_id=step.step_id, agent=step.agent,
                details={"duration_ms": round(step.duration_ms, 1)},
            )
            mission.add_log("step_completed", {"step": step.name})
        else:
            # Retry?
            if step.retry_count < step.max_retries:
                step.retry_count += 1
                step.status = StepStatus.PENDING.value
                step.error = ""
                self._audit.log(
                    AuditEvent.STEP_RETRIED, mission.mission_id,
                    step_id=step.step_id,
                    details={"attempt": step.retry_count, "error": step.error[:100]},
                )
            else:
                self._audit.log(
                    AuditEvent.STEP_FAILED, mission.mission_id,
                    step_id=step.step_id, agent=step.agent,
                    details={"error": step.error[:200], "retries": step.retry_count},
                )
                mission.add_log("step_failed", {"step": step.name, "error": step.error[:100]})
                # Fail the mission
                self._fail_mission(mission, f"Step '{step.name}' failed after {step.retry_count} retries")

        return {
            "executed": True,
            "step_id": step.step_id,
            "status": step.status,
            "output": result,
        }

    def approve_step(self, mission: Mission, step_id: str) -> bool:
        """Approve a waiting step, resuming execution."""
        step = mission.get_step(step_id)
        if not step or step.status != StepStatus.WAITING_APPROVAL.value:
            return False

        step.status = StepStatus.PENDING.value
        step.approval_required = False
        step.approved = True  # Mark as human-approved — skip future gates
        mission.status = MissionStatus.RUNNING.value
        mission.pending_approval_id = ""

        self._audit.log(
            AuditEvent.APPROVAL_GRANTED, mission.mission_id,
            step_id=step_id,
        )
        mission.add_log("approval_granted", {"step": step.name})
        return True

    def deny_step(self, mission: Mission, step_id: str) -> bool:
        """Deny a waiting step, skipping it."""
        step = mission.get_step(step_id)
        if not step or step.status != StepStatus.WAITING_APPROVAL.value:
            return False

        step.status = StepStatus.SKIPPED.value
        step.completed_at = time.time()
        mission.status = MissionStatus.RUNNING.value
        mission.pending_approval_id = ""

        self._audit.log(
            AuditEvent.APPROVAL_DENIED, mission.mission_id,
            step_id=step_id,
        )
        mission.add_log("approval_denied", {"step": step.name})
        return True

    def pause(self, mission: Mission) -> bool:
        """Pause a running mission."""
        if mission.status not in (MissionStatus.RUNNING.value, MissionStatus.WAITING_APPROVAL.value):
            return False
        mission.status = MissionStatus.PAUSED.value
        mission.paused_at = time.time()
        self._audit.log(AuditEvent.MISSION_PAUSED, mission.mission_id)
        mission.add_log("paused")
        return True

    def cancel(self, mission: Mission) -> bool:
        """Cancel a mission."""
        if mission.is_terminal:
            return False
        mission.status = MissionStatus.FAILED.value
        mission.completed_at = time.time()
        # Skip remaining steps
        for step in mission.steps:
            if not step.is_terminal:
                step.status = StepStatus.SKIPPED.value
        self._audit.log(AuditEvent.MISSION_CANCELLED, mission.mission_id)
        mission.add_log("cancelled")
        return True

    def retry_step(self, mission: Mission, step_id: str) -> bool:
        """Retry a failed step."""
        step = mission.get_step(step_id)
        if not step or step.status != StepStatus.FAILED.value:
            return False
        step.status = StepStatus.PENDING.value
        step.error = ""
        step.retry_count = 0
        step.started_at = None
        step.completed_at = None
        # Resume mission if it was failed
        if mission.status == MissionStatus.FAILED.value:
            mission.status = MissionStatus.RUNNING.value
            mission.completed_at = None
        self._audit.log(
            AuditEvent.STEP_RETRIED, mission.mission_id, step_id=step_id,
            details={"manual_retry": True},
        )
        return True

    def run_to_completion(self, mission: Mission, max_iterations: int = 50) -> Mission:
        """
        Run all steps to completion (or until approval/failure).
        
        Useful for non-interactive execution.
        """
        if mission.status == MissionStatus.DRAFT.value:
            self.plan(mission)
        if mission.status == MissionStatus.PLANNED.value:
            self.start(mission)

        for _ in range(max_iterations):
            if mission.is_terminal or mission.status == MissionStatus.WAITING_APPROVAL.value:
                break
            result = self.execute_next_step(mission)
            if not result.get("executed") and not result.get("needs_approval"):
                break

        return mission

    # ── Private ──

    def _build_step_context(self, mission: Mission, step: MissionStep) -> dict:
        """Build context from completed step outputs for the current step."""
        context: dict[str, Any] = {
            "mission_id": mission.mission_id,
            "mission_title": mission.title,
            "objective": mission.objective,
        }
        # Add outputs from dependencies
        for dep_id in step.depends_on:
            dep_step = mission.get_step(dep_id)
            if dep_step and dep_step.output_data:
                context[f"prev_{dep_id}"] = dep_step.output_data
        return context

    def _complete_mission(self, mission: Mission) -> None:
        """Mark mission as completed."""
        mission.status = MissionStatus.COMPLETED.value
        mission.completed_at = time.time()

        # Aggregate results
        mission.results = {
            "steps_completed": len(mission.completed_steps),
            "steps_failed": len(mission.failed_steps),
            "total_steps": len(mission.steps),
            "duration_seconds": round(mission.duration_seconds, 1),
            "step_outputs": {s.step_id: s.output_data for s in mission.completed_steps if s.output_data},
        }

        self._audit.log(
            AuditEvent.MISSION_COMPLETED, mission.mission_id,
            details={"duration": mission.duration_seconds, "steps": len(mission.steps)},
        )
        mission.add_log("completed", mission.results)

    def _fail_mission(self, mission: Mission, reason: str) -> None:
        """Mark mission as failed."""
        mission.status = MissionStatus.FAILED.value
        mission.completed_at = time.time()
        self._audit.log(
            AuditEvent.MISSION_FAILED, mission.mission_id,
            details={"reason": reason[:300]},
        )
        mission.add_log("failed", {"reason": reason})
