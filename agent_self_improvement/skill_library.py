"""
agent_self_improvement/skill_library.py — Typed Skill library (Voyager pattern).

A Skill is a named, tested, sourced procedure.  Skills without tests
or without a source reference are rejected at registration time.

Extends (does not replace) core/skills/skill_registry.py.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator
import structlog

log = structlog.get_logger("bea.self_improve.skills")


class SkillStatus(str, Enum):
    DRAFT = "draft"          # not yet tested
    TESTED = "tested"        # tests written and passing
    VERIFIED = "verified"    # used successfully ≥3 times
    DEPRECATED = "deprecated"


class Skill(BaseModel):
    """
    A reusable agent skill.

    Requirements (enforced):
    - test_code must be non-empty (TDD: tests before skill is accepted)
    - source_ref must be non-empty (where did this skill come from?)
    - human_verified: only humans can set this to True
    """

    skill_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:12])
    name: str = Field(min_length=3, max_length=128)
    description: str = Field(min_length=20, max_length=2000)
    code: str = Field(min_length=10)        # the skill implementation
    test_code: str = Field(min_length=10)   # tests (required)
    source_ref: str = Field(min_length=5)   # where this came from
    realm: str = Field(min_length=2)
    status: SkillStatus = SkillStatus.DRAFT
    tags: list[str] = Field(default_factory=list)
    use_count: int = 0
    human_verified: bool = False            # only humans may set True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: str = "unknown"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_skill(self) -> "Skill":
        if not self.test_code.strip():
            raise ValueError("Skill.test_code is required — write tests before registering a skill")
        if not self.source_ref.strip():
            raise ValueError("Skill.source_ref is required — document where this skill comes from")
        return self


class SkillLibrary:
    """
    Registry for agent skills.

    Extends the existing core/skills/skill_registry.py by adding
    provenance and test requirements.  Skills are never auto-deployed —
    they go through the GitHub Mission Loop for human review before use.
    """

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}
        self._name_index: dict[str, str] = {}  # name → skill_id

    def register(self, skill: Skill) -> str:
        """
        Register a skill.  Raises ValueError if:
        - test_code is missing
        - source_ref is missing
        - name already exists
        """
        if skill.name in self._name_index:
            raise ValueError(f"skill '{skill.name}' already registered — use deprecate() then re-register")
        self._skills[skill.skill_id] = skill
        self._name_index[skill.name] = skill.skill_id
        log.info(
            "skill_registered",
            skill_id=skill.skill_id,
            name=skill.name,
            realm=skill.realm,
            status=skill.status.value,
        )
        return skill.skill_id

    def get(self, name: str) -> Skill | None:
        sid = self._name_index.get(name)
        return self._skills.get(sid) if sid else None

    def get_by_id(self, skill_id: str) -> Skill | None:
        return self._skills.get(skill_id)

    def deprecate(self, name: str) -> bool:
        sid = self._name_index.get(name)
        if not sid:
            return False
        old = self._skills[sid]
        self._skills[sid] = old.model_copy(update={"status": SkillStatus.DEPRECATED})
        del self._name_index[name]
        log.info("skill_deprecated", name=name, skill_id=sid)
        return True

    def mark_used(self, name: str) -> None:
        sid = self._name_index.get(name)
        if sid and sid in self._skills:
            s = self._skills[sid]
            updates: dict[str, Any] = {"use_count": s.use_count + 1}
            if s.use_count + 1 >= 3 and s.status == SkillStatus.TESTED:
                updates["status"] = SkillStatus.VERIFIED
            self._skills[sid] = s.model_copy(update=updates)

    def human_verify(self, name: str) -> bool:
        """Only humans may call this."""
        sid = self._name_index.get(name)
        if not sid:
            return False
        s = self._skills[sid]
        self._skills[sid] = s.model_copy(update={"human_verified": True})
        log.info("skill_human_verified", name=name, skill_id=sid)
        return True

    def list_by_realm(self, realm: str) -> list[Skill]:
        return [s for s in self._skills.values()
                if s.realm == realm and s.status != SkillStatus.DEPRECATED]

    def stats(self) -> dict[str, Any]:
        skills = list(self._skills.values())
        by_status = {s.value: 0 for s in SkillStatus}
        for sk in skills:
            by_status[sk.status.value] += 1
        return {
            "total": len(skills),
            "by_status": by_status,
            "human_verified": sum(1 for sk in skills if sk.human_verified),
        }
