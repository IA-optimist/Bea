from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class DifficultyLevel(str, Enum):
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


class CyberEvalTask(BaseModel):
    task_id: str
    title: str
    repo_ref: Optional[str] = None
    fixture_path: Optional[str] = None
    difficulty: DifficultyLevel
    prompt: str
    hints: list[str] = Field(default_factory=list)
    expected_vulnerable: bool
    expected_vuln_class: str
    expected_locations: list[dict] = Field(default_factory=list)
    safe_context: str = ""
    tags: list[str] = Field(default_factory=list)


class CandidateFinding(BaseModel):
    vuln_class: str
    confidence: float = Field(ge=0.0, le=1.0)
    locations: list[dict] = Field(default_factory=list)
    reason: str
    evidence_refs: list[str] = Field(default_factory=list)
    remediation: Optional[str] = None
    regression_tests: list[str] = Field(default_factory=list)


class CyberEvalAgentOutput(BaseModel):
    task_id: str
    vulnerable: bool
    confidence: float = Field(ge=0.0, le=1.0)
    candidates: list[CandidateFinding] = Field(default_factory=list)

    @model_validator(mode="after")
    def max_three_candidates(self) -> "CyberEvalAgentOutput":
        if len(self.candidates) > 3:
            raise ValueError("CyberEvalAgentOutput allows maximum 3 candidates")
        return self


class CyberEvalScore(BaseModel):
    task_id: str
    verdict_score: float = Field(ge=0.0, le=1.0)
    class_score: float = Field(ge=0.0, le=1.0)
    location_score: float = Field(ge=0.0, le=1.0)
    evidence_score: float = Field(ge=0.0, le=1.0)
    remediation_score: float = Field(ge=0.0, le=1.0)
    total_score: float = Field(ge=0.0, le=100.0)
    notes: str = ""
