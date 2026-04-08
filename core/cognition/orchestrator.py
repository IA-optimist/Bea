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
