"""
core/planning/plan_runner.py — Automated plan execution engine.

Executes validated, approved plans step by step with:
  - Execution context propagation between steps
  - Pause/resume at step boundaries
  - Approval checkpoints before tool steps
  - Failure isolation (step failure ≠ system crash)
  - Automatic execution memory persistence
  - Cognitive event emission at each stage

This is the core loop closer: Goal → Plan → Execute → Artifacts → Memory.
"""
from __future__ import annotations

import time
import structlog

from core.planning.execution_plan import ExecutionPlan, PlanStatus
from core.planning.step_context import StepContext
from core.planning.step_executor import execute_step
from core.planning.run_state import PlanRun, RunStatus, get_run_store
from core.planning.plan_serializer import get_plan_store

log = structlog.get_logger("planning.runner")


class PlanRunner:
    """
    Execute plans step by step with full control and traceability.

    Usage:
        runner = PlanRunner()
        run = runner.start(plan_id)          # start execution
        run = runner.resume(run_id)          # resume paused run
        runner.pause(run_id)                 # pause at next step boundary
        runner.cancel(run_id)                # cancel execution
        run = runner.get_run(run_id)         # check status
    """

    def __init__(self):
        self._pause_requests: set[str] = set()

    def start(self, plan_id: str) -> PlanRun:
        """
        Start executing a plan.

        The plan must be in APPROVED or VALIDATED status.
        Returns a PlanRun with the execution result.
        """
        plan = get_plan_store().get(plan_id)
        if not plan:
            return self._error_run(plan_id, "Plan not found")

        # Verify plan status
        if plan.status not in {PlanStatus.APPROVED, PlanStatus.VALIDATED}:
            return self._error_run(plan_id,
                f"Plan status '{plan.status.value}' not executable. Must be approved or validated.")

        # Check approval for plans that require it
        if plan.requires_approval and plan.status != PlanStatus.APPROVED:
            return self._error_run(plan_id, "Plan requires approval before execution")

        # Create run — propagate plan metadata (budget_mode, etc.)
        context = StepContext(
            plan_id=plan.plan_id,
            goal=plan.goal,
            metadata=dict(getattr(plan, "metadata", {}) or {}),
        )
        run = PlanRun(
            run_id=context.run_id,
            plan_id=plan.plan_id,
            status=RunStatus.RUNNING,
            context=context,
            steps_total=len(plan.steps),
        )

        # Update plan status
        plan.status = PlanStatus.EXECUTING
        plan.updated_at = time.time()
        get_plan_store().save(plan)

        # Emit start event
        self._emit("run_started", run, plan=plan)

        # Execute steps
        run = self._execute_steps(plan, run)

        return run

    def resume(self, run_id: str) -> PlanRun:
        """Resume a paused or approval-waiting run."""
        store = get_run_store()
        run = store.get(run_id)
        if not run:
            return self._error_run("", f"Run not found: {run_id}")

        if run.status not in {RunStatus.PAUSED, RunStatus.AWAITING_APPROVAL}:
            run.error = f"Cannot resume run in status: {run.status.value}"
            return run

        plan = get_plan_store().get(run.plan_id)
        if not plan:
            run.status = RunStatus.FAILED
            run.error = "Plan no longer exists"
            store.save(run)
            return run

        # Clear pause request
        self._pause_requests.discard(run_id)

        # Resume execution
        run.status = RunStatus.RUNNING
        plan.status = PlanStatus.EXECUTING
        get_plan_store().save(plan)

        self._emit("run_resumed", run)
        run = self._execute_steps(plan, run)
        return run

    def pause(self, run_id: str) -> bool:
        """Request pause at next step boundary."""
        self._pause_requests.add(run_id)
        return True

    def cancel(self, run_id: str) -> PlanRun | None:
        """Cancel a running or paused plan."""
        store = get_run_store()
        run = store.get(run_id)
        if not run:
            return None

        if run.status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}:
            return run  # Already terminal

        run.status = RunStatus.CANCELLED
        run.completed_at = time.time()
        store.save(run)

        # Update plan status
        plan = get_plan_store().get(run.plan_id)
        if plan:
            plan.status = PlanStatus.CANCELLED
            plan.updated_at = time.time()
            get_plan_store().save(plan)

        self._emit("run_cancelled", run)
        self._record_memory(run)
        return run

    def approve_step(self, run_id: str, step_id: str, reason: str = "") -> bool:
        """Approve a specific step in a paused run."""
        store = get_run_store()
        run = store.get(run_id)
        if not run:
            return False
        run.context.record_approval(step_id, approved=True, reason=reason)
        store.save(run)
        return True

    def get_run(self, run_id: str) -> PlanRun | None:
        return get_run_store().get(run_id)

    # ── Core execution loop ───────────────────────────────────

    def _execute_steps(self, plan: ExecutionPlan, run: PlanRun) -> PlanRun:
        """Execute remaining steps in the plan."""
        store = get_run_store()
        start_index = run.context.current_step_index

        for i in range(start_index, len(plan.steps)):
            step = plan.steps[i]
            run.context.current_step_index = i
            run.current_step_id = step.step_id

            # Check for pause request
            if run.run_id in self._pause_requests:
                self._pause_requests.discard(run.run_id)
                run.status = RunStatus.PAUSED
                plan.status = PlanStatus.PAUSED
                get_plan_store().save(plan)
                store.save(run)
                self._emit("run_paused", run, step=step)
                return run

            # Mark step running
            step.status = "running"
            step.started_at = time.time()
            store.save(run)

            self._emit("step_started", run, step=step)

            # Execute step
            result = execute_step(step, run.context)

            # Handle approval-needed
            if result.needs_approval:
                step.status = "pending"
                run.status = RunStatus.AWAITING_APPROVAL
                run.current_step_id = step.step_id
                plan.status = PlanStatus.PAUSED
                get_plan_store().save(plan)
                store.save(run)
                self._emit("step_needs_approval", run, step=step)
                return run

            # Record result
            step.completed_at = time.time()
            step.result = result.to_dict()

            if result.ok:
                step.status = "completed"
                run.steps_completed += 1
                run.context.set_step_output(step.step_id, result.output)
                for artifact in result.artifacts:
                    run.context.add_artifact(artifact)
                self._emit("step_completed", run, step=step, result=result)
            else:
                step.status = "failed"
                run.steps_failed += 1
                self._emit("step_failed", run, step=step, result=result)

                # Fail the run on step failure
                run.status = RunStatus.FAILED
                run.error = f"Step '{step.name}' failed: {result.error[:200]}"
                run.completed_at = time.time()
                plan.status = PlanStatus.FAILED
                plan.updated_at = time.time()
                get_plan_store().save(plan)
                store.save(run)
                self._record_memory(run)
                return run

            # Advance context
            run.context.current_step_index = i + 1
            store.save(run)

        # All steps completed
        run.status = RunStatus.COMPLETED
        run.completed_at = time.time()
        plan.status = PlanStatus.COMPLETED
        plan.updated_at = time.time()
        get_plan_store().save(plan)
        store.save(run)

        self._emit("run_completed", run)
        self._record_memory(run)

        return run

    # ── Execution memory recording ────────────────────────────

    def _record_memory(self, run: PlanRun) -> None:
        """Record completed/failed run to execution memory."""
        try:
            from core.planning.execution_memory import get_execution_memory, ExecutionRecord
            plan = get_plan_store().get(run.plan_id)
            template_id = plan.template_id if plan else ""

            tools_used = []
            actions_used = []
            skills_used = []
            for output in run.context.step_outputs.values():
                if output.get("action_id"):
                    actions_used.append(output["action_id"])
                if output.get("tool_id"):
                    tools_used.append(output["tool_id"])
                if output.get("skill_id"):
                    skills_used.append(output["skill_id"])

            get_execution_memory().record(ExecutionRecord(
                record_id=run.run_id,
                plan_id=run.plan_id,
                goal=run.context.goal,
                template_id=template_id,
                tools_used=tools_used,
                actions_used=actions_used,
                skills_used=skills_used,
                success=run.status == RunStatus.COMPLETED,
                duration_ms=run.duration_ms,
                step_count=run.steps_total,
                steps_completed=run.steps_completed,
                artifacts=run.context.artifacts,
                error=run.error,
            ))
        except Exception as e:
            log.debug("memory_record_failed", err=str(e)[:80])

    # ── Cognitive event emission ──────────────────────────────

    def _emit(self, event: str, run: PlanRun, **extra) -> None:
        """Emit cognitive event + kernel event (fail-open)."""
        step = extra.get("step")
        result = extra.get("result")

        # ── Cognitive journal emission (existing) ─────────────────
        try:
            from core.cognitive_events.emitter import emit
            from core.cognitive_events.types import EventType, EventSeverity

            sev = EventSeverity.INFO
            if "failed" in event or "cancelled" in event:
                sev = EventSeverity.WARNING

            payload = {
                "event": event,
                "run_id": run.run_id,
                "plan_id": run.plan_id,
                "status": run.status.value,
                "progress": run.progress,
            }
            if step:
                payload["step_id"] = step.step_id
                payload["step_name"] = step.name
                payload["step_type"] = step.type.value if hasattr(step.type, 'value') else str(step.type)
            if result:
                payload["step_ok"] = result.ok
                if result.error:
                    payload["error"] = result.error[:100]

            emit(
                EventType.SYSTEM_EVENT,
                summary=f"Plan runner: {event}",
                source="plan_runner",
                mission_id=run.plan_id,
                severity=sev,
                payload=payload,
                tags=["plan_runner", event],
            )
        except Exception as _exc:
            log.warning("swallowed_exception", action="plan_runner_1", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

        # ── Kernel event emission (dual, fail-open) ──────────────
        try:
            from kernel.convergence.event_bridge import emit_kernel_event

            _RUNNER_TO_KERNEL = {
                "step_started": "step.started",
                "step_completed": "step.completed",
                "step_failed": "step.failed",
                "step_needs_approval": "approval.requested",
                "run_started": "mission.executing",
                "run_completed": "mission.completed",
                "run_failed": "mission.failed",
                "run_paused": "step.started",
                "run_resumed": "step.started",
                "run_cancelled": "mission.cancelled",
            }
            kernel_type = _RUNNER_TO_KERNEL.get(event)
            if kernel_type:
                kwargs = {
                    "plan_id": run.plan_id,
                    "mission_id": run.plan_id,
                    "source": "plan_runner",
                }
                if step:
                    kwargs["step_id"] = step.step_id
                    kwargs["step_name"] = step.name
                    # Pass step_type and target_id for performance tracking
                    kwargs["step_type"] = step.type.value if hasattr(step.type, 'value') else str(step.type)
                    kwargs["tool_id"] = step.target_id  # skill/tool/action ID
                if result:
                    if not result.ok and result.error:
                        kwargs["error"] = result.error[:100]
                    kwargs["success"] = result.ok
                if kernel_type == "approval.requested" and step:
                    kwargs["target_id"] = step.step_id
                    kwargs["action"] = f"Step '{step.name}' requires approval"
                emit_kernel_event(kernel_type, **kwargs)
        except Exception as _exc:
            log.warning("swallowed_exception", action="plan_runner_2", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    # ── Error helper ──────────────────────────────────────────

    def _error_run(self, plan_id: str, error: str) -> PlanRun:
        """Create a failed run for error cases."""
        run = PlanRun(
            plan_id=plan_id,
            status=RunStatus.FAILED,
            error=error,
            completed_at=time.time(),
        )
        get_run_store().save(run)
        return run


# ── Singleton ─────────────────────────────────────────────────

_runner: PlanRunner | None = None


def get_plan_runner() -> PlanRunner:
    global _runner
    if _runner is None:
        _runner = PlanRunner()
    return _runner
