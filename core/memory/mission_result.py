"""
core/memory/mission_result.py — Store mission outcomes as operational memory.

After a mission runs, record:
    - eval_result (aggregate outcome)
    - bug_memory (if it failed usefully)
    - skill (if success is repeatable)
    - model_result (model used for this task_type)
    - test_map (if new file/test links discovered)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.memory.memory_item import MemoryItem, MemoryItemStatus, MemoryItemType
from core.memory.operational_memory import OperationalMemoryStore, get_operational_memory_store


@dataclass
class MissionResult:
    """Normalized mission outcome payload."""

    mission_id: str
    run_id: str
    task_type: str
    files_changed: list[str]
    tests_run: list[str]
    success: bool
    failure_reason: str = ""
    model_used: str = ""
    model_class: str = ""
    duration_ms: int = 0
    cost_estimate: float | None = None
    lessons_learned: str = ""
    created_skill: str | None = None
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "run_id": self.run_id,
            "task_type": self.task_type,
            "files_changed": self.files_changed,
            "tests_run": self.tests_run,
            "success": self.success,
            "failure_reason": self.failure_reason,
            "model_used": self.model_used,
            "model_class": self.model_class,
            "duration_ms": self.duration_ms,
            "cost_estimate": self.cost_estimate,
            "lessons_learned": self.lessons_learned,
            "created_skill": self.created_skill,
            "summary": self.summary,
        }


class MissionResultRecorder:
    """Persist a mission result into various MemoryItem types."""

    def __init__(self, store: OperationalMemoryStore | None = None) -> None:
        self.store = store or get_operational_memory_store()

    def record(self, result: MissionResult) -> dict[str, str]:
        """Store all relevant memory atoms for a mission outcome."""
        created: dict[str, str] = {}

        # 1. eval_result
        eval_item = self._eval_result(result)
        created["eval_result"] = self.store.add(eval_item)

        # 2. model_result
        if result.model_used:
            model_item = self._model_result(result)
            created["model_result"] = self.store.add(model_item)

        # 3. bug_memory on failure
        if not result.success and result.failure_reason:
            bug_item = self._bug_memory(result)
            created["bug_memory"] = self.store.add(bug_item)

        # 4. skill on repeatable success
        if result.success and result.created_skill:
            skill_item = self._skill(result)
            created["skill"] = self.store.add(skill_item)

        # 5. test_map if we ran tests
        if result.tests_run and result.files_changed:
            test_map = self._test_map(result)
            if test_map:
                created["test_map"] = self.store.add(test_map)

        return created

    def _eval_result(self, result: MissionResult) -> MemoryItem:
        return MemoryItem(
            type=MemoryItemType.EVAL_RESULT,
            title=f"Mission {result.mission_id} outcome",
            content=result.summary or f"Task {result.task_type} success={result.success}",
            status=MemoryItemStatus.ACTIVE,
            confidence=0.9 if result.success else 0.7,
            source="mission_result_recorder",
            related_files=result.files_changed,
            related_tests=result.tests_run,
            tags=["mission", result.task_type, "outcome"],
            metadata={
                "mission_id": result.mission_id,
                "run_id": result.run_id,
                "task_type": result.task_type,
                "success": result.success,
                "duration_ms": result.duration_ms,
                "cost_estimate": result.cost_estimate,
                "model_used": result.model_used,
                "model_class": result.model_class,
            },
        )

    def _model_result(self, result: MissionResult) -> MemoryItem:
        return MemoryItem(
            type=MemoryItemType.MODEL_RESULT,
            title=f"Model {result.model_used} for {result.task_type}",
            content=(
                f"Model {result.model_used} ({result.model_class}) used for "
                f"{result.task_type}: success={result.success}, duration={result.duration_ms}ms."
            ),
            status=MemoryItemStatus.ACTIVE,
            confidence=0.7,
            source="mission_result_recorder",
            related_files=result.files_changed,
            tags=["model", result.task_type, result.model_class.lower()],
            metadata={
                "model": result.model_used,
                "model_class": result.model_class,
                "task_type": result.task_type,
                "success": result.success,
                "duration_ms": result.duration_ms,
                "cost_estimate": result.cost_estimate,
            },
        )

    def _bug_memory(self, result: MissionResult) -> MemoryItem:
        return MemoryItem(
            type=MemoryItemType.BUG_MEMORY,
            title=f"Bug in {result.task_type} mission {result.mission_id}",
            content=result.failure_reason,
            status=MemoryItemStatus.ACTIVE,
            confidence=0.75,
            source="mission_result_recorder",
            related_files=result.files_changed,
            related_tests=result.tests_run,
            tags=["bug", result.task_type, "failure"],
            metadata={
                "mission_id": result.mission_id,
                "run_id": result.run_id,
                "task_type": result.task_type,
                "failure_reason": result.failure_reason,
            },
        )

    def _skill(self, result: MissionResult) -> MemoryItem:
        return MemoryItem(
            type=MemoryItemType.SKILL,
            title=result.created_skill or f"Skill for {result.task_type}",
            content=result.lessons_learned or f"Successful pattern for {result.task_type}.",
            status=MemoryItemStatus.ACTIVE,
            confidence=0.8,
            source="mission_result_recorder",
            related_files=result.files_changed,
            related_tests=result.tests_run,
            tags=["skill", result.task_type],
            metadata={
                "mission_id": result.mission_id,
                "task_type": result.task_type,
            },
        )

    def _test_map(self, result: MissionResult) -> MemoryItem | None:
        # Build a test_map per changed source file, if tests exist.
        source_files = [f for f in result.files_changed if "test" not in f.lower()]
        if not source_files:
            return None
        return MemoryItem(
            type=MemoryItemType.TEST_MAP,
            title=f"Tests covering changes in mission {result.mission_id}",
            content=f"Source files {', '.join(source_files)} covered by tests {', '.join(result.tests_run)}.",
            status=MemoryItemStatus.ACTIVE,
            confidence=0.7,
            source="mission_result_recorder",
            related_files=source_files,
            related_tests=result.tests_run,
            tags=["test_map", result.task_type],
            metadata={
                "mission_id": result.mission_id,
                "test_count": len(result.tests_run),
            },
        )
