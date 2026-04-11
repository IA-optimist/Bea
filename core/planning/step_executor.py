"""
core/planning/step_executor.py — Execute individual plan steps.

Dispatches to the correct subsystem (business_action, tool, skill)
and captures structured results. Each step receives the shared context
so it can read outputs from previous steps.
"""
from __future__ import annotations

import time
import structlog

from core.planning.execution_plan import PlanStep, StepType
from core.planning.step_context import StepContext
_silent_log = __import__("structlog").get_logger(__name__)

log = structlog.get_logger("planning.step_executor")


class StepResult:
    """Result of executing a single plan step."""

    def __init__(
        self,
        step_id: str,
        ok: bool,
        output: dict | None = None,
        artifacts: list[str] | None = None,
        error: str = "",
        duration_ms: float = 0,
        needs_approval: bool = False,
    ):
        self.step_id = step_id
        self.ok = ok
        self.output = output or {}
        self.artifacts = artifacts or []
        self.error = error
        self.duration_ms = duration_ms
        self.needs_approval = needs_approval

    def to_dict(self) -> dict:
        return {
            "step_id": self.step_id,
            "ok": self.ok,
            "output": self.output,
            "artifacts": self.artifacts,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "needs_approval": self.needs_approval,
        }


def execute_step(step: PlanStep, context: StepContext) -> StepResult:
    """
    Execute a single plan step within the shared context.

    Dispatches to the correct subsystem based on step.type.
    Previous step outputs are available via context.get_all_outputs().
    """
    t0 = time.time()

    try:
        if step.type == StepType.BUSINESS_ACTION:
            result = _execute_business_action(step, context)
        elif step.type == StepType.TOOL:
            result = _execute_tool(step, context)
        elif step.type == StepType.SKILL:
            result = _execute_skill(step, context)
        else:
            result = StepResult(step_id=step.step_id, ok=False,
                               error=f"Unknown step type: {step.type}")
    except Exception as e:
        result = StepResult(step_id=step.step_id, ok=False,
                           error=f"Step execution error: {str(e)[:200]}")

    result.duration_ms = round((time.time() - t0) * 1000)

    # Record step outcome in learning memory (fail-open)
    try:
        from core.planning.learning_memory import get_learning_memory
        output = result.output or {}
        get_learning_memory().record_step_outcome(
            step_id=result.step_id,
            skill_id=output.get("skill_id", step.target_id),
            model_used=output.get("model", ""),
            success=result.ok,
            quality_score=output.get("quality", {}).get("score", 0.0) if isinstance(output.get("quality"), dict) else 0.0,
            retry_count=output.get("retry_trace", {}).get("total_attempts", 1) - 1 if output.get("retry_trace") else 0,
            issues=output.get("retry_trace", {}).get("issues_per_attempt", [[]])[0] if output.get("retry_trace") else [],
        )
    except Exception:
        _silent_log.debug("suppressed_exception", src='step_executor.py')

    return result


def _execute_business_action(step: PlanStep, context: StepContext) -> StepResult:
    """Execute a business action step."""
    try:
        from core.business_actions import get_business_executor, ACTION_REGISTRY

        action = ACTION_REGISTRY.get(step.target_id)
        if not action:
            return StepResult(step_id=step.step_id, ok=False,
                             error=f"Unknown action: {step.target_id}")

        # Resolve inputs: step.inputs + context + goal extraction
        try:
            from core.planning.input_resolver import resolve_step_inputs
            merged_inputs = resolve_step_inputs(
                step_target_id=step.target_id,
                step_inputs=step.inputs,
                goal=context.goal,
                context_outputs=context.get_all_outputs(),
            )
        except Exception:
            merged_inputs = dict(context.get_all_outputs())
            merged_inputs.update(step.inputs)

        executor = get_business_executor()
        result = executor.execute(
            action_id=step.target_id,
            agent_output=merged_inputs,
            mission_id=context.plan_id,
            project_name=context.goal[:40] if context.goal else "",
        )

        if result.get("ok"):
            output = {
                "action_id": step.target_id,
                "project_dir": result.get("project_dir", ""),
                "files_created": result.get("files_created", []),
            }
            artifacts = [result.get("project_dir", "")]
            return StepResult(
                step_id=step.step_id, ok=True,
                output=output, artifacts=artifacts,
            )
        else:
            # Check if it's awaiting approval
            if result.get("awaiting_approval"):
                return StepResult(
                    step_id=step.step_id, ok=False,
                    needs_approval=True,
                    error="Action requires approval",
                    output={"awaiting_approval": True, "project_dir": result.get("project_dir", "")},
                )
            return StepResult(step_id=step.step_id, ok=False,
                             error=result.get("error", "Action failed"))

    except Exception as e:
        return StepResult(step_id=step.step_id, ok=False,
                         error=f"Business action error: {str(e)[:200]}")


def _execute_tool(step: PlanStep, context: StepContext) -> StepResult:
    """Execute a tool step."""
    try:
        from core.tools_operational.tool_executor import get_tool_executor
        from core.tools_operational.tool_registry import get_tool_registry

        tool = get_tool_registry().get(step.target_id)
        if not tool:
            return StepResult(step_id=step.step_id, ok=False,
                             error=f"Unknown tool: {step.target_id}")

        # Check if tool needs approval and we don't have it
        if tool.requires_approval:
            approval = context.approval_decisions.get(step.step_id, {})
            if not approval.get("approved"):
                return StepResult(
                    step_id=step.step_id, ok=False,
                    needs_approval=True,
                    error=f"Tool {step.target_id} requires approval",
                )

        # Merge inputs
        merged_inputs = dict(context.get_all_outputs())
        merged_inputs.update(step.inputs)

        # If tool is approval-gated and we have approval, use override
        executor = get_tool_executor()
        approval_override = bool(context.approval_decisions.get(step.step_id, {}).get("approved"))
        result = executor.execute(
            tool_id=step.target_id,
            inputs=merged_inputs,
            mission_id=context.plan_id,
            approval_override=approval_override,
        )

        output = result.to_dict()
        artifacts = []

        return StepResult(
            step_id=step.step_id,
            ok=result.ok,
            output=output,
            artifacts=artifacts,
            error=result.error,
        )

    except Exception as e:
        return StepResult(step_id=step.step_id, ok=False,
                         error=f"Tool error: {str(e)[:200]}")


