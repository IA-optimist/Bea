"""
agent_memory — Structured agent memory with MemGPT-inspired tiered storage.

Public surface:
    from agent_memory import MemoryType, StructuredMemory, AgentMemoryStore
    from agent_memory import CodebaseMemoryService
"""
from __future__ import annotations

from agent_memory.models import MemoryType, StructuredMemory
from agent_memory.store import AgentMemoryStore
from agent_memory.codebase import CodebaseMemoryService

__all__ = [
    "MemoryType",
    "StructuredMemory",
    "AgentMemoryStore",
    "CodebaseMemoryService",
]
