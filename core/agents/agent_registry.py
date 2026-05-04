"""
core/agents/agent_registry.py — Multi-Agent Coordination Registry.

Extends existing role_definitions with:
- Inter-agent messaging protocol
- Task routing based on role + performance
- Agent availability tracking
- Coordination history for auditability

Does NOT replace agent_factory.py — works alongside it.
"""
from __future__ import annotations

import time
import uuid
import structlog
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum

from core.agents.role_definitions import (
    ROLE_DEFINITIONS,
)

log = structlog.get_logger("jarvis.agent_registry")


# ── Agent Message Protocol ───────────────────────────────────────────────────

class MessagePriority(str, Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass
class AgentMessage:
    """Inter-agent communication envelope."""
    message_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    sender: str = ""
    receiver: str = ""
    task: str = ""
    context: dict = field(default_factory=dict)
    priority: MessagePriority = MessagePriority.NORMAL
    timestamp: float = field(default_factory=time.time)
    reply_to: str = ""          # message_id of parent
    status: str = "pending"     # pending, delivered, completed, failed
    result: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "message_id": self.message_id,
            "sender": self.sender,
            "receiver": self.receiver,
            "task": self.task[:200],
            "priority": self.priority.value,
            "status": self.status,
            "timestamp": self.timestamp,
        }


# ── Agent Status ─────────────────────────────────────────────────────────────

@dataclass
class AgentStatus:
    """Runtime status of a registered agent."""
    agent_name: str
    role: str
    available: bool = True
    current_task: str = ""
    tasks_completed: int = 0
    tasks_failed: int = 0
    total_latency_ms: float = 0
    last_active: float = 0
    error_streak: int = 0

    @property
    def success_rate(self) -> float:
        total = self.tasks_completed + self.tasks_failed
        return self.tasks_completed / total if total > 0 else 1.0

    @property
    def avg_latency_ms(self) -> float:
        total = self.tasks_completed + self.tasks_failed
        return self.total_latency_ms / total if total > 0 else 0

    def to_dict(self) -> dict:
        return {
            "agent": self.agent_name,
            "role": self.role,
            "available": self.available,
            "current_task": self.current_task[:60],
            "success_rate": round(self.success_rate, 3),
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "tasks_completed": self.tasks_completed,
            "tasks_failed": self.tasks_failed,
        }


# ── Agent Registry ───────────────────────────────────────────────────────────

MAX_ERROR_STREAK = 3  # After 3 consecutive failures, mark unavailable
COOLDOWN_SECONDS = 300  # 5min cooldown after streak


