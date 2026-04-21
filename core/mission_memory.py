"""
JARVIS — Mission Memory Layer
=================================
Cross-mission learning: tracks execution patterns, subtask reuse,
strategy effectiveness across related missions.

This is the "long-horizon" intelligence — Jarvis gets better at
sequences of related work, not just individual missions.

Called from:
- mission_system.complete() — records outcomes
- planner.build_plan() — retrieves relevant strategies

Data stored:
- Successful tool sequences per mission type
- Subtask patterns that worked
- Multi-mission dependency chains
- Strategy effectiveness scores

Persistence: workspace/mission_memory.json
Bounded: 500 strategy entries, 200 sequences.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("jarvis.mission_memory")


@dataclass
class ToolSequence:
    """A recorded tool execution sequence."""
    mission_type: str
    tools: list[str]
    success: bool
    duration_s: float = 0.0
    complexity: str = "medium"
    count: int = 1  # how many times this sequence was observed
    last_seen: float = 0.0

    @property
    def effectiveness(self) -> float:
        """0.0-1.0 score based on success and frequency."""
        if not self.success:
            return 0.0
        return min(1.0, 0.5 + self.count * 0.1)

    def to_dict(self) -> dict:
        return {
            "mission_type": self.mission_type,
            "tools": self.tools,
            "success": self.success,
            "duration_s": round(self.duration_s, 1),
            "complexity": self.complexity,
            "count": self.count,
            "effectiveness": round(self.effectiveness, 3),
        }


@dataclass
class StrategyRecord:
    """A recorded mission strategy (agents + tools + plan)."""
    mission_type: str
    agents: list[str]
    tools: list[str]
    plan_steps: int
    successes: int = 0
    failures: int = 0
    total_duration_s: float = 0.0
    last_used: float = 0.0

    @property
    def success_rate(self) -> float:
        total = self.successes + self.failures
        return self.successes / max(total, 1)

    @property
    def avg_duration_s(self) -> float:
        total = self.successes + self.failures
        return self.total_duration_s / max(total, 1)

    @property
    def confidence(self) -> float:
        """Confidence in this strategy (more data = more confidence)."""
        total = self.successes + self.failures
        if total < 3:
            return 0.3
        return min(0.95, self.success_rate * (1 - 1 / total))

    def to_dict(self) -> dict:
        return {
            "mission_type": self.mission_type,
            "agents": self.agents,
            "tools": self.tools,
            "plan_steps": self.plan_steps,
            "success_rate": round(self.success_rate, 3),
            "confidence": round(self.confidence, 3),
            "total_uses": self.successes + self.failures,
            "avg_duration_s": round(self.avg_duration_s, 1),
        }


class MissionMemory:
    """
    Cross-mission learning memory.

    Tracks what works across missions, enables strategy reuse,
    and identifies failing patterns.
    """

    MAX_STRATEGIES = 500
    MAX_SEQUENCES = 200
    PERSIST_FILE = "workspace/mission_memory.json"

    def __init__(self, persist_path: Optional[str] = None):
        self._strategies: dict[str, StrategyRecord] = {}  # key = type:agents:tools
        self._sequences: dict[str, ToolSequence] = {}     # key = type:tools
        self._persist_path = persist_path or self.PERSIST_FILE
        self._dirty = False
        self._loaded = False

    def _ensure_loaded(self):
        if not self._loaded:
            self.load()
            self._loaded = True

    def record_outcome(
        self,
        mission_type: str,
        agents: list[str],
        tools: list[str],
        plan_steps: int,
        success: bool,
        duration_s: float = 0.0,
        complexity: str = "medium",
    ) -> None:
        """Record a mission outcome for cross-mission learning."""
        self._ensure_loaded()

        # Strategy record
        s_key = f"{mission_type}:{','.join(sorted(agents))}:{','.join(sorted(tools))}"
        if s_key not in self._strategies:
            if len(self._strategies) >= self.MAX_STRATEGIES:
                # Evict lowest confidence
                worst = min(self._strategies.values(), key=lambda s: s.confidence)
                worst_key = f"{worst.mission_type}:{','.join(sorted(worst.agents))}:{','.join(sorted(worst.tools))}"
                self._strategies.pop(worst_key, None)

            self._strategies[s_key] = StrategyRecord(
                mission_type=mission_type,
                agents=list(agents),
                tools=list(tools),
                plan_steps=plan_steps,
            )

        strategy = self._strategies[s_key]
        if success:
            strategy.successes += 1
        else:
            strategy.failures += 1
        strategy.total_duration_s += duration_s
        strategy.last_used = time.time()

        # Tool sequence record
        if tools:
            t_key = f"{mission_type}:{','.join(tools)}"
            if t_key not in self._sequences:
                if len(self._sequences) >= self.MAX_SEQUENCES:
                    oldest = min(self._sequences.values(), key=lambda s: s.last_seen)
                    old_key = f"{oldest.mission_type}:{','.join(oldest.tools)}"
                    self._sequences.pop(old_key, None)

                self._sequences[t_key] = ToolSequence(
                    mission_type=mission_type,
                    tools=list(tools),
                    success=success,
                    duration_s=duration_s,
                    complexity=complexity,
                )
            else:
                seq = self._sequences[t_key]
                seq.count += 1
                seq.success = seq.success or success  # keep True if ever succeeded
                seq.last_seen = time.time()

        self._dirty = True

    def get_best_strategy(self, mission_type: str, min_confidence: float = 0.4) -> Optional[dict]:
        """Return the most effective strategy for a mission type."""
        self._ensure_loaded()
        candidates = [
            s for s in self._strategies.values()
            if s.mission_type == mission_type and s.confidence >= min_confidence
        ]
        if not candidates:
            return None
        best = max(candidates, key=lambda s: (s.confidence, s.success_rate))
        return best.to_dict()

    def get_effective_sequences(self, mission_type: str, top_k: int = 5) -> list[dict]:
        """Return tool sequences that work for a mission type."""
        self._ensure_loaded()
        seqs = [
            s for s in self._sequences.values()
            if s.mission_type == mission_type and s.success
        ]
        seqs.sort(key=lambda s: s.effectiveness, reverse=True)
        return [s.to_dict() for s in seqs[:top_k]]

    def get_failing_patterns(self, min_failures: int = 3) -> list[dict]:
        """Return strategies that consistently fail."""
        self._ensure_loaded()
        return [
            s.to_dict() for s in self._strategies.values()
            if s.failures >= min_failures and s.success_rate < 0.40
        ]

    def get_dashboard_data(self) -> dict:
        """Dashboard payload."""
        self._ensure_loaded()
        strategies = list(self._strategies.values())
        sequences = list(self._sequences.values())
        return {
            "total_strategies": len(strategies),
            "total_sequences": len(sequences),
            "effective_strategies": sum(1 for s in strategies if s.confidence >= 0.6),
            "failing_patterns": len(self.get_failing_patterns()),
            "top_strategies": sorted(
                [s.to_dict() for s in strategies if s.successes + s.failures >= 2],
                key=lambda x: x["confidence"], reverse=True,
            )[:10],
            "top_sequences": sorted(
                [s.to_dict() for s in sequences if s.success],
                key=lambda x: x["effectiveness"], reverse=True,
            )[:10],
        }

    def save(self) -> bool:
        if not self._dirty:
            return True
        try:
            os.makedirs(os.path.dirname(self._persist_path) or ".", exist_ok=True)
            data = {
                "strategies": [s.to_dict() for s in self._strategies.values()],
                "sequences": [s.to_dict() for s in self._sequences.values()],
            }
            with open(self._persist_path, "w") as f:
                json.dump(data, f, indent=2)
            self._dirty = False
            return True
        except Exception as e:
            logger.warning("mission_memory_save_failed: %s", str(e)[:80])
            return False

    def load(self) -> bool:
        if not os.path.exists(self._persist_path):
            return False
        try:
            with open(self._persist_path) as f:
                data = json.load(f)
            for sd in data.get("strategies", []):
                key = f"{sd['mission_type']}:{','.join(sorted(sd.get('agents',[])))}" \
                      f":{','.join(sorted(sd.get('tools',[])))}"
                sr = StrategyRecord(
                    mission_type=sd["mission_type"],
                    agents=sd.get("agents", []),
                    tools=sd.get("tools", []),
                    plan_steps=sd.get("plan_steps", 0),
                )
                sr.successes = int(sd.get("success_rate", 0) * sd.get("total_uses", 0))
                sr.failures = sd.get("total_uses", 0) - sr.successes
                self._strategies[key] = sr
            return True
        except Exception as e:
            logger.warning("mission_memory_load_failed: %s", str(e)[:80])
            return False


_memory: Optional[MissionMemory] = None


def get_mission_memory() -> MissionMemory:
    global _memory
    if _memory is None:
        _memory = MissionMemory()
    return _memory
