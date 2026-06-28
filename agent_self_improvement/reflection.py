"""
agent_self_improvement/reflection.py — ReflectionAgent: self-monitoring loop.

Reads metrics from the memory store and produces ImprovementIssues
when patterns of failure are detected.  Never patches code directly.
Consults kernel/improvement/gate.py before creating any issue.
"""
from __future__ import annotations

from typing import Any
import structlog

from agent_memory.models import MemoryType, StructuredMemory
from agent_memory.store import AgentMemoryStore
from agent_self_improvement.improvement_issues import (
    ImprovementIssue,
    ImprovementIssueFactory,
    ImprovementKind,
)

log = structlog.get_logger("bea.self_improve.reflection")

_FAILURE_THRESHOLD = 3   # >= N failures of same type → propose improvement
_GATE_MAX_PER_RUN = 1    # max issues created per reflection cycle


class ReflectionAgent:
    """
    Monitors agent memory for failure patterns and proposes improvements.

    Output: list[ImprovementIssue] — never code patches.
    Gate: max _GATE_MAX_PER_RUN issues per cycle.
    Kernel gate is consulted if available.
    """

    def __init__(self, store: AgentMemoryStore) -> None:
        self._store = store
        self._factory = ImprovementIssueFactory()

    def reflect(self, *, agent_id: str = "reflection") -> list[ImprovementIssue]:
        """
        Run one reflection cycle.

        Returns list of ImprovementIssue objects to be filed as GitHub issues.
        Empty list if gate blocks or no issues found.
        """
        if not self._gate_allows():
            log.info("reflection_gate_blocked", reason="kernel gate or cooldown")
            return []

        issues: list[ImprovementIssue] = []

        # Check for repeated failure patterns
        failure_memories = self._store.recall(
            memory_type=MemoryType.LESSON,
            tags=["failure"],
            min_confidence=0.5,
            limit=50,
        )
        failure_categories = self._count_failure_categories(failure_memories)
        for category, count in failure_categories.items():
            if count >= _FAILURE_THRESHOLD and len(issues) < _GATE_MAX_PER_RUN:
                kind = self._map_category_to_kind(category)
                issue = self._factory.from_failure(
                    what_failed=f"Repeated failure in '{category}' ({count}× in memory)",
                    why=f"Pattern detected by reflection agent after {count} similar failures",
                    kind=kind,
                    detected_by=f"reflection_agent:{agent_id}",
                )
                issues.append(issue)
                log.info(
                    "reflection_issue_created",
                    kind=kind.value,
                    category=category,
                    failure_count=count,
                )

        if not issues:
            log.info("reflection_no_issues", failure_memories=len(failure_memories))
        return issues

    def _gate_allows(self) -> bool:
        """Consult kernel gate if available, otherwise allow."""
        try:
            from kernel.improvement.gate import Gate
            gate = Gate()
            return gate.check()
        except Exception:
            return True  # gate unavailable → allow (fail open for reflection)

    def _count_failure_categories(self, memories: list[StructuredMemory]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for m in memories:
            # Use first line of content as category
            first_line = m.content.split("\n")[0][:40]
            counts[first_line] = counts.get(first_line, 0) + 1
        return counts

    def _map_category_to_kind(self, category: str) -> ImprovementKind:
        cat = category.lower()
        if any(w in cat for w in ("security", "auth", "injection", "xss")):
            return ImprovementKind.SECURITY
        if any(w in cat for w in ("test", "pytest", "assert")):
            return ImprovementKind.TEST
        if any(w in cat for w in ("tool", "executor", "sandbox")):
            return ImprovementKind.TOOL_USAGE
        if any(w in cat for w in ("plan", "mission", "goal")):
            return ImprovementKind.PLANNING
        if any(w in cat for w in ("perf", "slow", "timeout", "latency")):
            return ImprovementKind.PERFORMANCE
        return ImprovementKind.BUG_FIX
