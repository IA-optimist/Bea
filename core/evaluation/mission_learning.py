"""
core/evaluation/mission_learning.py — Turn a mission report into useful memories.

After a mission, learn_from_mission_report() creates:
    - eval_result (always)
    - model_result (always, if model info present)
    - bug_memory (on failure / needs_fix)
    - skill (on success)
    - test_map (if files and tests exist)
    - risk (if sensitive files or risks detected)

Includes simple deduplication so the same lesson is not stored 50 times.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.evaluation.mission_report_parser import MissionLearningInput
from core.evaluation.model_router import ModelRouter
from core.memory.memory_item import MemoryItem, MemoryItemStatus, MemoryItemType
from core.memory.operational_memory import OperationalMemoryStore, get_operational_memory_store


_PROTECTED_PATHS: frozenset[str] = frozenset({
    "auth", "security", "kernel", "self_improvement",
    "api/routes", "core/policy", "config/settings",
})


def _is_protected(path: str) -> bool:
    lp = path.lower()
    return any(p in lp for p in _PROTECTED_PATHS)


@dataclass
class LearningResult:
    """Result of learning from one mission report."""

    mission_id: str
    created_memory_ids: list[str] = field(default_factory=list)
    updated_memory_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "created": self.created_memory_ids,
            "updated": self.updated_memory_ids,
            "warnings": self.warnings,
            "errors": self.errors,
        }


class MissionLearner:
    """Learn from a normalized mission report."""

    def __init__(self, store: OperationalMemoryStore | None = None) -> None:
        self.store = store or get_operational_memory_store()
        self.router = ModelRouter(store=self.store)

    def learn(self, inp: MissionLearningInput) -> LearningResult:
        """Create/update memories from a mission report."""
        result = LearningResult(mission_id=inp.mission_id)
        result.warnings.extend(inp.warnings)

        try:
            # 1. eval_result
            mid = self._create_or_update(
                item=self._eval_result(inp),
                dedup_keys=["type", "title"],
            )
            result.created_memory_ids.append(mid)

            # 2. model_result
            if inp.model_used:
                mid = self._create_or_update(
                    item=self._model_result(inp),
                    dedup_keys=["type", "title", "mission_id"],
                )
                result.created_memory_ids.append(mid)

            # 3. bug_memory on failure / needs_fix
            if not inp.success or inp.status.lower() in {"needs_fix", "needs fix"}:
                if inp.failure_reason or not inp.success:
                    mid = self._create_or_update(
                        item=self._bug_memory(inp),
                        dedup_keys=["type", "content"],
                    )
                    result.created_memory_ids.append(mid)

            # 4. skill on success
            if inp.success and inp.lessons_learned:
                mid = self._create_or_update(
                    item=self._skill(inp),
                    dedup_keys=["type", "title"],
                )
                result.created_memory_ids.append(mid)

            # 5. test_map
            if inp.files_changed and inp.tests_run:
                test_map = self._test_map(inp)
                if test_map:
                    mid = self._create_or_update(
                        item=test_map,
                        dedup_keys=["type", "related_files"],
                    )
                    result.created_memory_ids.append(mid)

            # 6. risk for sensitive files or explicit risks
            if inp.risks_detected or any(_is_protected(f) for f in inp.files_changed):
                for risk in self._risks(inp):
                    mid = self._create_or_update(
                        item=risk,
                        dedup_keys=["type", "content"],
                    )
                    result.created_memory_ids.append(mid)
        except Exception as exc:
            result.errors.append(str(exc)[:200])

        return result

    def _create_or_update(
        self,
        item: MemoryItem,
        dedup_keys: list[str],
    ) -> str:
        """Store item, updating an existing one if a duplicate is found."""
        existing = self._find_duplicate(item, dedup_keys)
        if existing:
            existing.confidence = min(1.0, existing.confidence + 0.05)
            existing.updated_at = time.time()
            existing.metadata["occurrence_count"] = existing.metadata.get("occurrence_count", 1) + 1
            self.store.add(existing)
            return existing.id
        self.store.add(item)
        return item.id

    def _find_duplicate(
        self,
        item: MemoryItem,
        dedup_keys: list[str],
    ) -> MemoryItem | None:
        """Simple deduplication: same type + matching key values."""
        # Fast path: search same type and first file/tag, then score candidates.
        query_files = item.related_files[:1] or item.related_tests[:1]
        candidates = self.store.search(
            type=item.type,
            related_files=query_files if query_files else None,
            limit=20,
        )
        if not candidates:
            candidates = self.store.search(type=item.type, limit=20)

        for candidate in candidates:
            if self._matches(item, candidate, dedup_keys):
                return candidate
        return None

    def _matches(
        self,
        item: MemoryItem,
        candidate: MemoryItem,
        dedup_keys: list[str],
    ) -> bool:
        for key in dedup_keys:
            if key == "type":
                if item.type != candidate.type:
                    return False
            elif key == "title":
                if self._slug(item.title) != self._slug(candidate.title):
                    return False
            elif key == "content":
                if self._slug(item.content) != self._slug(candidate.content):
                    return False
            elif key == "related_files":
                if set(item.related_files) != set(candidate.related_files):
                    return False
            elif key == "mission_id":
                if item.metadata.get("mission_id") != candidate.metadata.get("mission_id"):
                    return False
        return True

    @staticmethod
    def _slug(value: str) -> str:
        return " ".join(value.lower().split())[:120]

    def _eval_result(self, inp: MissionLearningInput) -> MemoryItem:
        return MemoryItem(
            type=MemoryItemType.EVAL_RESULT,
            title=f"Mission {inp.mission_id or 'unknown'}: {inp.title or inp.task_type}",
            content=f"Status={inp.status}, success={inp.success}, model={inp.model_used}.",
            status=MemoryItemStatus.ACTIVE,
            confidence=0.9 if inp.success else 0.7,
            source="mission_learning",
            related_files=inp.files_changed,
            related_tests=inp.tests_run,
            tags=["mission", inp.task_type, "outcome"],
            metadata={
                "mission_id": inp.mission_id,
                "task_type": inp.task_type,
                "success": inp.success,
                "duration_ms": inp.duration_ms,
                "cost_estimate": inp.cost_estimate,
                "model_used": inp.model_used,
                "model_class": inp.model_class,
            },
        )

    def _model_result(self, inp: MissionLearningInput) -> MemoryItem:
        return MemoryItem(
            type=MemoryItemType.MODEL_RESULT,
            title=f"{inp.model_used} on {inp.task_type}",
            content=(
                f"Model {inp.model_used} ({inp.model_class}) for {inp.task_type}: "
                f"success={inp.success}, duration={inp.duration_ms}ms."
            ),
            status=MemoryItemStatus.ACTIVE,
            confidence=0.7,
            source="mission_learning",
            related_files=inp.files_changed,
            tags=["model", inp.task_type, inp.model_class.lower()],
            metadata={
                "mission_id": inp.mission_id,
                "model": inp.model_used,
                "model_class": inp.model_class,
                "task_type": inp.task_type,
                "success": inp.success,
                "duration_ms": inp.duration_ms,
                "cost_estimate": inp.cost_estimate,
            },
        )

    def _bug_memory(self, inp: MissionLearningInput) -> MemoryItem:
        reason = inp.failure_reason or f"Mission {inp.mission_id} failed."
        return MemoryItem(
            type=MemoryItemType.BUG_MEMORY,
            title=f"Bug in {inp.task_type} mission {inp.mission_id}",
            content=reason,
            status=MemoryItemStatus.ACTIVE,
            confidence=0.75,
            source="mission_learning",
            related_files=inp.files_changed,
            related_tests=inp.tests_run,
            tags=["bug", inp.task_type, "failure"],
            metadata={
                "mission_id": inp.mission_id,
                "task_type": inp.task_type,
            },
        )

    def _skill(self, inp: MissionLearningInput) -> MemoryItem:
        title = f"Skill: {inp.task_type}"
        content = inp.lessons_learned
        # Try to extract a short title from first sentence
        first_sentence = content.split(".")[0]
        if len(first_sentence) < 80:
            title = f"Skill: {first_sentence}"
        return MemoryItem(
            type=MemoryItemType.SKILL,
            title=title,
            content=content,
            status=MemoryItemStatus.ACTIVE,
            confidence=0.8,
            source="mission_learning",
            related_files=inp.files_changed,
            related_tests=inp.tests_run,
            tags=["skill", inp.task_type],
            metadata={
                "mission_id": inp.mission_id,
                "task_type": inp.task_type,
            },
        )

    def _test_map(self, inp: MissionLearningInput) -> MemoryItem | None:
        source_files = [f for f in inp.files_changed if "test" not in f.lower()]
        if not source_files:
            return None
        return MemoryItem(
            type=MemoryItemType.TEST_MAP,
            title=f"Tests for changes in mission {inp.mission_id}",
            content=f"Files {', '.join(source_files)} tested by {', '.join(inp.tests_run)}.",
            status=MemoryItemStatus.ACTIVE,
            confidence=0.7,
            source="mission_learning",
            related_files=source_files,
            related_tests=inp.tests_run,
            tags=["test_map", inp.task_type],
            metadata={
                "mission_id": inp.mission_id,
                "test_count": len(inp.tests_run),
            },
        )

    def _risks(self, inp: MissionLearningInput) -> list[MemoryItem]:
        risks: list[MemoryItem] = []
        # Explicit risks
        for risk_text in inp.risks_detected:
            risks.append(MemoryItem(
                type=MemoryItemType.RISK,
                title=f"Risk in mission {inp.mission_id}",
                content=risk_text,
                status=MemoryItemStatus.DANGEROUS,
                confidence=0.85,
                source="mission_learning",
                related_files=inp.files_changed,
                tags=["risk", inp.task_type],
                metadata={"mission_id": inp.mission_id, "task_type": inp.task_type},
            ))
        # Auto-detect protected files
        protected = [f for f in inp.files_changed if _is_protected(f)]
        if protected:
            risks.append(MemoryItem(
                type=MemoryItemType.RISK,
                title=f"Protected files touched by mission {inp.mission_id}",
                content=f"Modified protected files: {', '.join(protected)}.",
                status=MemoryItemStatus.DANGEROUS,
                confidence=0.9,
                source="mission_learning",
                related_files=protected,
                tags=["risk", "protected", inp.task_type],
                metadata={"mission_id": inp.mission_id, "task_type": inp.task_type},
            ))
        return risks


def learn_from_mission_report(
    report: str | Path | dict[str, Any] | MissionLearningInput,
    store: OperationalMemoryStore | None = None,
) -> LearningResult:
    """Convenience entry point: parse a report and learn from it."""
    if isinstance(report, MissionLearningInput):
        inp = report
    else:
        from core.evaluation.mission_report_parser import MissionReportParser
        inp = MissionReportParser().parse(report)
    learner = MissionLearner(store=store)
    return learner.learn(inp)
