"""
Lifelong Learning Engine for JarvisMax (Phase 5.4)
===================================================
Voyager-style automatic skill discovery and persistence.

Features:
- Mission replay for learning
- Skill extraction from successful missions
- Confidence-based skill validation
- Qdrant persistence for skills
- Auto skill library building
"""
from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
import structlog

log = structlog.get_logger(__name__)


@dataclass
class Skill:
    """Learned skill."""
    
    skill_id: str
    name: str
    description: str
    code: str  # Python code or tool sequence
    success_count: int = 0
    failure_count: int = 0
    avg_confidence: float = 0.0
    tags: List[str] = field(default_factory=list)
    learned_from: List[str] = field(default_factory=list)  # Mission IDs
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_used: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 0.0
    
    @property
    def is_validated(self) -> bool:
        """Skill is validated if success rate > 70% and used >= 3 times."""
        total = self.success_count + self.failure_count
        return total >= 3 and self.success_rate > 0.7


class LifelongLearningEngine:
    """
    Manages skill discovery, validation, and persistence.
    
    Inspired by Voyager (MineDojo): autonomous curriculum learning
    through skill composition and iterative refinement.
    """
    
    def __init__(self, db_engine=None, qdrant_client=None):
        self.db = db_engine
        self.qdrant = qdrant_client
        self.skills: Dict[str, Skill] = {}
        self.mission_history: List[Dict] = []
        
    async def initialize(self):
        """Load skills from storage."""
        if self.qdrant:
            try:
                from core.memory.qdrant_client import get_qdrant
                q = get_qdrant()
                results = q.search('jarvis_skills', [0.0] * 768, limit=200, score_threshold=0.0)
                for hit in results:
                    p = hit.get('payload', {})
                    if p.get('skill_id'):
                        from core.cognition.lifelong_learning import Skill
                        sk = Skill(
                            skill_id=p['skill_id'],
                            name=p.get('name', ''),
                            description=p.get('description', ''),
                            code=p.get('code', ''),
                            success_rate=p.get('success_rate', 0.0),
                            confidence=p.get('confidence', 0.5),
                        )
                        self.skills[sk.skill_id] = sk
            except Exception as _e:
                log.warning("skills_load_failed", err=str(_e)[:80])
            log.info("lifelong_learning_initialized", skill_count=len(self.skills))
        else:
            log.warning("no_qdrant", msg="Skills won't persist across restarts")
    
    async def record_mission(
        self,
        mission_id: str,
        goal: str,
        result: str,
        success: bool,
        confidence: float,
        tools_used: List[str],
        execution_trace: List[Dict[str, Any]]
    ):
        """
        Record mission execution for learning.
        
        Args:
            mission_id: Unique mission identifier
            goal: Mission objective
            result: Outcome
            success: Whether mission succeeded
            confidence: Confidence score (0-1)
            tools_used: List of tools/APIs called
            execution_trace: Sequence of actions taken
        """
        mission_record = {
            "mission_id": mission_id,
            "goal": goal,
            "result": result,
            "success": success,
            "confidence": confidence,
            "tools_used": tools_used,
            "execution_trace": execution_trace,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        self.mission_history.append(mission_record)
        
        # Keep last 100 missions
        if len(self.mission_history) > 100:
            self.mission_history = self.mission_history[-100:]
        
        log.info(
            "mission_recorded",
            mission_id=mission_id,
            success=success,
            confidence=confidence,
            tools_count=len(tools_used)
        )
        
        # Auto-extract skill if high confidence success
        if success and confidence > 0.8:
            await self._try_extract_skill(mission_record)
    
    async def _try_extract_skill(self, mission: Dict[str, Any]):
        """
        Extract reusable skill from successful mission.
        
        Criteria for skill extraction:
        - High confidence (>0.8)
        - Used multiple tools (>1)
        - Novel pattern (not similar to existing skills)
        """
        tools_used = mission["tools_used"]
        
        if len(tools_used) <= 1:
            return  # Too simple to be a skill
        
        # Generate skill hash
        skill_pattern = "|".join(sorted(tools_used))
        skill_hash = hashlib.md5(skill_pattern.encode()).hexdigest()[:8]
        skill_id = f"skill-{skill_hash}"
        
        # Check if similar skill exists
        if skill_id in self.skills:
            # Update existing skill stats
            skill = self.skills[skill_id]
            skill.success_count += 1
            skill.last_used = datetime.now(timezone.utc)
            skill.learned_from.append(mission["mission_id"])
            
            # Update confidence (rolling average)
            total = skill.success_count + skill.failure_count
            skill.avg_confidence = (
                (skill.avg_confidence * (total - 1) + mission["confidence"]) / total
            )
            
            log.info("skill_reinforced", skill_id=skill_id, uses=total)
            return
        
        # Create new skill
        skill = Skill(
            skill_id=skill_id,
            name=f"Auto: {mission['goal'][:50]}",
            description=f"Learned from mission {mission['mission_id']}",
            code=json.dumps({
                "tools": tools_used,
                "trace": mission["execution_trace"]
            }),
            success_count=1,
            avg_confidence=mission["confidence"],
            tags=tools_used,
            learned_from=[mission["mission_id"]]
        )
        
        self.skills[skill_id] = skill
        
        log.info(
            "skill_discovered",
            skill_id=skill_id,
            name=skill.name,
            tools=tools_used
        )
        
        # Persist to Qdrant if available
        if self.qdrant:
            await self._persist_skill(skill)
    
    async def _persist_skill(self, skill: Skill):
        """Store skill in Qdrant for long-term memory."""
        if not self.qdrant:
            return
        
        try:
            from core.memory.qdrant_client import get_qdrant
            from core.memory.embedding_provider import EmbeddingProvider
            ep = EmbeddingProvider()
            text = skill.name + ' ' + skill.description + ' ' + (skill.code or '')
            vec = ep.embed(text)
            q = get_qdrant()
            q.ensure_collection('jarvis_skills', size=len(vec))
            q.upsert('jarvis_skills', skill.skill_id, vec, {
                'skill_id': skill.skill_id,
                'name': skill.name,
                'description': skill.description,
                'code': skill.code or '',
                'success_rate': skill.success_rate,
                'confidence': skill.confidence,
                'is_validated': skill.is_validated,
            })
        except Exception as _e:
            log.warning("skill_persist_failed", skill_id=skill.skill_id, err=str(_e)[:80])
        log.info("skill_persisted", skill_id=skill.skill_id)
    
    async def suggest_skills_for_goal(self, goal: str, limit: int = 3) -> List[Skill]:
        """
        Suggest relevant skills for a given goal.
        
        Uses semantic similarity if Qdrant available,
        otherwise falls back to keyword matching.
        """
        if self.qdrant:
            try:
                from core.memory.qdrant_client import get_qdrant
                from core.memory.embedding_provider import EmbeddingProvider
                ep = EmbeddingProvider()
                vec = ep.embed(goal)
                q = get_qdrant()
                results = q.search('jarvis_skills', vec, limit=limit, score_threshold=0.4)
                found = []
                for hit in results:
                    sid = hit.get('payload', {}).get('skill_id', '')
                    if sid and sid in self.skills:
                        found.append(self.skills[sid])
                if found:
                    return found[:limit]
            except Exception as _e:
                log.warning("skill_search_failed", err=str(_e)[:80])
        
        # Fallback: keyword match
        goal_lower = goal.lower()
        matches = []
        
        for skill in self.skills.values():
            if not skill.is_validated:
                continue  # Only suggest validated skills
            
            # Simple keyword overlap
            skill_keywords = skill.name.lower().split() + skill.tags
            overlap = sum(1 for word in goal_lower.split() if word in skill_keywords)
            
            if overlap > 0:
                matches.append((overlap, skill))
        
        # Sort by overlap + success rate
        matches.sort(key=lambda x: (x[0], x[1].success_rate), reverse=True)
        
        return [skill for _, skill in matches[:limit]]
    
    def get_skill_library_summary(self) -> Dict[str, Any]:
        """Get summary of all learned skills."""
        validated = [s for s in self.skills.values() if s.is_validated]
        
        return {
            "total_skills": len(self.skills),
            "validated_skills": len(validated),
            "total_missions": len(self.mission_history),
            "avg_success_rate": sum(s.success_rate for s in validated) / len(validated)
                if validated else 0.0,
            "top_skills": [
                {
                    "id": s.skill_id,
                    "name": s.name,
                    "success_rate": s.success_rate,
                    "uses": s.success_count + s.failure_count,
                }
                for s in sorted(validated, key=lambda x: x.success_rate, reverse=True)[:5]
            ]
        }
    
    async def replay_mission_for_learning(self, mission_id: str) -> Dict[str, Any]:
        """
        Replay a past mission to extract insights.
        
        Useful for:
        - Refining skills based on new context
        - Identifying failure patterns
        - Composing complex skills from simple ones
        """
        mission = next((m for m in self.mission_history if m["mission_id"] == mission_id), None)
        
        if not mission:
            return {"error": "Mission not found"}
        
        log.info("mission_replay", mission_id=mission_id, goal=mission["goal"])
        
        # Re-analyze execution trace
        insights = {
            "mission_id": mission_id,
            "tools_used": mission["tools_used"],
            "tool_count": len(mission["tools_used"]),
            "success": mission["success"],
            "confidence": mission["confidence"],
            "learning_opportunities": []
        }
        
        # Check if execution could be optimized
        if len(mission["tools_used"]) > 3:
            insights["learning_opportunities"].append({
                "type": "skill_composition",
                "suggestion": "Consider composing a macro skill from this sequence"
            })
        
        if not mission["success"] and mission["confidence"] < 0.5:
            insights["learning_opportunities"].append({
                "type": "failure_pattern",
                "suggestion": "Low confidence failure - may need better reasoning strategy"
            })
        
        return insights
