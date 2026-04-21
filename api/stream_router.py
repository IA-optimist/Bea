"""
JARVIS MAX — Streaming Router
SSE (Server-Sent Events) endpoints for clients that can't use WebSocket.

Routes:
    GET /api/v2/stream/{session_id}       — all events for a session
    GET /api/v2/tasks/{task_id}/progress  — task progress stream

SSE format (per WHATWG spec):
    data: {"type":"...", ...}\n\n

Clients that support EventSource can consume these directly.
On reconnect, replay buffer is sent first (last MAX_REPLAY events).
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import AsyncGenerator

import structlog
from typing import Optional
from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

log = structlog.get_logger(__name__)

router = APIRouter()

_KEEPALIVE_INTERVAL = 15.0    # seconds between SSE keepalives
_STREAM_TIMEOUT     = 300.0   # max seconds a stream stays open


def _sse(payload: dict) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(payload)}\n\n"


def _sse_comment(msg: str) -> str:
    """SSE keepalive / comment line."""
    return f": {msg}\n\n"


# ── Session stream ─────────────────────────────────────────────

def _check_sse_auth(token: str | None):
    import os
    api_token = os.getenv("JARVIS_API_TOKEN", "")
    if not api_token:
        return  # No token configured
    from api.token_utils import strip_bearer
    clean = strip_bearer(token) if token else None
    if clean and clean == api_token:
        return
    raise HTTPException(status_code=401, detail="Unauthorized")


@router.get("/api/v2/stream/{session_id}", response_class=StreamingResponse)
async def session_stream(
    session_id: str,
    request:    Request,
    replay:     bool = Query(True, description="Replay buffered events on connect"),
    x_jarvis_token: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
):
    _check_sse_auth(x_jarvis_token or authorization)
    """
    SSE stream for a specific session.
    Replays recent buffered events then streams live events as they arrive.
    """
    from api.ws_hub import get_hub
    hub = get_hub()

    async def generator() -> AsyncGenerator[str, None]:
        q   = hub.subscribe_session_sse(session_id)
        try:
            # Replay history
            if replay:
                for evt in hub.get_session_history(session_id):
                    yield _sse(evt)

            # Yield connect handshake
            yield _sse({"type": "connected", "session_id": session_id, "ts": time.time()})

            deadline = time.monotonic() + _STREAM_TIMEOUT
            while time.monotonic() < deadline:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=_KEEPALIVE_INTERVAL)
                    yield _sse(event)
                except asyncio.TimeoutError:
                    yield _sse_comment("keepalive")
        finally:
            hub.unsubscribe_session_sse(session_id, q)
            log.debug("sse_session_stream_closed", session_id=session_id)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":     "no-cache",
            "X-Accel-Buffering": "no",
            "Connection":        "keep-alive",
        },
    )


# ── Task progress stream ───────────────────────────────────────

@router.get("/api/v2/tasks/{task_id}/progress", response_class=StreamingResponse)
async def task_progress_stream(
    task_id: str,
    request: Request,
    replay:  bool = Query(True, description="Replay buffered progress events on connect"),
    x_jarvis_token: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
):
    _check_sse_auth(x_jarvis_token or authorization)
    """
    SSE progress stream for a background task.
    Streams task_progress events (percent 0→100) until DONE or FAILED.
    Auto-closes when task reaches a terminal state.
    """
    from api.ws_hub import get_hub
    from core.task_queue import get_core_task_queue

    hub   = get_hub()
    queue = get_core_task_queue()

    async def generator() -> AsyncGenerator[str, None]:
        # Check task exists
        task = await queue.get(task_id)
        if task is None:
            yield _sse({"type": "error", "message": f"Task {task_id!r} not found"})
            return

        q = hub.subscribe_task_sse(task_id)
        try:
            # Replay history
            if replay:
                for evt in hub.get_task_history(task_id):
                    yield _sse(evt)

            # Yield connect event
            yield _sse({
                "type":    "connected",
                "task_id": task_id,
                "state":   task.state.value,
                "ts":      time.time(),
            })

            # If already terminal, close immediately
            if task.is_terminal():
                yield _sse({
                    "type":    "task_complete",
                    "task_id": task_id,
                    "state":   task.state.value,
                    "result":  str(task.result)[:500] if task.result else None,
                    "error":   task.error,
                    "ts":      time.time(),
                })
                return

            deadline = time.monotonic() + _STREAM_TIMEOUT
            while time.monotonic() < deadline:
                if await request.is_disconnected():
                    break

                try:
                    event = await asyncio.wait_for(q.get(), timeout=_KEEPALIVE_INTERVAL)
                    yield _sse(event)

                    # Close stream when task finishes
                    if event.get("type") == "task_progress" and event.get("percent", 0) >= 100:
                        break
                    if event.get("type") in ("task_complete", "task_failed"):
                        break
                except asyncio.TimeoutError:
                    # Poll task state on each keepalive
                    current = await queue.get(task_id)
                    if current and current.is_terminal():
                        yield _sse({
                            "type":    "task_complete",
                            "task_id": task_id,
                            "state":   current.state.value,
                            "result":  str(current.result)[:500] if current.result else None,
                            "error":   current.error,
                            "ts":      time.time(),
                        })
                        break
                    yield _sse_comment("keepalive")
        finally:
            hub.unsubscribe_task_sse(task_id, q)
            log.debug("sse_task_stream_closed", task_id=task_id)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":     "no-cache",
            "X-Accel-Buffering": "no",
            "Connection":        "keep-alive",
        },
    )
