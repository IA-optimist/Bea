"""
BEA MAX — Learning API Routes
Exposes LearningLoop and ImprovementMemory data over HTTP.

Routes:
    GET /api/v2/learning/report                  — weekly report (all agents)
    GET /api/v2/learning/agents/{name}/stats     — per-agent improvement stats
    GET /api/v2/learning/agents/{name}/feedback  — top feedback entries
    GET /api/v2/learning/global_lessons          — cross-agent failure patterns
"""
from __future__ import annotations

from typing import Optional

import structlog
from fastapi import Depends, APIRouter, Header, Query
from api._deps import _check_auth

log = structlog.get_logger(__name__)


def _auth(x_bea_token: str | None = Header(None),
          authorization: str | None = Header(None)):
    _check_auth(x_bea_token, authorization)



router = APIRouter(prefix="/api/v2/learning", tags=["learning"], dependencies=[Depends(_auth)])

_API_TOKEN = __import__("os").getenv("BEA_API_TOKEN", "")


# ── Weekly report ─────────────────────────────────────────────

@router.get("/report")
async def weekly_report(x_bea_token: Optional[str] = Header(None)):
    """
    Full learning report: per-agent avg scores, improvement rates,
    top recurring issues, cross-agent patterns, and escalation list.
    """
    try:
        from core.learning_loop import get_learning_loop
        report = await get_learning_loop().generate_weekly_report()
        return {"ok": True, "data": report}
    except Exception as e:
        log.error("learning_report_endpoint_failed", err=str(e)[:120])
        return {"ok": False, "error": str(e)}


# ── Per-agent stats ───────────────────────────────────────────

@router.get("/agents/{agent_name}/stats")
async def agent_stats(
    agent_name:     str,
    x_bea_token: Optional[str] = Header(None),
):
    """
    Improvement statistics for a single agent:
    avg_score_before, avg_score_after, avg_delta, improvement_rate, total_tasks.
    Also returns should_escalate flag.
    """
    try:
        from core.improvement_memory import get_improvement_memory
        from core.learning_loop import get_learning_loop
        mem   = get_improvement_memory()
        stats = await mem.get_agent_stats(agent_name)
        loop  = get_learning_loop()
        return {"ok": True, "data": {
            **stats,
            "should_escalate": loop.should_escalate(agent_name, stats),
        }}
    except Exception as e:
        log.error("agent_stats_endpoint_failed", agent=agent_name, err=str(e)[:120])
        return {"ok": False, "error": str(e)}


# ── Per-agent top feedback ────────────────────────────────────

@router.get("/agents/{agent_name}/feedback")
async def agent_feedback(
    agent_name:     str,
    limit:          int            = Query(5, ge=1, le=20),
    x_bea_token: Optional[str]  = Header(None),
):
    """
    Top improvement feedback entries for an agent, sorted by score delta desc.
    Includes the formatted system-prompt addon that will be injected.
    """
    try:
        from core.improvement_memory import get_improvement_memory
        from core.learning_loop import get_learning_loop
        mem     = get_improvement_memory()
        top     = await mem.get_top_feedback(agent_name, limit=limit)
        loop    = get_learning_loop()
        loop.invalidate_cache(agent_name)   # force fresh addon
        addon   = await loop.get_agent_system_prompt_addon(agent_name)
        return {"ok": True, "data": {
            "agent_name":  agent_name,
            "top_feedback": top,
            "prompt_addon": addon,
        }}
    except Exception as e:
        log.error("agent_feedback_endpoint_failed", agent=agent_name, err=str(e)[:120])
        return {"ok": False, "error": str(e)}


# ── Global lessons ────────────────────────────────────────────

@router.get("/global_lessons")
async def global_lessons(
    limit:          int           = Query(10, ge=1, le=50),
    x_bea_token: Optional[str] = Header(None),
):
    """
    Cross-agent failure patterns: most common recurring issue keywords
    extracted from all recorded feedback, with agent attribution.
    """
    try:
        from core.learning_loop import get_learning_loop
        lessons = await get_learning_loop().get_global_lessons(limit=limit)
        return {"ok": True, "data": {"lessons": lessons, "total": len(lessons)}}
    except Exception as e:
        log.error("global_lessons_endpoint_failed", err=str(e)[:120])
        return {"ok": False, "error": str(e)}
