"""
JARVIS MAX — WebSocket Hub v2
Broadcast hub for real-time events: task progress, agent thinking, token streaming.

Architecture:
    WsHub
    ├── _system   — set[WebSocket]  : global system subscribers
    ├── _missions — dict[id, set]   : per-mission subscribers
    ├── _sessions — dict[id, set]   : per-session subscribers
    └── _tasks    — dict[id, set]   : per-task subscribers

    Per-session event buffer: deque(maxlen=MAX_BUFFER) — capped to avoid memory leak.

Usage:
    hub = get_hub()
    await hub.connect_session(session_id, ws)
    await hub.emit_agent_thinking(session_id, "PlannerAgent", "Evaluating options...")
    await hub.emit_task_progress(task_id, 50, "Processing...")
"""
from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict, deque
from typing import Any

import structlog
from fastapi import WebSocket

log = structlog.get_logger(__name__)

MAX_BUFFER = 1_000          # max events per session (addresses audit finding #3)
_SEND_TIMEOUT = 5.0         # seconds before a slow client is dropped


class WsHub:
    """
    Central broadcast hub for all WebSocket clients.
    Thread-safe via asyncio.Lock.
    """

    def __init__(self) -> None:
        self._lock     = asyncio.Lock()
        self._system:   set[WebSocket]                  = set()
        self._missions: dict[str, set[WebSocket]]       = defaultdict(set)
        self._sessions: dict[str, set[WebSocket]]       = defaultdict(set)
        self._tasks:    dict[str, set[WebSocket]]       = defaultdict(set)
        # Capped event replay buffers
        self._session_buf: dict[str, deque] = defaultdict(lambda: deque(maxlen=MAX_BUFFER))
        self._task_buf:    dict[str, deque] = defaultdict(lambda: deque(maxlen=MAX_BUFFER))
        # SSE async queues: session_id → list[asyncio.Queue]
        self._sse_sessions: dict[str, list[asyncio.Queue]] = defaultdict(list)
        self._sse_tasks:    dict[str, list[asyncio.Queue]] = defaultdict(list)

    # ── Connection management ─────────────────────────────────

    async def connect_system(self, ws: WebSocket) -> None:
        async with self._lock:
            self._system.add(ws)

    async def connect_mission(self, mission_id: str, ws: WebSocket) -> None:
        async with self._lock:
            self._missions[mission_id].add(ws)

    async def connect_session(self, session_id: str, ws: WebSocket) -> None:
        async with self._lock:
            self._sessions[session_id].add(ws)

    async def connect_task(self, task_id: str, ws: WebSocket) -> None:
        async with self._lock:
            self._tasks[task_id].add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._system.discard(ws)
            for s in self._missions.values():
                s.discard(ws)
            for s in self._sessions.values():
                s.discard(ws)
            for s in self._tasks.values():
                s.discard(ws)

    # ── SSE subscription (for stream_router) ─────────────────

    def subscribe_session_sse(self, session_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._sse_sessions[session_id].append(q)
        return q

    def unsubscribe_session_sse(self, session_id: str, q: asyncio.Queue) -> None:
        try:
            self._sse_sessions[session_id].remove(q)
        except (ValueError, KeyError):
            _silent_log.debug("suppressed_exception", src='ws_hub.py')

    def subscribe_task_sse(self, task_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._sse_tasks[task_id].append(q)
        return q

    def unsubscribe_task_sse(self, task_id: str, q: asyncio.Queue) -> None:
        try:
            self._sse_tasks[task_id].remove(q)
        except (ValueError, KeyError):
            _silent_log.debug("suppressed_exception", src='ws_hub.py')

    def get_session_history(self, session_id: str) -> list[dict]:
        return list(self._session_buf.get(session_id, []))

    def get_task_history(self, task_id: str) -> list[dict]:
        return list(self._task_buf.get(task_id, []))

    # ── Typed emit helpers ────────────────────────────────────

    async def emit_task_progress(
        self,
        task_id:  str,
        percent:  int,
        message:  str = "",
    ) -> None:
        """Emit a task progress event (0–100)."""
        payload = {
            "type":     "task_progress",
            "task_id":  task_id,
            "percent":  max(0, min(100, percent)),
            "message":  message,
            "ts":       time.time(),
        }
        self._task_buf[task_id].append(payload)
        await self._broadcast_task(task_id, payload)
        await self._push_sse(self._sse_tasks.get(task_id, []), payload)

    async def emit_agent_thinking(
        self,
        session_id: str,
        agent_name: str,
        thought:    str,
    ) -> None:
        """Emit a TAOR 'Think' step for live UI display."""
        payload = {
            "type":       "agent_thinking",
            "session_id": session_id,
            "agent":      agent_name,
            "thought":    thought,
            "ts":         time.time(),
        }
        self._session_buf[session_id].append(payload)
        await self._broadcast_session(session_id, payload)
        await self._push_sse(self._sse_sessions.get(session_id, []), payload)

    async def emit_token_stream(
        self,
        session_id: str,
        token:      str,
    ) -> None:
        """Emit a single LLM token for streaming UI."""
        payload = {
            "type":       "token_stream",
            "session_id": session_id,
            "token":      token,
            "ts":         time.time(),
        }
        # Tokens are high-frequency — don't add to replay buffer
        await self._broadcast_session(session_id, payload)
        await self._push_sse(self._sse_sessions.get(session_id, []), payload)

    async def emit_multimodal_result(
        self,
        session_id:    str,
        result_type:   str,   # "image" | "audio" | "video" | "file"
        url:           str,
        metadata:      dict | None = None,
    ) -> None:
        """Emit a multimodal result (image/audio/video URL) for rich UI."""
        payload = {
            "type":        "multimodal_result",
            "session_id":  session_id,
            "result_type": result_type,
            "url":         url,
            "metadata":    metadata or {},
            "ts":          time.time(),
        }
        self._session_buf[session_id].append(payload)
        await self._broadcast_session(session_id, payload)
        await self._push_sse(self._sse_sessions.get(session_id, []), payload)

    # ── Generic broadcast ─────────────────────────────────────

    async def broadcast_system(self, payload: dict[str, Any]) -> int:
        async with self._lock:
            targets = set(self._system)
        return await self._send_to_set(targets, payload)

    async def broadcast_mission(self, mission_id: str, payload: dict[str, Any]) -> int:
        async with self._lock:
            targets = set(self._missions.get(mission_id, set()))
        return await self._send_to_set(targets, payload)

    async def _broadcast_session(self, session_id: str, payload: dict) -> int:
        async with self._lock:
            targets = set(self._sessions.get(session_id, set()))
        return await self._send_to_set(targets, payload)

    async def _broadcast_task(self, task_id: str, payload: dict) -> int:
        async with self._lock:
            targets = set(self._tasks.get(task_id, set()))
        return await self._send_to_set(targets, payload)

    async def _send_to_set(self, targets: set[WebSocket], payload: dict) -> int:
        if not targets:
            return 0
        envelope = json.dumps(payload)
        sent = 0
        dead: list[WebSocket] = []
        for ws in targets:
            try:
                await asyncio.wait_for(ws.send_text(envelope), timeout=_SEND_TIMEOUT)
                sent += 1
            except Exception:
                dead.append(ws)
        if dead:
            asyncio.get_event_loop().create_task(self._cleanup_dead(dead))
        return sent

    async def _cleanup_dead(self, dead: list[WebSocket]) -> None:
        for ws in dead:
            await self.disconnect(ws)

    @staticmethod
    async def _push_sse(queues: list[asyncio.Queue], payload: dict) -> None:
        for q in list(queues):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass   # Slow SSE consumer — drop event rather than block


# ── Singleton ─────────────────────────────────────────────────

_hub: WsHub | None = None


def get_hub() -> WsHub:
    global _hub
    if _hub is None:
        _hub = WsHub()
    return _hub
