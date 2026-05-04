"""
JARVIS — Knowledge Ingestion Filter
=======================================
Controls what gets stored in knowledge memory to avoid noise.

Called from mission_system.complete() and the intelligence hooks.
Filters out:
- Trivial missions (info_query with < 2 steps)
- Duplicate strategies (same type + agents + tools within 24h)
- Failed missions with no useful error signal

Prioritizes:
- Novel successful strategies (new tool/agent combos)
- Missions with high plan complexity that succeeded
- Failures with identifiable error patterns

Feature flag: JARVIS_KNOWLEDGE_INGESTION=1 (default ON when knowledge_memory exists)
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger("jarvis.knowledge_ingestion")

# Recent ingestions for dedup (bounded, in-memory)
_recent_ingestions: list[dict] = []
_MAX_RECENT = 200
_DEDUP_WINDOW_S = 86400  # 24h


def should_ingest(
    mission_type: str,
    success: bool,
    agents_used: list[str],
    tools_used: list[str],
    plan_steps: int,
    complexity: str,
    error_category: str = "",
    duration_s: float = 0.0,
) -> tuple[bool, str]:
    """
    Decide whether this mission outcome should be ingested into knowledge memory.

    Returns:
        (should_ingest: bool, reason: str)
    """
    # Filter 1: Trivial missions
    if mission_type in ("info_query", "compare_query") and plan_steps < 2:
        return False, "trivial_query"

    # Filter 2: Dedup — same type+agents+tools within 24h
    now = time.time()
    sig = f"{mission_type}:{','.join(sorted(agents_used))}:{','.join(sorted(tools_used))}"
    cutoff = now - _DEDUP_WINDOW_S

    for recent in _recent_ingestions:
        if recent["sig"] == sig and recent["ts"] > cutoff:
            return False, "duplicate_within_24h"

    # Filter 3: Failed without useful signal
    if not success and not error_category and plan_steps < 2:
        return False, "uninformative_failure"

    # Prioritize: successful complex missions
    if success and (complexity in ("medium", "high") or plan_steps >= 3):
        _record_ingestion(sig, now)
        return True, "successful_complex_mission"

    # Prioritize: failures with identifiable patterns
    if not success and error_category:
        _record_ingestion(sig, now)
        return True, "informative_failure"

    # Prioritize: novel agent/tool combos
    if success and len(agents_used) >= 2:
        _record_ingestion(sig, now)
        return True, "novel_strategy"

    # Default: ingest if successful
    if success:
        _record_ingestion(sig, now)
        return True, "standard_success"

    return False, "filtered_out"


def _record_ingestion(sig: str, ts: float):
    global _recent_ingestions
    _recent_ingestions.append({"sig": sig, "ts": ts})
    if len(_recent_ingestions) > _MAX_RECENT:
        _recent_ingestions = _recent_ingestions[-_MAX_RECENT:]


def ingest_mission_outcome(
    mission_id: str,
    goal: str,
    mission_type: str,
    success: bool,
    agents_used: list[str],
    tools_used: list[str],
    plan_steps: int = 0,
    complexity: str = "medium",
    error_category: str = "",
    duration_s: float = 0.0,
) -> dict:
    """
    Ingest a mission outcome into knowledge memory if it passes filters.

    Returns:
        {"ingested": bool, "reason": str}
    """
    should, reason = should_ingest(
        mission_type, success, agents_used, tools_used,
        plan_steps, complexity, error_category, duration_s,
    )

    if not should:
        logger.debug("knowledge_ingestion_filtered", mission=mission_id, reason=reason)
        return {"ingested": False, "reason": reason}

    # Ingest into knowledge_memory
    try:
        from core.knowledge_memory import get_knowledge_memory
        km = get_knowledge_memory()
        km.store_if_useful(
            goal=goal[:300],
            mission_type=mission_type,
            agents_used=agents_used,
            tools_used=tools_used,
            success=success,
            mission_id=mission_id,
        )
        logger.info(
            "knowledge_ingested",
            mission=mission_id,
            type=mission_type,
            reason=reason,
        )
        return {"ingested": True, "reason": reason}
    except ImportError:
        logger.debug("knowledge_memory_not_available")
        return {"ingested": False, "reason": "knowledge_memory_unavailable"}
    except Exception as e:
        logger.debug("knowledge_ingestion_err", err=str(e)[:60])
        return {"ingested": False, "reason": f"error: {str(e)[:60]}"}
