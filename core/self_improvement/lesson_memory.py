"""
core/self_improvement/lesson_memory.py
=======================================
Canonical location for Lesson and LessonMemory.

Extracted from core/self_improvement_loop.py (Part 7 — LESSON MEMORY).
The old import path `from core.self_improvement_loop import LessonMemory`
remains valid via a re-export shim in self_improvement_loop.py.

Preferred import:
    from core.self_improvement.lesson_memory import Lesson, LessonMemory
    from core.self_improvement import LessonMemory           # also valid (re-exported)
"""
from __future__ import annotations

import structlog
log = structlog.get_logger(__name__)

import json
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Lesson:
    """Stored outcome of an improvement cycle."""
    task_id: str
    problem: str
    fix_strategy: str
    files_changed: list[str]
    result: str            # success, failure, rejected
    score: float           # 0-1
    lessons_learned: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id, "problem": self.problem,
            "strategy": self.fix_strategy, "files": self.files_changed,
            "result": self.result, "score": self.score,
            "lessons": self.lessons_learned, "timestamp": self.timestamp,
        }


class LessonMemory:
    """Persistent memory of improvement outcomes."""

    def __init__(self, persist_path: Path | None = None):
        self._path = persist_path or Path("workspace/improvement_lessons.json")
        self._lessons: list[Lesson] = []
        self._load()

    def store(self, lesson: Lesson) -> None:
        self._lessons.append(lesson)
        if len(self._lessons) > 500:
            self._lessons = self._lessons[-300:]
        self._save()

    def search(self, problem_keywords: str, limit: int = 5) -> list[Lesson]:
        """Search lessons by keyword matching."""
        keywords = problem_keywords.lower().split()
        scored = []
        for lesson in self._lessons:
            text = f"{lesson.problem} {lesson.fix_strategy} {lesson.lessons_learned}".lower()
            score = sum(1 for kw in keywords if kw in text)
            if score > 0:
                scored.append((score, lesson))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [le for _, le in scored[:limit]]

    def get_success_rate(self, strategy: str) -> float:
        relevant = [le for le in self._lessons if le.fix_strategy == strategy]
        if not relevant:
            return 0.5  # no data → neutral
        return sum(1 for le in relevant if le.result == "success") / len(relevant)

    def get_all(self) -> list[dict]:
        return [le.to_dict() for le in self._lessons]

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps([le.to_dict() for le in self._lessons], indent=2, default=str),
                encoding="utf-8")
        except Exception as _exc:
            log.warning("swallowed_exception", action="lesson_memory_1", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    def _load(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                for d in data:
                    self._lessons.append(Lesson(
                        task_id=d.get("task_id", ""),
                        problem=d.get("problem", ""),
                        fix_strategy=d.get("strategy", ""),
                        files_changed=d.get("files", []),
                        result=d.get("result", ""),
                        score=d.get("score", 0),
                        lessons_learned=d.get("lessons", ""),
                        timestamp=d.get("timestamp", 0),
                    ))
            except Exception as _exc:
                log.warning("swallowed_exception", action="lesson_memory_2", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