def _execute_skill(step: PlanStep, context: StepContext) -> StepResult:
    """
    Execute a skill step.

    Skills don't call LLMs directly — they prepare prompt contexts.
    The step executor captures the preparation result as the output.
    A real LLM call would be injected here in future.
    """
    try:
        from core.skills.domain_executor import get_skill_executor

        executor = get_skill_executor()

        # Resolve inputs: step.inputs + context + goal extraction
        try:
            from core.planning.input_resolver import resolve_step_inputs
            merged_inputs = resolve_step_inputs(
                step_target_id=step.target_id,
                step_inputs=step.inputs,
                goal=context.goal,
                context_outputs=context.get_all_outputs(),
            )
        except Exception:
            # Fallback to original merge behavior
            merged_inputs = dict(context.get_all_outputs())
            merged_inputs.update(step.inputs)

        # Prepare skill context
        prep = executor.prepare(step.target_id, merged_inputs)
        if "error" in prep:
            return StepResult(step_id=step.step_id, ok=False,
                             error=prep["error"])

        # Attempt LLM invocation (fail-open: falls back to prep-only)
        # Propagate budget_mode from context metadata
        budget_mode = context.metadata.get("budget_mode", "normal") if context.metadata else "normal"

        # Attempt LLM invocation with adaptive retry on incomplete output
        prompt_context = prep.get("prompt_context", "")
        output_schema = prep.get("output_schema", [])
        retry_trace = None

        llm_result = None
        try:
            from core.planning.skill_llm import invoke_skill_llm
            from core.planning.step_retry import (
                detect_incomplete_output, should_retry, get_retry_strategy,
                apply_strategy_to_prompt, RetryTrace,
            )

            retry_trace = RetryTrace()
            current_prompt = prompt_context
            current_budget = budget_mode

            # First attempt
            llm_result = invoke_skill_llm(
                prompt_context=current_prompt,
                output_schema=output_schema,
                skill_id=step.target_id,
                budget_mode=current_budget,
            )

            # Retry loop: check output quality and retry if needed
            if llm_result and llm_result.get("invoked") and not llm_result.get("error"):
                content = llm_result.get("content", {})
                issues = detect_incomplete_output(content, output_schema)
                retry_trace.issues_per_attempt.append(issues)

                attempt = 0
                while should_retry(issues, attempt):
                    strategy = get_retry_strategy(attempt)
                    if strategy is None:
                        break

                    retry_trace.strategies_used.append(strategy.to_dict())
                    current_prompt = apply_strategy_to_prompt(prompt_context, strategy)
                    retry_budget = strategy.budget_mode or current_budget

                    retry_result = invoke_skill_llm(
                        prompt_context=current_prompt,
                        output_schema=output_schema,
                        skill_id=step.target_id,
                        budget_mode=retry_budget,
                    )

                    if retry_result and retry_result.get("invoked") and not retry_result.get("error"):
                        retry_content = retry_result.get("content", {})
                        retry_issues = detect_incomplete_output(retry_content, output_schema)
                        retry_trace.issues_per_attempt.append(retry_issues)

                        # Use retry result if it's better (fewer issues)
                        if len(retry_issues) < len(issues):
                            llm_result = retry_result
                            content = retry_content
                            issues = retry_issues
                    else:
                        retry_trace.issues_per_attempt.append(["llm_call_failed"])

                    attempt += 1
                    retry_trace.total_attempts += 1

                retry_trace.final_attempt = retry_trace.total_attempts - 1

        except Exception:
            pass  # fail-open: proceed with whatever we have

        if llm_result and llm_result.get("invoked") and not llm_result.get("error"):
            # LLM produced real output
            output = {
                "skill_id": step.target_id,
                "invoked": True,
                "content": llm_result.get("content", {}),
                "raw_length": llm_result.get("raw_length", 0),
                "duration_ms": llm_result.get("duration_ms", 0),
                "model": llm_result.get("model", ""),
                "budget_mode": llm_result.get("budget_mode", budget_mode),
                "model_role": llm_result.get("model_role", ""),
                "quality": llm_result.get("quality", {}),
                "output_schema": output_schema,
            }
            if retry_trace and retry_trace.total_attempts > 1:
                output["retry_trace"] = retry_trace.to_dict()
        else:
            # Preparation-only (no LLM available or call failed)
            output = {
                "skill_id": step.target_id,
                "prepared": True,
                "invoked": False,
                "prompt_context_length": len(prompt_context),
                "output_schema": output_schema,
                "quality_checks": prep.get("quality_checks", []),
            }
            # If LLM was attempted but failed, include the error as warning
            if llm_result and llm_result.get("error"):
                output["llm_error"] = llm_result["error"][:200]

        return StepResult(
            step_id=step.step_id, ok=True,
            output=output,
        )

    except Exception as e:
        return StepResult(step_id=step.step_id, ok=False,
                         error=f"Skill error: {str(e)[:200]}")
