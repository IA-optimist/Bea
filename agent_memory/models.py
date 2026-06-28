"""
agent_memory/models.py — StructuredMemory: typed memory item with required provenance.

Every memory entry requires:
  - realm: the knowledge domain (code, research, data, ops, security)
  - source: how it was acquired (agent_id, tool name, human note, etc.)
  - confidence: float 0.0–1.0

This prevents the "confident hallucination" pattern where agents assert
facts without provenance.  Entries with confidence < 0.5 are surfaced as
uncertain in recall.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class MemoryType(str, Enum):
    """Taxonomy of structured agent memories."""

    FACT = "fact"                        # verified fact about code/project
    DECISION = "decision"                # architectural / design decision
    BUG = "bug"                          # known bug or pitfall
    LESSON = "lesson"                    # what worked / didn't
    SKILL = "skill"                      # reusable procedure (has tests)
    RISK = "risk"                        # operational or safety risk
    RESEARCH_FINDING = "research_finding"  # fact from external research
    DATA_INSIGHT = "data_insight"        # finding from data analysis
    TEST_MAP = "test_map"                # module ↔ test file mapping
    SECURITY_NOTE = "security_note"      # security observation


class StructuredMemory(BaseModel):
    """
    A typed, provenanced memory entry.

    Agents must supply realm, source, and confidence.
    Content is capped at 4000 chars to prevent unbounded growth.
    """

    memory_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    memory_type: MemoryType
    realm: str = Field(min_length=2, max_length=64)
    source: str = Field(min_length=2, max_length=256)  # who/what created this
    confidence: float = Field(ge=0.0, le=1.0)
    content: str = Field(min_length=5, max_length=4000)
    tags: list[str] = Field(default_factory=list)
    mission_id: str | None = None
    agent_id: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)
    superseded_by: str | None = None  # memory_id of the replacement

    @field_validator("realm")
    @classmethod
    def realm_lowercase(cls, v: str) -> str:
        return v.lower().strip()

    @field_validator("tags")
    @classmethod
    def tags_lowercase(cls, v: list[str]) -> list[str]:
        return [t.lower().strip() for t in v]

    @property
    def is_uncertain(self) -> bool:
        return self.confidence < 0.5

    @property
    def is_superseded(self) -> bool:
        return self.superseded_by is not None

    @property
    def is_security_sensitive(self) -> bool:
        return self.memory_type in (
            MemoryType.SECURITY_NOTE,
            MemoryType.RISK,
        )

    def to_recall_context(self) -> str:
        """Format for injection into agent context (safe, no secrets)."""
        uncertain_prefix = "[UNCERTAIN] " if self.is_uncertain else ""
        return (
            f"{uncertain_prefix}[{self.memory_type.value.upper()}] "
            f"(confidence={self.confidence:.0%}, source={self.source})\n"
            f"{self.content}"
        )
