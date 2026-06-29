from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from agent_cyber.scope import CyberScopePolicy


class FactStatus(str, Enum):
    CONFIRMED = "confirmed"
    TENTATIVE = "tentative"
    REJECTED = "rejected"


class IntentStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    ABANDONED = "abandoned"
    BLOCKED = "blocked"


class CyberFact(BaseModel):
    fact_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    mission_id: str
    content: str
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    status: FactStatus = FactStatus.TENTATIVE
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @model_validator(mode="after")
    def confirmed_fact_needs_evidence(self) -> "CyberFact":
        if self.status == FactStatus.CONFIRMED and not self.evidence_refs:
            raise ValueError("CONFIRMED fact requires at least one evidence_ref")
        return self


class CyberIntent(BaseModel):
    intent_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    mission_id: str
    goal: str
    action_type: str
    target: Optional[str] = None
    status: IntentStatus = IntentStatus.OPEN
    reason: str = ""
    depends_on_facts: list[str] = Field(default_factory=list)
    generated_findings: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


class CyberMissionGraph:
    """Tracks cyber mission progress. Prevents loops and duplicate execution."""

    def __init__(self, mission_id: str, scope: CyberScopePolicy) -> None:
        self.mission_id = mission_id
        self.scope = scope
        self.facts: dict[str, CyberFact] = {}
        self.intents: dict[str, CyberIntent] = {}
        self.findings: list[str] = []
        self.blockers: list[str] = []

    def add_fact(self, fact: CyberFact) -> None:
        self.facts[fact.fact_id] = fact

    def add_intent(self, intent: CyberIntent) -> None:
        self.intents[intent.intent_id] = intent

    def execute_intent(self, intent_id: str) -> CyberIntent:
        """Mark intent as IN_PROGRESS. Blocks if already done/blocked."""
        intent = self.intents.get(intent_id)
        if intent is None:
            raise KeyError(f"Intent '{intent_id}' not found in graph")
        if intent.status in (IntentStatus.DONE, IntentStatus.ABANDONED):
            raise RuntimeError(
                f"Intent '{intent_id}' already {intent.status.value} — cannot re-execute"
            )
        if intent.status == IntentStatus.BLOCKED:
            raise RuntimeError(f"Intent '{intent_id}' is BLOCKED: {intent.reason}")
        updated = intent.model_copy(update={"status": IntentStatus.IN_PROGRESS})
        self.intents[intent_id] = updated
        return updated

    def complete_intent(
        self,
        intent_id: str,
        finding_ids: Optional[list[str]] = None,
    ) -> None:
        intent = self.intents.get(intent_id)
        if intent is None:
            raise KeyError(f"Intent '{intent_id}' not found")
        self.intents[intent_id] = intent.model_copy(
            update={
                "status": IntentStatus.DONE,
                "generated_findings": finding_ids or [],
                "completed_at": datetime.utcnow(),
            }
        )
        if finding_ids:
            self.findings.extend(finding_ids)

    def block_intent(self, intent_id: str, reason: str) -> None:
        intent = self.intents.get(intent_id)
        if intent is None:
            raise KeyError(f"Intent '{intent_id}' not found")
        self.intents[intent_id] = intent.model_copy(
            update={"status": IntentStatus.BLOCKED, "reason": reason}
        )
        self.blockers.append(f"{intent_id}: {reason}")

    @property
    def has_open_intents(self) -> bool:
        return any(i.status == IntentStatus.OPEN for i in self.intents.values())

    @property
    def should_stop(self) -> bool:
        if not self.has_open_intents:
            return True
        if self.scope.is_expired:
            return True
        return False
