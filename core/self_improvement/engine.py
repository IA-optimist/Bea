"""
core/self_improvement/engine.py — SelfImprovementEngine V3 facade.

Orchestrates the full self-improvement cycle:
  detect weaknesses → generate candidates → run PromotionPipeline → record results

V3 changes vs V1:
  - Candidates with target_file/current_content → PromotionPipeline (real code patches)
  - Workspace candidates (PROMPT_TWEAK etc.) → SafeExecutor (unchanged)
  - All results recorded in ImprovementLoop memory
  - Observability events emitted for every cycle
"""
from __future__ import annotations

import structlog

logger = structlog.get_logger("jarvis.self_improvement.engine")
log = logger  # M3 emitter alias

from core.self_improvement.failure_collector import FailureCollector
from core.self_improvement.improvement_planner import ImprovementPlanner
from core.self_improvement.candidate_generator import CandidateGenerator


class SelfImprovementEngine:
    """
    V3 Self-Improvement Engine.

    Cycle:
      1. Collect failures from FailureCollector
      2. Plan improvements via ImprovementPlanner
      3. Generate candidates via CandidateGenerator
      4. For each candidate:
         - Code candidates → PromotionPipeline.execute()
         - Workspace candidates → SafeExecutor.execute()
      5. Return summary with decisions per candidate
    """

    def __init__(self, settings=None):
        self.settings = settings
        self.collector = FailureCollector()
        self.planner = ImprovementPlanner()
        self.generator = CandidateGenerator()

    async def run_cycle(self) -> dict:
        """
        Run one full self-improvement cycle.

        Returns summary dict with:
          - failures: int
          - proposals: int
          - candidates: int
          - results: list[dict] with per-candidate outcome
        """
        # Step 1: Collect failures
        failures = self.collector.collect()
        logger.info("si_engine.cycle_start", failures=len(failures))

        # Step 2: Plan improvements
        proposals = self.planner.plan(failures)
        logger.info("si_engine.proposals", count=len(proposals))

        # Step 3: Generate candidates
        weaknesses = getattr(proposals, "__iter__", lambda: [])()
        candidates = self.generator.generate(list(weaknesses) if hasattr(proposals, "__iter__") else [])
        logger.info("si_engine.candidates", count=len(candidates))

        # Step 4: Execute candidates
        results = []
        for candidate in candidates:
            result = self._execute_candidate(candidate)
            results.append(result)

        # Step 5: Emit cycle summary event
        self._emit_cycle_event(failures, proposals, candidates, results)

        return {
            "failures": len(failures),
            "proposals": len(proposals) if hasattr(proposals, "__len__") else 0,
            "candidates": len(candidates),
            "results": results,
        }

    def _execute_candidate(self, candidate) -> dict:
        """
        Execute a single candidate through the appropriate pipeline.

        Code candidates (have target_file) → PromotionPipeline
        Workspace candidates → SafeExecutor
        """
        candidate_type = getattr(candidate, "type", "UNKNOWN")
        domain = getattr(candidate, "domain", "general")
        has_target_file = bool(getattr(candidate, "target_file", ""))

        # Route to PromotionPipeline for code candidates
        if has_target_file or getattr(candidate, "code_patch", ""):
            return self._run_promotion_pipeline(candidate)

        # Route to SafeExecutor for workspace candidates (PROMPT_TWEAK, TOOL_PREFERENCE, etc.)
        if candidate_type in ("PROMPT_TWEAK", "TOOL_PREFERENCE", "RETRY_STRATEGY", "SKIP_PATTERN"):
            return self._run_safe_executor(candidate)

        # Unknown type — log and skip
        logger.warning("si_engine.unknown_candidate_type", type=candidate_type, domain=domain)
        return {
            "candidate_type": candidate_type,
            "domain": domain,
            "decision": "SKIP",
            "reason": f"Unknown candidate type: {candidate_type}",
        }

    def _run_promotion_pipeline(self, candidate) -> dict:
        """Execute candidate through V3 PromotionPipeline."""
        try:
            from core.self_improvement.promotion_pipeline import get_promotion_pipeline
            pipeline = get_promotion_pipeline()
            result = pipeline.execute(candidate)

            logger.info(
                "si_engine.promotion_result",
                run_id=result.run_id,
                decision=result.decision,
                score=result.score,
                pr_url=result.pr_url or "none",
            )

            return {
                "candidate_type": getattr(candidate, "type", "CODE_PATCH"),
                "domain": getattr(candidate, "domain", "unknown"),
                "decision": result.decision,
                "run_id": result.run_id,
                "score": result.score,
                "risk_level": result.risk_level,
                "changed_files": result.changed_files,
                "pr_url": result.pr_url,
                "human_notified": result.human_notified,
                "error": result.error,
            }
        except Exception as exc:
            logger.error("si_engine.promotion_pipeline_error", err=str(exc))
            return {
                "candidate_type": getattr(candidate, "type", "CODE_PATCH"),
                "domain": getattr(candidate, "domain", "unknown"),
                "decision": "REJECT",
                "error": str(exc),
            }

    def _run_safe_executor(self, candidate) -> dict:
        """Execute workspace candidate through SafeExecutor."""
        try:
            from core.self_improvement.safe_executor import get_safe_executor
            executor = get_safe_executor()
            result = executor.execute(candidate)

            logger.info(
                "si_engine.safe_executor_result",
                type=getattr(candidate, "type", "?"),
                success=result.success,
            )

            return {
                "candidate_type": getattr(candidate, "type", "WORKSPACE"),
                "domain": getattr(candidate, "domain", "unknown"),
                "decision": "APPLIED" if result.success else "REJECT",
                "output": result.output,
                "error": result.error,
                "changed_file": result.changed_file,
                "rollback_triggered": result.rollback_triggered,
            }
        except Exception as exc:
            logger.error("si_engine.safe_executor_error", err=str(exc))
            return {
                "candidate_type": getattr(candidate, "type", "WORKSPACE"),
                "domain": getattr(candidate, "domain", "unknown"),
                "decision": "REJECT",
                "error": str(exc),
            }

    def _emit_cycle_event(self, failures, proposals, candidates, results: list) -> None:
        """Emit observability event for cycle completion."""
        try:
            from core.observability.event_envelope import get_event_collector
            promotes = sum(1 for r in results if r.get("decision") == "PROMOTE")
            reviews = sum(1 for r in results if r.get("decision") == "REVIEW")
            rejects = sum(1 for r in results if r.get("decision") in ("REJECT", "SKIP"))

            get_event_collector().emit_quick("self_improvement", "cycle_complete", {
                "failures": len(failures),
                "candidates": len(candidates),
                "promotes": promotes,
                "reviews": reviews,
                "rejects": rejects,
            })
        except Exception as _exc:
            log.warning("swallowed_exception", action="engine_swallow", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
