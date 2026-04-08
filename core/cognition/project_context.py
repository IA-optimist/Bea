"""
Multi-Project Context Manager for JarvisMax (Phase 5.2)
========================================================
Manages project-specific memory, context, and cognitive state.

Each project has:
- Dedicated memory store (RAG via Qdrant)
- Conversation history
- Learned skills
- Performance metrics
- Active goals/missions
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any
import structlog

log = structlog.get_logger(__name__)


@dataclass
class ProjectContext:
    """Context for a single project."""
    
    project_id: int
    name: str
    description: str = ""
    
    # Memory
    recent_messages: List[Dict[str, str]] = field(default_factory=list)
    long_term_memory_ids: List[str] = field(default_factory=list)  # Qdrant IDs
    
    # Skills
    learned_skills: List[str] = field(default_factory=list)
    
    # State
    active_missions: List[str] = field(default_factory=list)
    current_goal: Optional[str] = None
    
    # Performance
    success_count: int = 0
    failure_count: int = 0
    avg_confidence: float = 0.0
    
    # Metadata
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_active: datetime = field(default_factory=datetime.utcnow)
    
    def add_message(self, role: str, content: str):
        """Add message to recent history (keep last 20)."""
        self.recent_messages.append({
            "role": role,
            "content": content,
            "timestamp": datetime.utcnow().isoformat()
        })
        if len(self.recent_messages) > 20:
            self.recent_messages = self.recent_messages[-20:]
        self.last_active = datetime.utcnow()
    
    def record_mission_result(self, success: bool, confidence: float):
        """Update performance metrics."""
        if success:
            self.success_count += 1
        else:
            self.failure_count += 1
        
        # Rolling average confidence
        total = self.success_count + self.failure_count
        self.avg_confidence = (
            (self.avg_confidence * (total - 1) + confidence) / total
        )


class ProjectContextManager:
    """
    Manages multiple project contexts with intelligent switching.
    
    Features:
    - Project-specific memory (RAG)
    - Context switching
    - Skill inheritance between projects
    - Performance tracking per project
    """
    
    def __init__(self, db_engine=None, qdrant_client=None):
        self.db = db_engine
        self.qdrant = qdrant_client
        self.contexts: Dict[int, ProjectContext] = {}
        self.current_project_id: Optional[int] = None
        
    async def initialize(self):
        """Load all projects from database."""
        if not self.db:
            log.warning("no_db_engine", msg="ProjectContextManager without DB")
            # Create default project
            self.contexts[1] = ProjectContext(
                project_id=1,
                name="Central Chat",
                description="Default conversational project"
            )
            self.current_project_id = 1
            return
        
        # TODO: Load from projects table
        log.info("project_contexts_initialized", count=len(self.contexts))
    
    def get_current_context(self) -> Optional[ProjectContext]:
        """Get currently active project context."""
        if self.current_project_id is None:
            return None
        return self.contexts.get(self.current_project_id)
    
    def switch_project(self, project_id: int) -> ProjectContext:
        """Switch to different project."""
        if project_id not in self.contexts:
            raise ValueError(f"Project {project_id} not found")
        
        old_id = self.current_project_id
        self.current_project_id = project_id
        
        log.info(
            "project_switched",
            from_project=old_id,
            to_project=project_id,
            name=self.contexts[project_id].name
        )
        
        return self.contexts[project_id]
    
    def get_project_memory(self, project_id: int, limit: int = 5) -> List[Dict]:
        """Retrieve recent messages for a project."""
        if project_id not in self.contexts:
            return []
        return self.contexts[project_id].recent_messages[-limit:]
    
    async def store_in_long_term_memory(
        self,
        project_id: int,
        content: str,
        metadata: Dict[str, Any]
    ) -> str:
        """
        Store important information in Qdrant for project.
        
        Returns Qdrant point ID.
        """
        if not self.qdrant:
            log.warning("no_qdrant_client", msg="Cannot store long-term memory")
            return ""
        
        # TODO: Implement Qdrant storage
        # - Generate embedding
        # - Store in project-specific collection
        # - Return point ID
        
        log.info(
            "long_term_memory_stored",
            project_id=project_id,
            content_length=len(content)
        )
        
        return f"mock-qdrant-id-{project_id}"
    
    async def retrieve_relevant_memory(
        self,
        project_id: int,
        query: str,
        limit: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Semantic search in project's long-term memory.
        
        Returns most relevant memory items.
        """
        if not self.qdrant:
            return []
        
        # TODO: Implement Qdrant search
        # - Generate query embedding
        # - Search project collection
        # - Return top results
        
        return []
    
    def add_learned_skill(self, project_id: int, skill_name: str):
        """Record that project learned a new skill."""
        if project_id in self.contexts:
            ctx = self.contexts[project_id]
            if skill_name not in ctx.learned_skills:
                ctx.learned_skills.append(skill_name)
                log.info(
                    "skill_learned",
                    project_id=project_id,
                    skill=skill_name,
                    total_skills=len(ctx.learned_skills)
                )
    
    def get_all_skills(self, include_global: bool = True) -> List[str]:
        """
        Get all skills across projects.
        
        If include_global=True, includes skills from all projects.
        Otherwise, only current project's skills.
        """
        if not include_global and self.current_project_id:
            ctx = self.contexts.get(self.current_project_id)
            return ctx.learned_skills if ctx else []
        
        # Collect from all projects (deduplicated)
        all_skills = set()
        for ctx in self.contexts.values():
            all_skills.update(ctx.learned_skills)
        
        return list(all_skills)
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """Get performance metrics across all projects."""
        total_success = sum(ctx.success_count for ctx in self.contexts.values())
        total_failure = sum(ctx.failure_count for ctx in self.contexts.values())
        total = total_success + total_failure
        
        return {
            "total_projects": len(self.contexts),
            "total_missions": total,
            "success_rate": total_success / total if total > 0 else 0.0,
            "avg_confidence": sum(
                ctx.avg_confidence for ctx in self.contexts.values()
            ) / len(self.contexts) if self.contexts else 0.0,
            "projects": [
                {
                    "id": ctx.project_id,
                    "name": ctx.name,
                    "missions": ctx.success_count + ctx.failure_count,
                    "success_rate": ctx.success_count / (ctx.success_count + ctx.failure_count)
                        if (ctx.success_count + ctx.failure_count) > 0 else 0.0,
                    "avg_confidence": ctx.avg_confidence,
                    "skills": len(ctx.learned_skills),
                }
                for ctx in self.contexts.values()
            ]
        }
