"""
ContextProvider — structured knowledge injection for agents.
Fail-open: if any source is unavailable, returns partial context.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ContextBlock:
    context_summary: str = ""
    relevant_files: list[str] = field(default_factory=list)
    recent_decisions: list[dict] = field(default_factory=list)
    known_constraints: list[str] = field(default_factory=list)
    memory_entries: list[dict] = field(default_factory=list)
    agent_history: list[dict] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "context_summary": self.context_summary,
            "relevant_files": self.relevant_files,
            "recent_decisions": self.recent_decisions,
            "known_constraints": self.known_constraints,
            "memory_entries": self.memory_entries,
            "agent_history": self.agent_history,
            "timestamp": self.timestamp,
        }

    def to_prompt_text(self) -> str:
        """Returns a formatted string suitable for prepending to agent prompts."""
        parts = ["=== AGENT CONTEXT ==="]

        if self.context_summary:
            parts.append(f"Summary: {self.context_summary}")

        if self.known_constraints:
            parts.append("\nConstraints:")
            for c in self.known_constraints:
                parts.append(f"  - {c}")

        if self.recent_decisions:
            parts.append("\nRecent Decisions:")
            for d in self.recent_decisions[:5]:
                desc = d.get("description") or d.get("input") or str(d)[:120]
                parts.append(f"  - {desc}")

        if self.memory_entries:
            parts.append("\nRelevant Memory:")
            for m in self.memory_entries[:5]:
                text = m.get("text") or m.get("summary") or str(m)[:120]
                parts.append(f"  - {text}")

        if self.agent_history:
            parts.append("\nAgent History:")
            for h in self.agent_history[:3]:
                parts.append(f"  - {str(h)[:120]}")

        parts.append("=== END CONTEXT ===")
        return "\n".join(parts)


class ContextProvider:
    """
    Aggregates context from multiple sources:
    - MemoryBus (working + episodic layers)
    - workspace/decision_replay.json
    - workspace/missions.json (recent missions)
    - known_constraints from config/settings.py
    """

    def __init__(self, workspace_dir: str = "workspace"):
        self.workspace_dir = workspace_dir
        self._memory_bus = None

    def _get_memory_bus(self):
        """Lazy import — fail-open if not available."""
        if self._memory_bus is None:
            try:
                from memory.memory_bus import MemoryBus
                self._memory_bus = MemoryBus.get_instance()
            except Exception:
                _silent_log.debug("suppressed_exception", src='context_provider.py')
        return self._memory_bus

    def _read_json_file(self, path: str) -> Any:
        """Read and parse a JSON file. Returns None on any failure."""
        try:
            full = Path(self.workspace_dir) / path
            if full.exists():
                with open(full, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            _silent_log.debug("suppressed_exception", src='context_provider.py')
        return None

    def _load_decisions(self, max_entries: int) -> list[dict]:
        """Try to read workspace/decision_replay.json."""
        data = self._read_json_file("decision_replay.json")
        if not data:
            return []
        try:
            if isinstance(data, list):
                entries = data
            elif isinstance(data, dict):
                entries = data.get("events") or data.get("decisions") or list(data.values())
            else:
                return []
            result = []
            for e in entries[-max_entries:]:
                if isinstance(e, dict):
                    result.append(e)
            return result
        except Exception:
            return []

    def _load_recent_missions(self, n: int = 5) -> list[dict]:
        """Try to read workspace/missions.json."""
        data = self._read_json_file("missions.json")
        if not data:
            return []
        try:
            if isinstance(data, list):
                missions = data
            elif isinstance(data, dict):
                missions = list(data.values())
            else:
                return []
            return [m for m in missions if isinstance(m, dict)][-n:]
        except Exception:
            return []

    def _load_constraints(self) -> list[str]:
        """Try to extract constraint fields from config/settings.py Settings class."""
        constraints = []
        try:
            from config.settings import get_settings
            s = get_settings()
            # Extract string/bool fields that look like constraints
            for attr in dir(s):
                if attr.startswith("_"):
                    continue
                val = getattr(s, attr, None)
                if isinstance(val, bool) and val:
                    constraints.append(f"{attr}=True")
                elif isinstance(val, str) and attr.endswith(("_mode", "_policy", "_level")):
                    constraints.append(f"{attr}={val}")
        except Exception:
            _silent_log.debug("suppressed_exception", src='context_provider.py')
        return constraints[:10]

    def _build_summary(
        self,
        agent_id: str,
        mission_id: str,
        decisions: list[dict],
        missions: list[dict],
        memory_entries: list[dict],
    ) -> str:
        """Build a 2-3 sentence narrative summary."""
        parts = []

        if agent_id:
            parts.append(f"Agent '{agent_id}' is operating")
            if mission_id:
                parts.append(f" on mission '{mission_id}'")
            parts.append(".")

        if decisions:
            last = decisions[-1]
            mode = last.get("mode") or last.get("type") or "unknown"
            parts.append(f" Last decision was mode='{mode}'.")

        if missions:
            last_m = missions[-1]
            title = last_m.get("title") or last_m.get("name") or last_m.get("id") or "unnamed"
            parts.append(f" Most recent mission: '{str(title)[:60]}'.")

        if not parts:
            return "No prior context available."

        return "".join(parts)

    def get_context(
        self,
        agent_id: str,
        mission_id: str = "",
        max_entries: int = 10,
    ) -> ContextBlock:
        """Build a ContextBlock for the given agent. Never raises."""
        try:
            decisions = self._load_decisions(max_entries)
        except Exception:
            decisions = []

        try:
            missions = self._load_recent_missions()
        except Exception:
            missions = []

        try:
            constraints = self._load_constraints()
        except Exception:
            constraints = []

        memory_entries: list[dict] = []
        try:
            bus = self._get_memory_bus()
            if bus and hasattr(bus, "get_recent"):
                memory_entries = bus.get_recent("working_memory", n=max_entries)
        except Exception:
            _silent_log.debug("suppressed_exception", src='context_provider.py')

        agent_history: list[dict] = []
        try:
            bus = self._get_memory_bus()
            if bus and hasattr(bus, "build_agent_context"):
                ctx_str = bus.build_agent_context(agent_id, mission_id=mission_id)
                if ctx_str:
                    agent_history = [{"text": ctx_str}]
        except Exception:
            _silent_log.debug("suppressed_exception", src='context_provider.py')

        summary = self._build_summary(agent_id, mission_id, decisions, missions, memory_entries)

        return ContextBlock(
            context_summary=summary,
            relevant_files=[],
            recent_decisions=decisions,
            known_constraints=constraints,
            memory_entries=memory_entries,
            agent_history=agent_history,
        )

    def get_context_for_shadow_advisor(self, mission_id: str) -> ContextBlock:
        """Specialized context for shadow-advisor: includes recent decisions + constraints."""
        block = self.get_context("shadow-advisor", mission_id=mission_id, max_entries=15)
        extra = []
        try:
            extra.append("shadow-advisor must validate feasibility before any irreversible action")
            extra.append("reject plans that lack rollback strategy")
        except Exception:
            _silent_log.debug("suppressed_exception", src='context_provider.py')
        block.known_constraints = extra + block.known_constraints
        return block

    def get_context_for_lens_reviewer(self, mission_id: str) -> ContextBlock:
        """Specialized context for lens-reviewer: includes recent outputs + quality checks."""
        block = self.get_context("lens-reviewer", mission_id=mission_id, max_entries=10)
        block.known_constraints = [
            "lens-reviewer checks output quality, coherence, and completeness",
            "flag outputs that contain unresolved TODOs or placeholders",
        ] + block.known_constraints
        return block

    def get_context_for_map_planner(self, mission_id: str) -> ContextBlock:
        """Specialized context for map-planner: includes available agents + tool registry."""
        block = self.get_context("map-planner", mission_id=mission_id, max_entries=10)
        # Inject known agent list
        try:
            from core.task_router import TaskRouter
            block.relevant_files.append("core/task_router.py")
        except Exception:
            _silent_log.debug("suppressed_exception", src='context_provider.py')
        try:
            from tools.tool_registry import get_tool_registry
            tools = get_tool_registry().list_tools()
            block.known_constraints.insert(0, f"Available tools: {', '.join(tools)}")
        except Exception:
            _silent_log.debug("suppressed_exception", src='context_provider.py')
        return block


# Module-level singleton
_provider: ContextProvider | None = None


def get_context_provider() -> ContextProvider:
    global _provider
    if _provider is None:
        _provider = ContextProvider()
    return _provider
