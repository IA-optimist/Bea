"""
Global Workspace Theory Implementation
Cognitive architecture module inspired by Bernard Baars' Global Workspace Theory.

Metaphor: A "conscious workspace" where agents publish their outputs with confidence scores.
Other agents can read recent broadcasts to coordinate and build shared context.

Key concepts:
- Broadcasting: Agents publish results to the global workspace
- Attention: High-confidence broadcasts are more "prominent" 
- Working memory: Recent broadcasts decay over time (default: last 100 entries)
- Cross-talk: Enables inter-agent communication and collective intelligence

Usage:
    from core.global_workspace import get_workspace
    
    # Agent publishes result
    await get_workspace().publish(
        agent="architect",
        content="Designed 3-tier microservice architecture",
        confidence=0.9,
        metadata={'domain': 'architecture'}
    )
    
    # Other agent reads recent context
    recent = await get_workspace().get_recent(limit=10, min_confidence=0.7)
"""
from __future__ import annotations

import asyncio
import structlog
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field, asdict
from collections import deque

log = structlog.get_logger(__name__)


@dataclass
class WorkspaceEntry:
    """A single broadcast entry in the global workspace."""
    agent: str
    content: str
    confidence: float
    timestamp: float = field(default_factory=lambda: datetime.now().timestamp())
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    def is_expired(self, max_age_seconds: int = 3600) -> bool:
        """Check if entry is older than max_age_seconds."""
        return (datetime.now().timestamp() - self.timestamp) > max_age_seconds


class GlobalWorkspace:
    """
    Singleton global workspace - implements Global Workspace Theory.
    
    Maintains a rolling buffer of agent broadcasts, enabling:
    - Inter-agent awareness (consciousness metaphor)
    - Context propagation across the agent network
    - Collective intelligence through shared attention
    """
    
    def __init__(self, max_entries: int = 100):
        self.max_entries = max_entries
        self.broadcasts: deque[WorkspaceEntry] = deque(maxlen=max_entries)
        self._lock = asyncio.Lock()
        self.total_published = 0
        self.agents_seen = set()
        log.info("global_workspace.initialized", max_entries=max_entries)
    
    async def publish(
        self,
        agent: str,
        content: str,
        confidence: float = 0.8,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Publish agent output to the global workspace.
        
        Args:
            agent: Agent name (e.g., "architect", "coder", "qa")
            content: Output content (truncated to 500 chars for memory efficiency)
            confidence: Confidence score 0.0-1.0 (higher = more "prominent")
            metadata: Optional metadata dict (domain, mission_id, etc.)
        """
        async with self._lock:
            # Truncate content for memory efficiency
            truncated_content = content[:500] if len(content) > 500 else content
            
            entry = WorkspaceEntry(
                agent=agent,
                content=truncated_content,
                confidence=max(0.0, min(1.0, confidence)),  # Clamp 0-1
                metadata=metadata or {}
            )
            
            self.broadcasts.append(entry)
            self.total_published += 1
            self.agents_seen.add(agent)
            
            log.debug(
                "global_workspace.published",
                agent=agent,
                confidence=confidence,
                content_len=len(content),
                total_entries=len(self.broadcasts)
            )
    
    async def get_recent(
        self,
        limit: int = 10,
        min_confidence: float = 0.0,
        agent_filter: Optional[str] = None,
        max_age_seconds: int = 3600
    ) -> List[Dict[str, Any]]:
        """
        Retrieve recent broadcasts from the workspace.
        
        Args:
            limit: Max number of entries to return
            min_confidence: Filter by minimum confidence threshold
            agent_filter: Only return broadcasts from specific agent
            max_age_seconds: Filter out entries older than this (default: 1h)
        
        Returns:
            List of broadcast entries as dicts, newest first
        """
        async with self._lock:
            # Filter broadcasts
            filtered = [
                entry for entry in self.broadcasts
                if (entry.confidence >= min_confidence
                    and (agent_filter is None or entry.agent == agent_filter)
                    and not entry.is_expired(max_age_seconds))
            ]
            
            # Sort by timestamp desc (newest first), then by confidence
            sorted_entries = sorted(
                filtered,
                key=lambda e: (e.timestamp, e.confidence),
                reverse=True
            )
            
            # Return top N as dicts
            return [entry.to_dict() for entry in sorted_entries[:limit]]
    
    async def get_by_agent(self, agent: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Get recent broadcasts from a specific agent."""
        return await self.get_recent(limit=limit, agent_filter=agent)
    
    async def get_high_confidence(self, threshold: float = 0.8, limit: int = 10) -> List[Dict[str, Any]]:
        """Get high-confidence broadcasts (attention mechanism)."""
        return await self.get_recent(limit=limit, min_confidence=threshold)
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get workspace statistics."""
        async with self._lock:
            if not self.broadcasts:
                return {
                    'total_entries': 0,
                    'total_published': self.total_published,
                    'unique_agents': 0,
                    'avg_confidence': 0.0
                }
            
            confidences = [entry.confidence for entry in self.broadcasts]
            
            return {
                'total_entries': len(self.broadcasts),
                'total_published': self.total_published,
                'unique_agents': len(self.agents_seen),
                'agents': list(self.agents_seen),
                'avg_confidence': round(sum(confidences) / len(confidences), 3),
                'max_confidence': round(max(confidences), 3),
                'min_confidence': round(min(confidences), 3),
                'oldest_entry_age_seconds': round(
                    datetime.now().timestamp() - min(e.timestamp for e in self.broadcasts),
                    1
                )
            }
    
    async def clear(self) -> None:
        """Clear all broadcasts (for testing/reset)."""
        async with self._lock:
            self.broadcasts.clear()
            log.info("global_workspace.cleared")


# Singleton instance
_workspace: Optional[GlobalWorkspace] = None


def get_workspace() -> GlobalWorkspace:
    """Get the singleton global workspace instance."""
    global _workspace
    if _workspace is None:
        _workspace = GlobalWorkspace()
    return _workspace


def reset_workspace() -> None:
    """Reset the singleton (for testing)."""
    global _workspace
    _workspace = None
