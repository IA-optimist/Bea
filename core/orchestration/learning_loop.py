"""
core/orchestration/learning_loop.py — Post-mission learning loop.

After each mission completes, the learning loop:
1. Reviews the reflection verdict
2. If low confidence or retry: extracts lesson
3. Feeds lesson into memory and skills
4. Over time, Bea learns from its own failures

Inspired by Hermes Agent's skill improvement + ARC's refinement loops.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import structlog

log = structlog.get_logger("orchestration.learning")


@dataclass
class Lesson:
    mission_id: str
    goal_summary: str
    what_happened: str
    what_to_do_differently: str
    confidence: float
    created_at: float = 0.0

    def __post_init__(self):
        if not self.created_at:
            self.created_at = time.time()

    def to_dict(self) -> dict:
        return {
            "mission_id": self.mission_id,
            "goal_summary": self.goal_summary,
            "what_happened": self.what_happened,
            "what_to_do_differently": self.what_to_do_differently,
            "confidence": self.confidence,
            "created_at": self.created_at,
        }


def extract_lesson(
    mission_id: str,
    goal: str,
    result: str,
    reflection_verdict: str,
    reflection_confidence: float,
    error_class: str = "",
    retries: int = 0,
) -> Lesson | None:
    """
    Extract a lesson from a completed mission.
    Only generates lessons when something went wrong or was uncertain.
    """
    if reflection_verdict == "accept" and reflection_confidence >= 0.8:
        return None  # Nothing to learn from clean successes

    # Determine what happened
    if reflection_verdict == "empty":
        what_happened = "Mission produced no output"
        what_to_do = "Verify tool availability and input format before execution"
    elif reflection_verdict == "retry_suggested":
        what_happened = f"Result was weak (confidence={reflection_confidence})"
        what_to_do = "Try alternative approach or decompose into smaller steps"
    elif error_class and error_class != "none":
        what_happened = f"Error: {error_class}"
        if error_class == "timeout":
            what_to_do = "Increase timeout or break task into smaller chunks"
        elif error_class == "tool_not_available":
            what_to_do = "Check tool availability before planning execution"
        elif error_class == "rate_limited":
            what_to_do = "Add backoff/delay or queue for later execution"
        elif error_class == "validation_failed":
            what_to_do = "Validate input format before sending to tool"
        else:
            what_to_do = f"Handle {error_class} errors in planning phase"
    elif retries > 0:
        what_happened = f"Required {retries} retries to complete"
        what_to_do = "Investigate root cause of transient failures"
    else:
        what_happened = f"Low confidence result (confidence={reflection_confidence})"
        what_to_do = "Consider more specific goal formulation"

    # Truncate goal to summary
    goal_summary = goal[:100] + ("..." if len(goal) > 100 else "")

    lesson = Lesson(
        mission_id=mission_id,
        goal_summary=goal_summary,
        what_happened=what_happened,
        what_to_do_differently=what_to_do,
        confidence=reflection_confidence,
    )

    log.info("lesson_extracted",
             mission_id=mission_id,
             verdict=reflection_verdict,
             lesson=what_to_do[:60])

    return lesson


def store_lesson(lesson: Lesson, memory_facade=None) -> bool:
    """
    Store a lesson in memory via the facade.
    Falls back to logging if facade is unavailable.
    """
    if memory_facade is None:
        try:
            from core.memory_facade import get_memory_facade
            memory_facade = get_memory_facade()
        except Exception:
            log.info("lesson_stored_log_only", **lesson.to_dict())
            return False

    try:
        memory_facade.store_failure(
            content=f"[lesson] {lesson.goal_summary}: {lesson.what_to_do_differently}",
            error_class="lesson",
            mission_id=lesson.mission_id,
        )
        return True
    except Exception as e:
        log.debug("lesson_store_failed", err=str(e)[:60])
        return False


def find_relevant_lessons(goal: str, task_type: str = "",
                          max_results: int = 3) -> list[dict]:
    """
    Retrieve lessons relevant to a goal from the memory facade.

    Called by kernel.memory.retrieve_lessons() via registration (Pass 13).
    Searches for stored lesson entries (tagged [lesson]) and returns structured dicts.

    Returns list of dicts:
      - goal_summary:           str
      - what_to_do_differently: str
      - relevance:              float
    """
    try:
        from core.memory_facade import get_memory_facade
        facade = get_memory_facade()
        # Over-fetch then filter for lesson-tagged entries
        raw_results = facade.search(goal, top_k=max_results * 3)
        lessons = []
        for r in raw_results:
            # MemoryFacade.search() returns MemoryEntry dataclass objects, not dicts.
            # BLOC 1 fix: use attribute access (getattr) for MemoryEntry compatibility.
            if isinstance(r, dict):
                content = r.get("content", "")
                score = float(r.get("score", 0.0))
            else:
                content = getattr(r, "content", "") or ""
                score = float(getattr(r, "score", 0.0) or 0.0)
            if "[lesson]" not in content:
                continue
            # Parse "[lesson] goal_summary: what_to_do_differently"
            lesson_text = content.replace("[lesson] ", "", 1)
            parts = lesson_text.split(": ", 1)
            goal_summary = parts[0].strip() if parts else goal[:100]
            what_to_do = parts[1].strip() if len(parts) > 1 else lesson_text
            lessons.append({
                "goal_summary": goal_summary,
                "what_to_do_differently": what_to_do,
                "relevance": round(score, 3),
            })
            if len(lessons) >= max_results:
                break
        return lessons
    except Exception as e:
        log.debug("find_relevant_lessons_failed", err=str(e)[:80])
        return []
