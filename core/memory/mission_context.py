"""
core/memory/mission_context.py — Active memory lookup before a mission starts.

Builds a structured context payload from MemoryItem:
    - relevant decisions
    - known risks
    - repo facts
    - test maps
    - bug memories
    - a short suggested_context_summary
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.memory.memory_item import MemoryItem, MemoryItemStatus, MemoryItemType
from core.memory.operational_memory import OperationalMemoryStore, get_operational_memory_store


@dataclass
class MissionContext:
    """Structured useful context for a new mission."""

    relevant_memories: list[MemoryItem] = field(default_factory=list)
    relevant_repo_facts: list[MemoryItem] = field(default_factory=list)
    relevant_decisions: list[MemoryItem] = field(default_factory=list)
    relevant_risks: list[MemoryItem] = field(default_factory=list)
    relevant_tests: list[MemoryItem] = field(default_factory=list)
    suggested_context_summary: str = ""
    model_class_hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "relevant_memories": [m.to_dict() for m in self.relevant_memories],
            "relevant_repo_facts": [m.to_dict() for m in self.relevant_repo_facts],
            "relevant_decisions": [m.to_dict() for m in self.relevant_decisions],
            "relevant_risks": [m.to_dict() for m in self.relevant_risks],
            "relevant_tests": [m.to_dict() for m in self.relevant_tests],
            "suggested_context_summary": self.suggested_context_summary,
            "model_class_hint": self.model_class_hint,
        }


class MissionContextBuilder:
    """Prepare mission context by querying operational memory."""

    def __init__(self, store: OperationalMemoryStore | None = None) -> None:
        self.store = store or get_operational_memory_store()

    def prepare(
        self,
        mission_title: str,
        mission_description: str,
        optional_files: list[str] | None = None,
        task_type: str = "",
    ) -> MissionContext:
        """
        Search memory for anything useful about this mission.

        Returns a MissionContext ranked by relevance, with obsolete/replaced
        memories deprioritized and dangerous risks surfaced explicitly.
        """
        optional_files = optional_files or []
        query = f"{mission_title} {mission_description} {task_type}"
        task_tags = self._task_tags(task_type)

        # Collect separate ranked pools
        all_memories = self.store.ranked_search(
            query=query,
            related_files=optional_files,
            tags=task_tags,
            include_obsolete=False,
            limit=15,
        )

        facts = self.store.ranked_search(
            query=query,
            type=MemoryItemType.REPO_FACT,
            related_files=optional_files,
            tags=task_tags,
            include_obsolete=False,
            limit=8,
        )

        decisions = self.store.ranked_search(
            query=query,
            type=MemoryItemType.ARCHITECTURE_DECISION,
            related_files=optional_files,
            tags=task_tags,
            include_obsolete=False,
            limit=5,
        )

        # Risks: include dangerous/active even if query match is weak
        risks = self.store.ranked_search(
            query=query,
            type=MemoryItemType.RISK,
            related_files=optional_files,
            tags=task_tags,
            include_obsolete=False,
            weights={**OperationalMemoryStore.DEFAULT_WEIGHTS, "active": 0.5, "dangerous": 1.2},
            limit=5,
        )

        tests = self.store.ranked_search(
            query=query,
            type=MemoryItemType.TEST_MAP,
            related_files=optional_files,
            tags=task_tags,
            include_obsolete=False,
            limit=5,
        )

        # Unverified fallback only if active pool is empty
        if not all_memories:
            all_memories = self.store.ranked_search(
                query=query,
                related_files=optional_files,
                tags=task_tags,
                include_obsolete=True,
                limit=10,
            )

        ctx = MissionContext()
        ctx.relevant_memories = [item for item, _ in all_memories]
        ctx.relevant_repo_facts = [item for item, _ in facts]
        ctx.relevant_decisions = [item for item, _ in decisions]
        ctx.relevant_risks = [item for item, _ in risks]
        ctx.relevant_tests = [item for item, _ in tests]
        ctx.suggested_context_summary = self._summarize(
            mission_title, ctx, task_type, optional_files,
        )
        ctx.model_class_hint = self._model_class_hint(ctx, task_type)
        return ctx

    @staticmethod
    def _task_tags(task_type: str) -> list[str]:
        base = []
        tt = task_type.lower()
        if "test" in tt:
            base.append("test")
        if "api" in tt or "route" in tt:
            base.append("api")
        if "bug" in tt or "fix" in tt:
            base.append("bug")
        if "security" in tt or "patch" in tt:
            base.append("security")
        if "memory" in tt or "retrieval" in tt:
            base.append("memory")
        return base

    @staticmethod
    def _model_class_hint(ctx: MissionContext, task_type: str) -> str:
        if any(r.status == MemoryItemStatus.DANGEROUS for r in ctx.relevant_risks):
            return "STRONG_CODE_REVIEW"
        tt = task_type.lower()
        if "review" in tt or "security" in tt or "patch" in tt:
            return "STRONG_CODE_REVIEW"
        if "refactor" in tt or "bug" in tt or "complex" in tt:
            return "STRONG_REASONING"
        if "simple" in tt or "doc" in tt or "summary" in tt:
            return "SMALL_FAST"
        return "MEDIUM_TOOL_USE"

    @staticmethod
    def _summarize(
        title: str,
        ctx: MissionContext,
        task_type: str,
        optional_files: list[str],
    ) -> str:
        lines = [f"Mission: {title} (type={task_type or 'general'})"]
        if optional_files:
            lines.append(f"Files in scope: {', '.join(optional_files)}")
        if ctx.relevant_risks:
            lines.append(f"Risks: {len(ctx.relevant_risks)} known risk(s).")
        if ctx.relevant_decisions:
            lines.append(f"Decisions: {len(ctx.relevant_decisions)} active ADR(s).")
        if ctx.relevant_tests:
            lines.append(f"Tests: {len(ctx.relevant_tests)} related test map(s).")
        if ctx.relevant_repo_facts:
            lines.append(f"Repo facts: {len(ctx.relevant_repo_facts)} relevant fact(s).")
        return " ".join(lines)