class AgentRegistry:
    """Multi-agent coordination registry with messaging and performance tracking."""

    def __init__(self):
        self._agents: dict[str, AgentStatus] = {}
        self._messages: list[AgentMessage] = []
        self._max_message_history = 500
        self._init_from_roles()

    def _init_from_roles(self):
        """Bootstrap agent registry from existing role definitions."""
        for role_name, role_def in ROLE_DEFINITIONS.items():
            for agent_name in role_def.assigned_agents:
                self._agents[agent_name] = AgentStatus(
                    agent_name=agent_name,
                    role=role_name,
                )
        log.info("agent_registry_initialized", count=len(self._agents))

    # ── Agent Management ─────────────────────────────────────────

    def register(self, agent_name: str, role: str = "operator") -> None:
        """Register a new agent (or update existing)."""
        if agent_name not in self._agents:
            self._agents[agent_name] = AgentStatus(agent_name=agent_name, role=role)
            log.info("agent_registered", agent=agent_name, role=role)

    def get_agent(self, name: str) -> Optional[AgentStatus]:
        return self._agents.get(name)

    def list_agents(self, role: str = "", available_only: bool = False) -> list[AgentStatus]:
        agents = list(self._agents.values())
        if role:
            agents = [a for a in agents if a.role == role]
        if available_only:
            agents = [a for a in agents if a.available]
        return agents

    # ── Task Routing ─────────────────────────────────────────────

    def best_agent_for_role(self, role: str) -> Optional[str]:
        """Select the best available agent for a role based on performance."""
        candidates = self.list_agents(role=role, available_only=True)
        if not candidates:
            # Fall back to unavailable agents (cooldown might have expired)
            candidates = self.list_agents(role=role)
            for c in candidates:
                if not c.available and c.last_active > 0:
                    elapsed = time.time() - c.last_active
                    if elapsed > COOLDOWN_SECONDS:
                        c.available = True
                        c.error_streak = 0
            candidates = [c for c in candidates if c.available]

        if not candidates:
            return None

        # Score: success_rate * 0.5 + (1 - latency_norm) * 0.3 + recency * 0.2
        now = time.time()
        scored = []
        for c in candidates:
            sr = c.success_rate
            latency_norm = min(1.0, c.avg_latency_ms / 10000)
            latency_score = 1.0 - latency_norm
            recency = min(1.0, (now - c.last_active) / 3600) if c.last_active else 0.5
            score = sr * 0.5 + latency_score * 0.3 + (1.0 - recency) * 0.2
            scored.append((score, c.agent_name))

        scored.sort(key=lambda x: -x[0])
        return scored[0][1]

    def route_task(self, task: str, required_role: str = "",
                   priority: MessagePriority = MessagePriority.NORMAL,
                   context: dict | None = None,
                   sender: str = "orchestrator") -> Optional[AgentMessage]:
        """Route a task to the best available agent. Returns the message or None."""
        role = required_role or self._infer_role(task)
        agent = self.best_agent_for_role(role)

        if not agent:
            log.warning("no_agent_available", role=role, task=task[:60])
            return None

        msg = AgentMessage(
            sender=sender,
            receiver=agent,
            task=task,
            context=context or {},
            priority=priority,
        )
        self._deliver(msg)
        return msg

    def _infer_role(self, task: str) -> str:
        """Simple keyword-based role inference for tasks."""
        t = task.lower()
        if any(kw in t for kw in ("plan", "decompose", "design", "architect")):
            return "planner"
        if any(kw in t for kw in ("research", "search", "find", "gather", "look up")):
            return "researcher"
        if any(kw in t for kw in ("review", "check", "evaluate", "assess")):
            return "critic"
        if any(kw in t for kw in ("approve", "validate", "verify", "quality")):
            return "reviewer"
        if any(kw in t for kw in ("store", "remember", "memory", "forget", "prune")):
            return "memory_curator"
        return "operator"

    # ── Messaging ────────────────────────────────────────────────

    def _deliver(self, msg: AgentMessage) -> None:
        """Record message delivery."""
        msg.status = "delivered"
        self._messages.append(msg)
        if len(self._messages) > self._max_message_history:
            self._messages = self._messages[-self._max_message_history:]

        agent = self._agents.get(msg.receiver)
        if agent:
            agent.current_task = msg.task[:100]

        log.debug("message_delivered",
                  sender=msg.sender, receiver=msg.receiver,
                  priority=msg.priority.value, task=msg.task[:40])

    def send_message(self, sender: str, receiver: str, task: str,
                     context: dict | None = None,
                     priority: MessagePriority = MessagePriority.NORMAL) -> AgentMessage:
        """Send a direct message between agents."""
        msg = AgentMessage(
            sender=sender, receiver=receiver, task=task,
            context=context or {}, priority=priority,
        )
        self._deliver(msg)
        return msg

    def complete_message(self, message_id: str, result: dict | None = None,
                         success: bool = True) -> None:
        """Mark a message/task as completed and update agent stats."""
        for msg in reversed(self._messages):
            if msg.message_id == message_id:
                msg.status = "completed" if success else "failed"
                msg.result = result or {}
                agent = self._agents.get(msg.receiver)
                if agent:
                    agent.current_task = ""
                    agent.last_active = time.time()
                    latency = (time.time() - msg.timestamp) * 1000
                    agent.total_latency_ms += latency
                    if success:
                        agent.tasks_completed += 1
                        agent.error_streak = 0
                    else:
                        agent.tasks_failed += 1
                        agent.error_streak += 1
                        if agent.error_streak >= MAX_ERROR_STREAK:
                            agent.available = False
                            log.warning("agent_disabled_streak",
                                        agent=agent.agent_name,
                                        streak=agent.error_streak)
                return

    def get_messages(self, agent: str = "", limit: int = 20) -> list[dict]:
        """Get recent messages, optionally filtered by agent."""
        msgs = self._messages
        if agent:
            msgs = [m for m in msgs if m.sender == agent or m.receiver == agent]
        return [m.to_dict() for m in msgs[-limit:]]

    # ── Diagnostics ──────────────────────────────────────────────

    def stats(self) -> dict:
        """Registry statistics for dashboard."""
        agents = list(self._agents.values())
        available = sum(1 for a in agents if a.available)
        total_tasks = sum(a.tasks_completed + a.tasks_failed for a in agents)
        total_success = sum(a.tasks_completed for a in agents)

        by_role: dict[str, int] = {}
        for a in agents:
            by_role[a.role] = by_role.get(a.role, 0) + 1

        return {
            "total_agents": len(agents),
            "available": available,
            "total_tasks": total_tasks,
            "overall_success_rate": round(total_success / total_tasks, 3) if total_tasks else 1.0,
            "by_role": by_role,
            "message_count": len(self._messages),
            "agents": [a.to_dict() for a in sorted(agents, key=lambda x: -x.success_rate)[:10]],
        }


# ── Singleton ────────────────────────────────────────────────────────────────

_registry: AgentRegistry | None = None

def get_agent_registry() -> AgentRegistry:
    global _registry
    if _registry is None:
        _registry = AgentRegistry()
    return _registry
