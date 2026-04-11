"""
api/routes/trace.py — Trace lifecycle endpoint.

GET /api/v1/trace/{trace_id} — retrieve all lifecycle events for a trace.
GET /api/v1/trace/mission/{mission_id} — retrieve all events for a mission.
"""
from __future__ import annotations

import logging
from typing import Optional

try:
    from fastapi import APIRouter, Depends, Header, HTTPException
except ImportError:
    APIRouter = None

from api._deps import _check_auth

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/trace", tags=["trace"])


def _auth(x_jarvis_token: Optional[str] = Header(None),
          authorization: Optional[str] = Header(None)):
    _check_auth(x_jarvis_token, authorization)


@router.get("/{trace_id}", dependencies=[Depends(_auth)])
async def get_trace(trace_id: str):
    """Retrieve all lifecycle events for a trace_id."""
    try:
        from core.observability.event_envelope import get_event_collector
        collector = get_event_collector()
        events = collector.get_trace(trace_id)
        return {
            "ok": True,
            "data": {
                "trace_id": trace_id,
                "event_count": len(events),
                "events": events,
            }
        }
    except Exception as e:
        log.error("trace_fetch_failed", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mission/{mission_id}", dependencies=[Depends(_auth)])
async def get_mission_trace(mission_id: str):
    """Retrieve all lifecycle events across traces for a mission."""
    try:
        from core.observability.event_envelope import get_event_collector
        collector = get_event_collector()
        events = collector.get_mission_trace(mission_id)

        # Also get the trace_id from mission decision_trace
        trace_id = ""
        try:
            from core.mission_system import get_mission_system
            ms = get_mission_system()
            mission = ms.get(mission_id)
            if mission:
                trace_id = getattr(mission, "decision_trace", {}).get("trace_id", "")
        except Exception:
            _silent_log.debug("suppressed_exception", src='trace.py')

        return {
            "ok": True,
            "data": {
                "mission_id": mission_id,
                "trace_id": trace_id,
                "event_count": len(events),
                "events": events,
            }
        }
    except Exception as e:
        log.error("mission_trace_fetch_failed", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail=str(e))
