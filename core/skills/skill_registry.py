"""
core/skills/skill_registry.py — Persistent skill storage.

Uses JSONL file storage (consistent with MemoryFacade pattern).
One JSONL file = append-friendly, grep-friendly, no DB dependency.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Optional

import structlog

from core.skills.skill_models import Skill

log = structlog.get_logger("skills.registry")

_DEFAULT_PATH = "workspace/skills.jsonl"


class SkillRegistry:
    """
    Persistent skill store backed by a JSONL file.

    Thread-safe. Loads all skills into memory on init for fast search.
    Appends to file on write. Periodic compaction optional.
    """

    def __init__(self, path: str = _DEFAULT_PATH):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._skills: dict[str, Skill] = {}
        self._load()

    # ── Persistence ──────────────────────────────────────────────

    def _load(self) -> None:
        """Load all skills from JSONL into memory."""
        if not self._path.exists():
            return
        loaded = 0
        with open(self._path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    skill = Skill.from_dict(d)
                    self._skills[skill.skill_id] = skill
                    loaded += 1
                except Exception as e:
                    log.debug("skill_load_skip", err=str(e)[:60])
        if loaded:
            log.info("skills_loaded", count=loaded)

    def _append(self, skill: Skill) -> None:
        """Append one skill to the JSONL file."""
        with open(self._path, "a") as f:
            f.write(json.dumps(skill.to_dict(), ensure_ascii=False) + "\n")

    def _rewrite(self) -> None:
        """Rewrite the full JSONL file (for updates/deletes)."""
        with open(self._path, "w") as f:
            for skill in self._skills.values():
                f.write(json.dumps(skill.to_dict(), ensure_ascii=False) + "\n")

    # ── CRUD ─────────────────────────────────────────────────────

    def add(self, skill: Skill) -> str:
        """Add a new skill. Returns skill_id."""
        with self._lock:
            self._skills[skill.skill_id] = skill
            self._append(skill)
        log.info("skill_created",
                 id=skill.skill_id, name=skill.name,
                 problem_type=skill.problem_type,
                 confidence=skill.confidence)
        return skill.skill_id

    def update(self, skill: Skill) -> None:
        """Update an existing skill and rewrite storage."""
        skill.updated_at = time.time()
        with self._lock:
            self._skills[skill.skill_id] = skill
            self._rewrite()
        log.info("skill_updated", id=skill.skill_id, name=skill.name)

    def get(self, skill_id: str) -> Optional[Skill]:
        return self._skills.get(skill_id)

    def all(self) -> list[Skill]:
        return list(self._skills.values())

    def count(self) -> int:
        return len(self._skills)

    def delete(self, skill_id: str) -> bool:
        with self._lock:
            if skill_id in self._skills:
                del self._skills[skill_id]
                self._rewrite()
                log.info("skill_deleted", id=skill_id)
                return True
        return False

    def find_by_tags(self, tags: list[str], limit: int = 5) -> list[Skill]:
        """Find skills matching any of the given tags."""
        tag_set = set(t.lower() for t in tags)
        scored = []
        for skill in self._skills.values():
            skill_tags = set(t.lower() for t in skill.tags)
            overlap = len(tag_set & skill_tags)
            if overlap > 0:
                scored.append((overlap, skill))
        scored.sort(key=lambda x: (-x[0], -x[1].confidence))
        return [s for _, s in scored[:limit]]

    def find_by_problem_type(self, problem_type: str) -> list[Skill]:
        return [s for s in self._skills.values()
                if s.problem_type == problem_type]
