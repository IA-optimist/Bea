"""
BEA MAX — LearningLoop
Autonomous self-improvement: past critic feedback injected into future agent prompts.

Key idea:
    Every agent invocation calls get_agent_system_prompt_addon(name).
    The addon is a formatted [LEARNED FROM EXPERIENCE] block built from
    ImprovementMemory.get_top_feedback(). It's cached per-agent (TTL = 5 min)
    to avoid a DB hit on every single agent call.

Usage:
    loop = get_learning_loop()
    addon = await loop.get_agent_system_prompt_addon("coder-agent")
    # Returns "" if nothing learned yet; silently if DB unavailable.

    if loop.should_escalate("coder-agent", stats):
        ...   # alert human reviewer

    report  = await loop.generate_weekly_report()
    lessons = await loop.get_global_lessons(limit=5)
"""
from __future__ import annotations

import asyncio
import re
import time
from collections import Counter

import structlog

log = structlog.get_logger(__name__)

_CACHE_TTL_S        = 300      # 5 min per-agent cache
_ESCALATION_MIN_N   = 10       # min tasks before escalation check
_ESCALATION_RATE    = 0.3      # improvement_rate threshold
_LESSON_STOP_WORDS  = frozenset({
    "the", "a", "an", "is", "it", "in", "of", "to", "and", "or",
    "that", "this", "for", "was", "are", "be", "with", "has", "have",
    "output", "agent", "task", "response", "result", "more", "should",
    "not", "but", "if", "too", "very", "on", "at", "by", "from",
})


