"""
JARVIS MAX — AgentComm (Agent Communication Bus)
Structured inter-agent communication for multi-agent sessions.

Architecture:
    AgentComm
    ├── _outputs[session_id][agent_name]  → deque(maxlen=100) of AgentOutput
    ├── _mailboxes[(session_id, to_agent)] → list[asyncio.Queue]  (pub/sub)
    └── _lock: asyncio.Lock

Public API:
    bus = get_agent_comm()

    # Publish a result
    await bus.publish(session_id, "coder-agent", "result", {"code": "..."})

    # Read another agent's latest output
    out = bus.get_agent_output(session_id, "security-agent")

    # Send a direct message
    await bus.send_to_agent("planner-agent", "coder-agent", session_id, "Refactor X")

    # Subscribe to messages
    q = bus.subscribe(session_id, "coder-agent")
    msg = await q.get()
    bus.unsubscribe(session_id, "coder-agent", q)

    # Merged context (all agents in session)
    ctx = bus.get_session_context(session_id)
"""
from __future__ import annotations

import asyncio
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

import structlog
_silent_log = __import__("structlog").get_logger(__name__)

log = structlog.get_logger(__name__)

_MAX_OUTPUTS_PER_AGENT = 100   # bounded per (session, agent)
_MAX_MAILBOX_SIZE      = 256   # asyncio.Queue maxsize per subscriber


@dataclass
class AgentOutput:
    """Structured output published by an agent."""
    output_id:   str   = field(default_factory=lambda: str(uuid.uuid4()))
    session_id:  str   = ""
    agent_name:  str   = ""
    output_type: str   = "result"   # "result" | "thought" | "error" | "context" | "plan"
    payload:     Any   = None
    timestamp:   float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "output_id":   self.output_id,
            "session_id":  self.session_id,
            "agent_name":  self.agent_name,
            "output_type": self.output_type,
            "payload":     self.payload,
            "timestamp":   self.timestamp,
        }


@dataclass
class AgentMessage:
    """Direct message between two agents."""
    message_id:  str   = field(default_factory=lambda: str(uuid.uuid4()))
    session_id:  str   = ""
    from_agent:  str   = ""
    to_agent:    str   = ""
    output_type: str   = "message"
    payload:     Any   = None
    timestamp:   float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "message_id":  self.message_id,
            "session_id":  self.session_id,
            "from_agent":  self.from_agent,
            "to_agent":    self.to_agent,
            "output_type": self.output_type,
            "payload":     self.payload,
            "timestamp":   self.timestamp,
        }


