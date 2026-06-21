"""
core/memory/memory_item.py — Operational memory items for agent-coder memory.

Typed memory entries built on top of the existing memory stack.
Does NOT replace memory.schemas.MemoryEntry nor core.memory.memory_schema.MemoryEntry.
Instead, MemoryItem is a structured, searchable normalization layer for facts,
bugs, decisions, tests, skills, risks, model results and evaluation results.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class MemoryItemType(str, Enum):
    """Operational memory taxonomy for Béa."""

    REPO_FACT = "repo_fact"                     # verified fact about the repo
    BUG_MEMORY = "bug_memory"                   # known bug / pitfall
    ARCHITECTURE_DECISION = "architecture_decision"  # ADR / policy
    TEST_MAP = "test_map"                       # link module <-> tests
    SKILL = "skill"                             # reusable procedure / pattern
    RISK = "risk"                               # operational or safety risk
    MODEL_RESULT = "model_result"               # model performance result
    EVAL_RESULT = "eval_result"                 # bea eval result
    FUN_FACT = "fun_fact"                       # light, non-actionable trivia
    PROJECT_FACT = "project_fact"               # verified fact about the project/team


class MemoryItemStatus(str, Enum):
    """Lifecycle status of a memory item."""

    ACTIVE = "active"
    OBSOLETE = "obsolete"
    REPLACED = "replaced"      # operational alias for obsolete
    UNVERIFIED = "unverified"
    DANGEROUS = "dangerous"    # risk / safety rule, must be surfaced


@dataclass
class MemoryItem:
    """
    Structured operational memory entry.

    All lists default to empty, dates default to now. The id is a short UUID.
    """

    type: MemoryItemType
    title: str
    content: str
    status: MemoryItemStatus = MemoryItemStatus.ACTIVE
    confidence: float = 0.5
    source: str = ""
    related_files: list[str] = field(default_factory=list)
    related_tests: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    supersedes: list[str] = field(default_factory=list)
    superseded_by: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])

    def __post_init__(self) -> None:
        # Normalize enum values when reconstructed from strings
        if isinstance(self.type, str):
            self.type = MemoryItemType(self.type)
        if isinstance(self.status, str):
            self.status = MemoryItemStatus(self.status)
        self.confidence = max(0.0, min(1.0, float(self.confidence)))
        # Lists should be real lists, not tuples
        self.related_files = list(self.related_files or [])
        self.related_tests = list(self.related_tests or [])
        self.tags = list(self.tags or [])
        self.supersedes = list(self.supersedes or [])

    def is_usable(self) -> bool:
        """An entry is usable unless it is obsolete/replaced."""
        return self.status not in (MemoryItemStatus.OBSOLETE, MemoryItemStatus.REPLACED)

    def is_risk(self) -> bool:
        return self.status == MemoryItemStatus.DANGEROUS

    def bump_updated(self) -> "MemoryItem":
        self.updated_at = time.time()
        return self

    @property
    def is_not_for_decision(self) -> bool:
        """Returns True for memories tagged as personal/fun and unsuitable for serious decisions."""
        if self.metadata.get("not_for_decision") is True:
            return True
        if self.metadata.get("usage_rule") in {"decorative", "light_context_only"}:
            return True
        if "private_joke" in self.tags or "fun_fact" in self.tags:
            return True
        if self.metadata.get("importance") == "low" and "personal" in self.metadata.get("privacy", ""):
            return True
        return False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["type"] = self.type.value
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryItem":
        return cls(
            id=data.get("id", str(uuid.uuid4())[:12]),
            type= MemoryItemType(data.get("type", MemoryItemType.REPO_FACT.value)),
            title=data.get("title", ""),
            content=data.get("content", ""),
            status=MemoryItemStatus(data.get("status", MemoryItemStatus.ACTIVE.value)),
            confidence=float(data.get("confidence", 0.5)),
            source=data.get("source", ""),
            related_files=list(data.get("related_files", [])),
            related_tests=list(data.get("related_tests", [])),
            tags=list(data.get("tags", [])),
            supersedes=list(data.get("supersedes", [])),
            superseded_by=data.get("superseded_by"),
            metadata=dict(data.get("metadata", {})),
            created_at=float(data.get("created_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())),
        )

    @property
    def search_text(self) -> str:
        """Plain text used for full-text search indexing."""
        parts = [self.title, self.content, self.source]
        parts.extend(self.tags)
        parts.extend(self.related_files)
        parts.extend(self.related_tests)
        return " ".join(str(p) for p in parts if p)
