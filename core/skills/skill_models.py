"""
core/skills/skill_models.py — Skill data model.

A Skill is a reusable procedural artifact created from a successful execution.
Stored as structured JSON, retrieved by semantic similarity or tags.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class SkillStep:
    """One step in a skill's procedure."""
    order: int
    description: str
    tool: str = ""           # tool name used, if any
    code_snippet: str = ""   # optional code/command
    notes: str = ""


@dataclass
class Skill:
    """
    A reusable procedural artifact learned from a successful mission.

    Fields kept flat and simple — serializes to JSON directly.
    """
    skill_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = ""
    description: str = ""
    problem_type: str = ""          # e.g. "api_fix", "data_analysis", "deployment"
    context: str = ""               # when this skill applies
    prerequisites: list[str] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    steps: list[SkillStep] = field(default_factory=list)
    pitfalls: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    # Quality signals
    confidence: float = 0.5         # 0.0–1.0
    risk_level: str = "low"         # low / medium / high
    use_count: int = 0
    success_count: int = 0
    last_used_at: float | None = None

    # Provenance
    source_mission_id: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["steps"] = [asdict(s) for s in self.steps]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Skill":
        steps_raw = d.pop("steps", [])
        steps: list[SkillStep] = [SkillStep(**s) if isinstance(s, dict) else s for s in steps_raw]
        return cls(steps=steps, **d)

    def text_for_search(self) -> str:
        """Concatenated text for similarity search."""
        parts = [self.name, self.description, self.problem_type, self.context]
        parts += self.tags
        parts += [s.description for s in self.steps]
        return " ".join(p for p in parts if p)

    def record_use(self, success: bool = True) -> None:
        self.use_count += 1
        if success:
            self.success_count += 1
        self.last_used_at = time.time()
        self.updated_at = time.time()