class AgentComm:
    """
    In-process agent communication bus.
    All state is bounded (deques with maxlen) to prevent memory leaks.
    Thread-safe via asyncio.Lock.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        # session_id → agent_name → deque[AgentOutput]
        self._outputs: dict[str, dict[str, deque]] = defaultdict(
            lambda: defaultdict(lambda: deque(maxlen=_MAX_OUTPUTS_PER_AGENT))
        )
        # (session_id, to_agent) → list[asyncio.Queue]
        self._mailboxes: dict[tuple[str, str], list[asyncio.Queue]] = defaultdict(list)

    # ── Publish ───────────────────────────────────────────────

    async def publish(
        self,
        session_id:  str,
        agent_name:  str,
        output_type: str = "result",
        payload:     Any = None,
    ) -> AgentOutput:
        """
        Publish a structured output from an agent.
        Stored in bounded deque; all subscribers on (session, agent_name) notified.
        """
        out = AgentOutput(
            session_id  = session_id,
            agent_name  = agent_name,
            output_type = output_type,
            payload     = payload,
        )
        async with self._lock:
            self._outputs[session_id][agent_name].append(out)
            queues = list(self._mailboxes.get((session_id, agent_name), []))

        for q in queues:
            try:
                q.put_nowait(out)
            except asyncio.QueueFull:
                pass   # slow consumer — drop

        log.debug("agent_comm_published",
                  session=session_id, agent=agent_name, type=output_type)
        return out

    # ── Read latest output ────────────────────────────────────

    def get_agent_output(
        self,
        session_id: str,
        agent_name: str,
        output_type: str | None = None,
    ) -> AgentOutput | None:
        """
        Returns the most recent output from agent_name in session_id.
        Optionally filtered by output_type.
        """
        buf = self._outputs.get(session_id, {}).get(agent_name)
        if not buf:
            return None
        if output_type is None:
            return buf[-1]
        for out in reversed(buf):
            if out.output_type == output_type:
                return out
        return None

    def list_agent_outputs(
        self,
        session_id:  str,
        agent_name:  str,
        output_type: str | None = None,
        limit:       int        = 20,
    ) -> list[AgentOutput]:
        """Returns up to `limit` recent outputs from an agent."""
        buf = self._outputs.get(session_id, {}).get(agent_name)
        if not buf:
            return []
        items = list(buf)
        if output_type:
            items = [o for o in items if o.output_type == output_type]
        return items[-limit:]

    # ── Session context ───────────────────────────────────────

    def get_session_context(
        self,
        session_id:  str,
        max_per_agent: int = 3,
    ) -> dict[str, list[dict]]:
        """
        Returns a merged context dict of all agents' recent outputs in a session.

        Shape: {"coder-agent": [...], "security-agent": [...], ...}
        Callers inject this into LLM prompts for cross-agent awareness.
        """
        agents_dict = self._outputs.get(session_id, {})
        context: dict[str, list[dict]] = {}
        for agent_name, buf in agents_dict.items():
            recent = list(buf)[-max_per_agent:]
            context[agent_name] = [o.to_dict() for o in recent]
        return context

    def format_session_context(
        self,
        session_id:   str,
        max_per_agent: int = 2,
    ) -> str:
        """
        Returns a human-readable context block suitable for LLM prompt injection.
        Example:
            [security-agent] Found 2 SQL injection risks in auth.py
            [planner-agent] Plan: step 1 = audit, step 2 = fix
        """
        ctx = self.get_session_context(session_id, max_per_agent=max_per_agent)
        if not ctx:
            return ""
        lines = ["=== Agent Context ==="]
        for agent, outputs in ctx.items():
            for o in outputs:
                payload_str = str(o.get("payload", ""))[:200]
                lines.append(f"[{agent}] ({o.get('output_type','?')}) {payload_str}")
        return "\n".join(lines)

    # ── Direct messaging (pub/sub) ────────────────────────────

    async def send_to_agent(
        self,
        from_agent:  str,
        to_agent:    str,
        session_id:  str,
        message:     Any,
        output_type: str = "message",
    ) -> AgentMessage:
        """
        Send a direct async message from one agent to another.
        All subscribers on (session_id, to_agent) receive the message.
        Also stored in _outputs so get_session_context() picks it up.
        """
        msg = AgentMessage(
            session_id  = session_id,
            from_agent  = from_agent,
            to_agent    = to_agent,
            output_type = output_type,
            payload     = {"from": from_agent, "message": message},
        )
        # Store as agent output for context accumulation
        out = AgentOutput(
            session_id  = session_id,
            agent_name  = from_agent,
            output_type = f"msg_to_{to_agent}",
            payload     = {"to": to_agent, "message": message},
        )
        async with self._lock:
            self._outputs[session_id][from_agent].append(out)
            queues = list(self._mailboxes.get((session_id, to_agent), []))

        for q in queues:
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                _silent_log.debug("suppressed_exception", src='agent_comm.py')

        log.debug("agent_comm_message_sent",
                  session=session_id, frm=from_agent, to=to_agent)
        return msg

    # ── Subscribe / Unsubscribe ───────────────────────────────

    async def subscribe(self, session_id: str, agent_name: str) -> asyncio.Queue:
        """
        Subscribe to outputs/messages directed at agent_name in session_id.
        Returns an asyncio.Queue; call unsubscribe() when done.
        """
        q: asyncio.Queue = asyncio.Queue(maxsize=_MAX_MAILBOX_SIZE)
        async with self._lock:
            self._mailboxes[(session_id, agent_name)].append(q)
        return q

    async def unsubscribe(
        self, session_id: str, agent_name: str, q: asyncio.Queue
    ) -> None:
        async with self._lock:
            try:
                self._mailboxes[(session_id, agent_name)].remove(q)
            except ValueError:
                _silent_log.debug("suppressed_exception", src='agent_comm.py')

    # ── Cleanup ───────────────────────────────────────────────

    async def clear_session(self, session_id: str) -> None:
        """Remove all outputs and mailboxes for a session (call on mission complete)."""
        async with self._lock:
            self._outputs.pop(session_id, None)
            stale = [k for k in self._mailboxes if k[0] == session_id]
            for k in stale:
                del self._mailboxes[k]
        log.debug("agent_comm_session_cleared", session=session_id)

    def session_agents(self, session_id: str) -> list[str]:
        """Returns list of agent names that have published in this session."""
        return list(self._outputs.get(session_id, {}).keys())


# ── Singleton ─────────────────────────────────────────────────

_comm: AgentComm | None = None


def get_agent_comm() -> AgentComm:
    global _comm
    if _comm is None:
        _comm = AgentComm()
    return _comm
