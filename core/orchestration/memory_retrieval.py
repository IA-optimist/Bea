"""
core/orchestration/memory_retrieval.py — Pre-Planning Memory Retrieval Hook
=============================================================================
Phase 3 cognitive upgrade: memory is used BEFORE planning, not just after.

Before any non-trivial mission:
  1. Retrieve 3 most similar FAILURES  (content_type="failure")
  2. Retrieve 3 most similar SUCCESSES (content_type="mission_outcome")
  3. Summarize: what failed, what worked, what to avoid, what to reuse
  4. Inject this MissionLessons artifact into enriched_goal

Current state (before this module):
  - context_assembler.py retrieves prior_skills + relevant_memories generically
  - kernel_lessons are injected from kernel.run_cognitive_cycle() if available
  - BUT: no dedicated "failure vs success diff" artifact exists
  - No structured before-planning retrieval with explicit contrast

Design:
  - Fail-open: if memory unavailable, returns empty MissionLessons with log
  - Fast: max 3+3 items, no LLM call
  - Structured: MissionLessons is inspectable, serializable, injectable
  - Reuses existing memory_facade — no new storage backend

Status: CODE READY + WIRED (Pass 42 — Phase 3)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

log = structlog.get_logger("orchestration.memory_retrieval")


# ══════════════════════════════════════════════════════════════════════════════
# Data model
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class MissionLessons:
    """
    Pre-planning memory artifact: structured failure/success contrast.

    Available to planner via enriched_goal injection and ctx.metadata.
    """
    # Raw retrieved items
    failures:  list[dict[str, Any]] = field(default_factory=list)
    successes: list[dict[str, Any]] = field(default_factory=list)

    # Synthesized guidance
    avoid:   list[str] = field(default_factory=list)   # From failures
    reuse:   list[str] = field(default_factory=list)   # From successes
    summary: str = ""

    # Retrieval meta
    retrieval_ok: bool = True
    retrieval_error: str = ""
    failure_count:  int = 0
    success_count:  int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "failures_retrieved": len(self.failures),
            "successes_retrieved": len(self.successes),
            "avoid": self.avoid,
            "reuse": self.reuse,
            "summary": self.summary,
            "retrieval_ok": self.retrieval_ok,
            "retrieval_error": self.retrieval_error,
        }

    def to_prompt_injection(self) -> str:
        """
        Compact text for injection into enriched_goal.
        Concise — agents need signal, not noise.
        """
        if not self.retrieval_ok or (not self.avoid and not self.reuse):
            return ""

        parts = ["[MEMORY_LESSONS]"]
        if self.avoid:
            parts.append("AVOID (from past failures):")
            for item in self.avoid[:3]:
                parts.append(f"  - {item}")
        if self.reuse:
            parts.append("REUSE (from past successes):")
            for item in self.reuse[:3]:
                parts.append(f"  - {item}")
        return "\n".join(parts)

    @property
    def has_lessons(self) -> bool:
        return bool(self.avoid or self.reuse)


# ══════════════════════════════════════════════════════════════════════════════
# Retrieval function
# ══════════════════════════════════════════════════════════════════════════════

def retrieve_mission_lessons(
    goal: str,
    task_type: str = "",
    top_k: int = 3,
) -> MissionLessons:
    """
    Retrieve pre-planning lessons from memory before execution starts.

    Queries memory_facade for failures and successes relevant to the goal.
    Synthesizes a MissionLessons artifact for planner injection.

    Fail-open: always returns MissionLessons. If retrieval fails, returns
    empty lessons with retrieval_ok=False and logs the error.

    Args:
        goal      : raw mission goal
        task_type : from classifier (improves search precision)
        top_k     : max items per category (default 3)

    Returns:
        MissionLessons — always, never raises
    """
    try:
        return _retrieve(goal, task_type, top_k)
    except Exception as exc:
        log.warning(
            "memory_retrieval_failed",
            goal_preview=goal[:60],
            err=str(exc)[:120],
        )
        return MissionLessons(
            retrieval_ok=False,
            retrieval_error=str(exc)[:200],
            summary="memory retrieval unavailable (fail-open)",
        )


# Pass 43: minimum cosine-like score to consider a memory entry relevant.
# Entries below this threshold are noise — ignore rather than inject misleading lessons.
_SCORE_THRESHOLD = 0.40


def _retrieve(goal: str, task_type: str, top_k: int) -> MissionLessons:
    """Internal retrieval — may raise; caller wraps in try/except."""
    from core.memory_facade import get_memory_facade
    facade = get_memory_facade()

    # ── Retrieve failures ──────────────────────────────────────────────────
    raw_failures: list[Any] = []
    try:
        raw_failures = facade.search(goal, content_type="failure", top_k=top_k + 2)
        if not raw_failures:
            # Fallback: unfiltered search with failure keywords
            raw_failures = facade.search(
                f"failed error {goal[:40]}", top_k=top_k + 2
            )
    except Exception as fe:
        log.debug("memory_retrieval_failures_failed", err=str(fe)[:60])

    # ── Retrieve successes ─────────────────────────────────────────────────
    raw_successes: list[Any] = []
    try:
        raw_successes = facade.search(goal, content_type="mission_outcome", top_k=top_k + 2)
        if not raw_successes:
            raw_successes = facade.search(
                f"success complete done {goal[:40]}", top_k=top_k + 2
            )
    except Exception as se:
        log.debug("memory_retrieval_successes_failed", err=str(se)[:60])

    # ── Normalize to dicts ─────────────────────────────────────────────────
    all_failures  = [_normalize(e) for e in raw_failures]
    all_successes = [_normalize(e) for e in raw_successes]

    # ── Pass 43: filter by score threshold + deduplicate by content prefix ─
    failures  = _filter_and_dedup(all_failures,  threshold=_SCORE_THRESHOLD, top_k=top_k)
    successes = _filter_and_dedup(all_successes, threshold=_SCORE_THRESHOLD, top_k=top_k)

    if len(all_failures) != len(failures) or len(all_successes) != len(successes):
        log.debug("memory_retrieval_filtered",
                  raw_failures=len(all_failures), kept_failures=len(failures),
                  raw_successes=len(all_successes), kept_successes=len(successes),
                  threshold=_SCORE_THRESHOLD)

    # ── Synthesize guidance ────────────────────────────────────────────────
    avoid = _extract_avoid(failures, task_type)
    reuse = _extract_reuse(successes, task_type)
    summary = _build_summary(failures, successes, avoid, reuse, goal)

    lessons = MissionLessons(
        failures=failures,
        successes=successes,
        avoid=avoid,
        reuse=reuse,
        summary=summary,
        retrieval_ok=True,
        failure_count=len(failures),
        success_count=len(successes),
    )

    log.info(
        "memory_retrieval_complete",
        goal_preview=goal[:60],
        task_type=task_type,
        failures_retrieved=len(failures),
        successes_retrieved=len(successes),
        avoid_count=len(avoid),
        reuse_count=len(reuse),
        has_lessons=lessons.has_lessons,
    )

    return lessons


def _filter_and_dedup(
    entries: list[dict[str, Any]],
    threshold: float,
    top_k: int,
) -> list[dict[str, Any]]:
    """
    Pass 43: filter entries below score threshold and deduplicate by content prefix.
    Returns at most top_k entries, sorted by score descending.
    """
    seen_prefixes: set[str] = set()
    kept: list[dict[str, Any]] = []
    # Sort by score desc so highest-quality entries win dedup
    sorted_entries = sorted(entries, key=lambda e: e.get("score", 0.0), reverse=True)
    for entry in sorted_entries:
        score = entry.get("score", 0.0)
        if score < threshold:
            continue
        # Dedup key: first 60 chars of content (normalised)
        prefix = entry.get("content", "")[:60].lower().strip()
        if prefix in seen_prefixes:
            continue
        seen_prefixes.add(prefix)
        kept.append(entry)
        if len(kept) >= top_k:
            break
    return kept


def _normalize(entry: Any) -> dict[str, Any]:
    """Normalize a memory entry (MemoryEntry dataclass or dict) to dict."""
    if isinstance(entry, dict):
        return {
            "content": str(entry.get("content", ""))[:300],
            "score": float(entry.get("score", 0.0)),
            "content_type": str(entry.get("content_type", "")),
            "tags": entry.get("tags", []),
        }
    # MemoryEntry dataclass
    return {
        "content": str(getattr(entry, "content", ""))[:300],
        "score": float(getattr(entry, "score", 0.0)),
        "content_type": str(getattr(entry, "content_type", "")),
        "tags": getattr(entry, "tags", []),
    }


def _extract_avoid(failures: list[dict], task_type: str) -> list[str]:
    """
    Extract actionable "avoid" lessons from failure entries.
    Heuristic: first sentence or pattern in failure content.
    """
    avoid = []
    for f in failures:
        content = f.get("content", "").strip()
        if not content:
            continue
        # Take first meaningful sentence
        first_sentence = content.split(".")[0].strip()
        if len(first_sentence) > 10:
            avoid.append(first_sentence[:120])
    # Add task-type-specific defaults when no memory found
    if not avoid:
        defaults = {
            "code":       ["missing import after edit", "breaking change without test"],
            "deployment": ["deploy without health check", "no rollback plan"],
            "research":   ["unverified source cited as fact"],
        }
        avoid = defaults.get(task_type, [])
    return avoid[:3]


def _extract_reuse(successes: list[dict], task_type: str) -> list[str]:
    """
    Extract actionable "reuse" patterns from success entries.
    """
    reuse = []
    for s in successes:
        content = s.get("content", "").strip()
        if not content:
            continue
        first_sentence = content.split(".")[0].strip()
        if len(first_sentence) > 10:
            reuse.append(first_sentence[:120])
    if not reuse:
        defaults = {
            "code":       ["minimal edit targeting the specific bug"],
            "deployment": ["build + verify + deploy + health-check sequence"],
            "research":   ["primary source cross-referenced with secondary"],
        }
        reuse = defaults.get(task_type, [])
    return reuse[:3]


def _build_summary(
    failures: list[dict],
    successes: list[dict],
    avoid: list[str],
    reuse: list[str],
    goal: str,
) -> str:
    """Build a one-paragraph summary for logging."""
    parts = []
    if failures:
        parts.append(
            f"{len(failures)} similar past failure(s) found. "
            f"Avoid: {'; '.join(avoid[:2]) or 'see failure logs'}."
        )
    if successes:
        parts.append(
            f"{len(successes)} similar past success(es) found. "
            f"Reuse: {'; '.join(reuse[:2]) or 'see success logs'}."
        )
    if not parts:
        parts.append("No relevant memory found — proceeding without prior lessons.")
    return " ".join(parts)