class LearningLoop:
    """
    Coordinates agent self-improvement via ImprovementMemory.
    Thread-safe: all mutable state protected by asyncio.Lock.
    """

    def __init__(self) -> None:
        self._lock   = asyncio.Lock()
        # agent_name → (addon_str, expires_at)
        self._cache: dict[str, tuple[str, float]] = {}

    # ── Prompt addon ──────────────────────────────────────────

    async def get_agent_system_prompt_addon(self, agent_name: str) -> str:
        """
        Returns a [LEARNED FROM EXPERIENCE] block (or "" if nothing available).
        Cached per agent for _CACHE_TTL_S to avoid repeated DB hits.
        Silently returns "" on any error.
        """
        try:
            async with self._lock:
                cached = self._cache.get(agent_name)
                if cached and time.time() < cached[1]:
                    return cached[0]

            addon = await self._build_addon(agent_name)

            async with self._lock:
                self._cache[agent_name] = (addon, time.time() + _CACHE_TTL_S)

            return addon
        except Exception as e:
            log.debug("learning_loop_addon_failed", agent=agent_name, err=str(e)[:80])
            return ""

    def invalidate_cache(self, agent_name: str | None = None) -> None:
        """Force cache refresh on next call. Pass None to clear all."""
        if agent_name:
            self._cache.pop(agent_name, None)
        else:
            self._cache.clear()

    # ── Escalation ────────────────────────────────────────────

    def should_escalate(
        self,
        agent_name: str,
        stats:      dict | None = None,
    ) -> bool:
        """
        Returns True if the agent has 10+ tasks recorded but improvement_rate < 0.3.
        Pass pre-fetched stats dict to avoid a second DB call; otherwise returns False
        (caller should fetch stats first with ImprovementMemory.get_agent_stats()).
        """
        if not stats:
            return False
        total = stats.get("total_tasks", 0)
        rate  = stats.get("improvement_rate", 1.0)
        return total >= _ESCALATION_MIN_N and rate < _ESCALATION_RATE

    # ── Weekly report ─────────────────────────────────────────

    async def generate_weekly_report(self) -> dict:
        """
        Aggregated summary of all agents' learning progress.
        Returns dict with agents stats, global lessons, and escalation list.
        """
        try:
            from core.improvement_memory import get_improvement_memory
            mem    = get_improvement_memory()
            agents = await mem.list_agents()
        except Exception as e:
            log.warning("learning_report_failed", err=str(e)[:80])
            return {"error": str(e), "agents": {}, "global_lessons": [], "escalations": []}

        agent_rows: dict[str, dict] = {}
        escalations: list[str]      = []

        for name in agents:
            try:
                stats = await mem.get_agent_stats(name)
                top   = await mem.get_top_feedback(name, limit=3)
                top_issues = [r.get("feedback", "")[:80] for r in top if r.get("feedback")]
                agent_rows[name] = {
                    "avg_score_before": stats.get("avg_score_before", 0),
                    "avg_score_after":  stats.get("avg_score_after",  0),
                    "avg_delta":        stats.get("avg_delta",        0),
                    "improvement_rate": stats.get("improvement_rate", 0),
                    "total_tasks":      stats.get("total_tasks",      0),
                    "top_issues":       top_issues,
                }
                if self.should_escalate(name, stats):
                    escalations.append(name)
            except Exception as e:
                log.debug("weekly_report_agent_failed", agent=name, err=str(e)[:80])

        lessons = await self.get_global_lessons(limit=5)

        return {
            "generated_at":  time.time(),
            "agent_count":   len(agent_rows),
            "agents":        agent_rows,
            "global_lessons": lessons,
            "escalations":   escalations,
        }

    # ── Global lessons ────────────────────────────────────────

    async def get_global_lessons(self, limit: int = 5) -> list[dict]:
        """
        Cross-agent pattern detection: finds the most common failure themes
        by doing keyword frequency analysis over all feedback text.

        Returns list of {"pattern", "count", "agents"}.
        """
        try:
            from core.improvement_memory import get_improvement_memory
            mem    = get_improvement_memory()
            agents = await mem.list_agents()
        except Exception as e:
            log.debug("global_lessons_failed", err=str(e)[:80])
            return []

        # Collect all feedback strings per keyword
        kw_agents: dict[str, set[str]] = {}
        kw_count:  Counter             = Counter()

        for name in agents:
            try:
                records = await mem.recent(name, limit=50)
            except Exception:
                log.debug("swallowed_exception", exc_info=True)
                continue
            for rec in records:
                feedback = rec.get("feedback", "") or ""
                if not feedback:
                    continue
                words = re.findall(r"[a-z]{4,}", feedback.lower())
                for w in words:
                    if w not in _LESSON_STOP_WORDS:
                        kw_count[w] += 1
                        kw_agents.setdefault(w, set()).add(name)

        lessons = []
        for kw, count in kw_count.most_common(limit):
            lessons.append({
                "pattern": kw,
                "count":   count,
                "agents":  sorted(kw_agents.get(kw, set())),
            })
        return lessons

    # ── Internals ─────────────────────────────────────────────

    async def _build_addon(self, agent_name: str) -> str:
        """Fetch top feedback from DB and format as prompt block."""
        from core.improvement_memory import get_improvement_memory
        mem = get_improvement_memory()

        # Ensure table exists (no-op after first call)
        await mem.ensure_table()

        top = await mem.get_top_feedback(agent_name, limit=3)
        if not top:
            return ""

        lines = ["[LEARNED FROM EXPERIENCE]"]
        for i, rec in enumerate(top, 1):
            feedback = (rec.get("feedback") or "").strip()
            if not feedback:
                continue
            before = rec.get("score_before", 0)
            after  = rec.get("score_after",  0)
            delta  = after - before
            lines.append(
                f"  {i}. {feedback} "
                f"(improved score: {before:.1f} -> {after:.1f}, +{delta:.1f})"
            )

        if len(lines) == 1:   # only header, no real entries
            return ""

        lines.append("[Apply these lessons to improve your current response.]")
        return "\n".join(lines)


# ── Singleton ─────────────────────────────────────────────────

_loop: LearningLoop | None = None


def get_learning_loop() -> LearningLoop:
    global _loop
    if _loop is None:
        _loop = LearningLoop()
    return _loop
