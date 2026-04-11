"""
api/routes/cognitive_events.py — Cognitive Event Journal API.

Read-only endpoints for inspecting the event journal.
Auth-protected. No secret leakage.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from api._deps import require_auth
_silent_log = __import__("structlog").get_logger(__name__)

router = APIRouter(prefix="/api/v3/cognitive-events", tags=["cognitive-events"])


@router.get("")
async def get_journal_stats(_user: dict = Depends(require_auth)):
    """Journal statistics."""
    from core.cognitive_events.store import get_journal
    return {"ok": True, "data": get_journal().stats()}


@router.get("/recent")
async def get_recent_events(
    limit: int = Query(50, ge=1, le=500),
    domain: str | None = Query(None, pattern="^(runtime|lab|system)$"),
    event_type: str | None = None,
    mission_id: str | None = None,
    severity: str | None = Query(None, pattern="^(debug|info|warning|error|critical)$"),
    source: str | None = None,
    _user: dict = Depends(require_auth),
):
    """Query recent events with filters."""
    from core.cognitive_events.store import get_journal
    from core.cognitive_events.types import EventDomain, EventType, EventSeverity

    kwargs: dict = {"limit": limit}
    if domain:
        kwargs["domain"] = EventDomain(domain)
    if event_type:
        try:
            kwargs["event_type"] = EventType(event_type)
        except ValueError:
            _silent_log.debug("suppressed_exception", src='cognitive_events.py')
    if mission_id:
        kwargs["mission_id"] = mission_id
    if severity:
        kwargs["severity_min"] = EventSeverity(severity)
    if source:
        kwargs["source"] = source

    return {"ok": True, "data": get_journal().get_recent(**kwargs)}


@router.get("/mission/{mission_id}")
async def get_mission_timeline(
    mission_id: str,
    _user: dict = Depends(require_auth),
):
    """Full event timeline for a specific mission."""
    from core.cognitive_events.store import get_journal
    return {"ok": True, "data": get_journal().get_mission_timeline(mission_id)}


@router.get("/runtime")
async def get_runtime_events(
    limit: int = Query(50, ge=1, le=200),
    _user: dict = Depends(require_auth),
):
    """Runtime-domain events only."""
    from core.cognitive_events.store import get_journal
    return {"ok": True, "data": get_journal().get_runtime_events(limit)}


@router.get("/lab")
async def get_lab_events(
    limit: int = Query(50, ge=1, le=200),
    _user: dict = Depends(require_auth),
):
    """Lab/sandbox-domain events only."""
    from core.cognitive_events.store import get_journal
    return {"ok": True, "data": get_journal().get_lab_events(limit)}


@router.get("/boundary")
async def get_boundary(_user: dict = Depends(require_auth)):
    """Runtime/lab boundary definition."""
    from core.cognitive_events.boundary import get_boundary_summary
    return {"ok": True, "data": get_boundary_summary()}


@router.get("/replay")
async def replay_events(
    since: float = Query(0.0, description="Unix timestamp to replay from"),
    domain: str | None = Query(None, pattern="^(runtime|lab|system)$"),
    _user: dict = Depends(require_auth),
):
    """Replay events since a timestamp (oldest first)."""
    from core.cognitive_events.store import get_journal
    from core.cognitive_events.types import EventDomain
    d = EventDomain(domain) if domain else None
    return {"ok": True, "data": get_journal().replay(since_ts=since, domain=d)}


@router.get("/explain/{mission_id}")
async def explain_mission(
    mission_id: str,
    _user: dict = Depends(require_auth),
):
    """Human-readable explanation of what happened in a mission."""
    from core.cognitive_events.store import get_journal
    return {"ok": True, "data": get_journal().explain_mission(mission_id)}


@router.get("/approvals/{mission_id}")
async def get_mission_approvals(
    mission_id: str,
    _user: dict = Depends(require_auth),
):
    """All approval-related events for a mission."""
    from core.cognitive_events.store import get_journal
    return {"ok": True, "data": get_journal().get_mission_approvals(mission_id)}


@router.get("/patches")
async def get_patch_events(
    patch_id: str | None = None,
    _user: dict = Depends(require_auth),
):
    """Lab patch events, optionally filtered by patch_id."""
    from core.cognitive_events.store import get_journal
    return {"ok": True, "data": get_journal().get_patch_events(patch_id or "")}


@router.get("/degraded")
async def get_degraded_events(
    limit: int = Query(50, ge=1, le=200),
    _user: dict = Depends(require_auth),
):
    """Recent degradation and failure events."""
    from core.cognitive_events.store import get_journal
    return {"ok": True, "data": get_journal().get_degraded_events(limit)}
