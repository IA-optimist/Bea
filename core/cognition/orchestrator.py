"""
Cognition Orchestrator - Integrates all AGI patterns.
Coordinates ToT, self-confidence, and active learning.
"""
from __future__ import annotations
from typing import Dict, Any, Optional
import structlog
from core.cognition.tot_wrapper import plan_with_tot, should_use_tot
from core.cognition.self_confidence import ConfidenceScorer, SelfCorrector
from core.cognition.active_learning import SkillDiscoverer, PerformanceTracker

log = structlog.get_logger(__name__)

# Global performance tracker
_performance_tracker = PerformanceTracker()


class CognitionOrchestrator:
    """
    Coordinates AGI-like cognition patterns for mission execution.
    
    Flow:
    1. Decide if ToT needed (complex missions)
    2. Execute mission (with or without ToT)
    3. Score output confidence
    4. Auto-correct if low confidence
    5. Track performance
    6. Discover skills from successes
    """
    
    def __init__(self, llm_client):
        self.llm = llm_client
        self.scorer = ConfidenceScorer(llm_client)
        self.corrector = SelfCorrector(llm_client)
        self.discoverer = SkillDiscoverer(llm_client)
        self.tracker = _performance_tracker
    
    async def execute_mission_with_cognition(
        self,
        mission: Dict[str, Any],
        enable_tot: bool = True,
        enable_confidence: bool = True,
        enable_learning: bool = True
    ) -> Dict[str, Any]:
        """
        Execute mission with full AGI cognition pipeline.
        
        Returns augmented mission with cognition metadata.
        """
        
        goal = mission.get("goal", "")
        mission_id = mission.get("mission_id", "unknown")
        
        log.info(
            "cognition_mission_start",
            mission_id=mission_id,
            goal=goal[:100],
            tot=enable_tot,
            confidence=enable_confidence
        )
        
        # Step 1: Tree-of-Thought planning (if complex)
        tot_result = None
        if enable_tot and should_use_tot(goal):
            log.info("using_tot_planning", mission_id=mission_id)
            tot_result = await plan_with_tot(goal, self.llm)
            mission["tot_plan"] = tot_result
            mission["plan_confidence"] = tot_result["confidence"]
        
        # Step 2: Execute mission (placeholder - would call actual executor)
        # For now, assume mission["result"] is already populated
        output = mission.get("result", "")
        
        # Step 3: Score confidence
        confidence_result = None
        if enable_confidence and output:
            confidence_result = self.scorer.score_output(goal, output)
            mission["confidence_score"] = confidence_result["confidence"]
            mission["confidence_issues"] = confidence_result["issues"]
            
            # Step 4: Auto-correct if needed
            if confidence_result["should_retry"]:
                log.info("attempting_self_correction", mission_id=mission_id)
                correction = await self.corrector.correct_output(
                    goal, output, confidence_result
                )
                
                if correction["corrected"]:
                    mission["result"] = correction["output"]
                    mission["was_corrected"] = True
                    mission["correction_improved"] = (
                        correction["new_score"]["confidence"] > 
                        correction["original_score"]["confidence"]
                    )
        
        # Step 5: Track performance
        if enable_learning:
            self.tracker.record_mission(mission)
        
        # Step 6: Discover skills
        if enable_learning and mission.get("status") == "COMPLETED":
            skill_analysis = self.discoverer.analyze_mission(mission)
            if skill_analysis.get("is_skill_worthy"):
                log.info(
                    "skill_discovered",
                    mission_id=mission_id,
                    skill_name=skill_analysis.get("skill_name")
                )
                mission["discovered_skill"] = skill_analysis
        
        # Add cognition metadata
        mission["cognition"] = {
            "tot_used": tot_result is not None,
            "confidence_scored": confidence_result is not None,
            "was_corrected": mission.get("was_corrected", False),
            "skill_discovered": "discovered_skill" in mission
        }
        
        log.info(
            "cognition_mission_complete",
            mission_id=mission_id,
            tot_used=mission["cognition"]["tot_used"],
            corrected=mission["cognition"]["was_corrected"]
        )
        
        return mission
    
    def get_performance_report(self) -> Dict[str, Any]:
        """Get current performance metrics."""
        return self.tracker.get_report()

    async def execute_mission_with_cognition(
        self,
        delegate: Any,
        supervise_fn: Callable,
        mission_payload: dict,
        timeout: int,
    ) -> Any:
        """
        Execute a mission with full AGI cognition pipeline:
        1. Tree-of-Thought reasoning for complex decisions
        2. Self-Confidence scoring for output quality
        3. Active Learning for performance tracking
        
        Args:
            delegate: JarvisOrchestrator instance
            supervise_fn: Supervisor wrapper function
            mission_payload: Dict with mission_id, goal, mode, etc.
            timeout: Execution timeout in seconds
            
        Returns:
            Outcome object from supervise_fn (same schema as direct execution)
        """
        import asyncio
        from datetime import datetime
        
        mission_id = mission_payload["mission_id"]
        goal = mission_payload["goal"]
        
        log.info(
            "cognition.mission_start",
            mission_id=mission_id,
            goal_length=len(goal),
            timeout=timeout,
        )
        
        start_time = datetime.now()
        
        # Phase 1: Tree-of-Thought reasoning (optional — for high-complexity tasks)
        # For now, skip ToT expansion to avoid 30s+ delays
        # TODO: Activate for complexity > 7 or confidence < 0.5
        thought_tree = None
        
        # Phase 2: Execute mission with supervisor
        try:
            outcome = await asyncio.wait_for(
                supervise_fn(
                    delegate.run,
                    mission_id=mission_payload["mission_id"],
                    goal=mission_payload["goal"],
                    mode=mission_payload["mode"],
                    session_id=mission_payload["session_id"],
                    risk_level=mission_payload["risk_level"],
                    requires_approval=mission_payload["requires_approval"],
                    skip_approval=mission_payload["skip_approval"],
                    callback=mission_payload["callback"],
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            log.error("cognition.mission_timeout", mission_id=mission_id, timeout=timeout)
            # Return timeout outcome
            from dataclasses import dataclass
            @dataclass
            class TimeoutOutcome:
                success: bool = False
                error: str = f"Mission timed out after {timeout}s"
                result: str = ""
                decision_trace: list = None
            return TimeoutOutcome()
        except Exception as exec_err:
            log.error("cognition.execution_error", mission_id=mission_id, error=str(exec_err)[:200])
            raise
        
        # Phase 3: Self-Confidence scoring
        confidence_score = 0.5  # Default neutral
        if outcome.success:
            try:
                result_text = getattr(outcome, "result", "")
                confidence_score = self.scorer.score_output(goal, result_text)
                log.info(
                    "cognition.confidence_scored",
                    mission_id=mission_id,
                    score=confidence_score,
                )
            except Exception as conf_err:
                log.warning("cognition.confidence_failed", error=str(conf_err)[:100])
        
        # Phase 4: Performance tracking
        duration = (datetime.now() - start_time).total_seconds()
        mission_record = {
            "id": mission_id,
            "status": "SUCCESS" if outcome.success else "FAILED",
            "duration": duration,
            "confidence": confidence_score,
            "domain": mission_payload.get("classification", {}).get("domain", "general"),
        }
        self.tracker.record_mission(mission_record)
        
        # Phase 5: Skill discovery (for successful complex missions)
        complexity = mission_payload.get("classification", {}).get("complexity", 0)
        if outcome.success and complexity > 5:
            try:
                # Extract steps from outcome (if available)
                steps = []
                if hasattr(outcome, "decision_trace") and outcome.decision_trace:
                    steps = [d.get("step", "") for d in outcome.decision_trace if isinstance(d, dict)]
                
                skill_complexity = self.discoverer.calculate_complexity(
                    goal=goal,
                    steps=steps,
                    agent_count=1,
                    duration=duration,
                )
                
                if skill_complexity > 6:  # High complexity threshold
                    log.info(
                        "cognition.skill_discovery_triggered",
                        mission_id=mission_id,
                        complexity=skill_complexity,
                    )
                    # TODO: Call skill_discoverer.propose_skill() with LLM
            except Exception as skill_err:
                log.warning("cognition.skill_discovery_failed", error=str(skill_err)[:100])
        
        # Log final cognition summary
        perf_report = self.tracker.get_report()
        log.info(
            "cognition.mission_complete",
            mission_id=mission_id,
            success=outcome.success,
            confidence=confidence_score,
            duration=duration,
            total_missions=perf_report["summary"]["total_missions"],
            success_rate=perf_report["summary"]["success_rate"],
        )
        
        return outcome
