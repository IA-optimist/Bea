"""
core/autonomy/learning.py — Feedback loop : outcomes → routing decisions.

Wires the autonomy event bus to a small in-memory learning aggregator
so the daemon's planner can ask "what worked yesterday on this kind of
goal ?" without going through the full mission_memory / qdrant stack.

It listens to :
- `autonomy.iteration.completed`  → success signal (for an action)
- `autonomy.iteration.failed`     → failure signal
- `skill.completed` / `skill.failed`

Aggregates into per-action / per-skill counters with a sliding decay :
recent outcomes weigh more than old ones. The result feeds an
`AdaptiveStrategy` that the daemon's planner can consult to bias
toward strategies that have worked recently.

This is a lightweight in-process predictor — not a real ML model. For
a real system, lifelong_learning.py + Qdrant store the long-term
artefacts ; this layer is the fast path that drives next-action
selection.

Public API :
    learner = get_outcome_learner()           # singleton, wires to bus
    learner.score("nmap-scan")                 # 0.0..1.0 success-rate proxy
    learner.recommendation(["nmap", "nuclei"]) # ranked best→worst
    learner.snapshot()                         # debug
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import structlog

from core.autonomy.event_bus import Event, EventBus, get_event_bus

log = structlog.get_logger(__name__)


@dataclass
class _ActionStats:
    """Per-action exponentially-weighted moving-average stats."""
    successes: float = 0.0
    failures: float = 0.0
    last_update: float = field(default_factory=time.time)
    decay_half_life_s: float = 7 * 24 * 3600  # 1 week

    def _decayed(self, new_ts: float) -> Tuple[float, float]:
        """Decay current counters to `new_ts`. Returns (s, f) post-decay."""
        dt = max(0.0, new_ts - self.last_update)
        if dt == 0.0:
            return self.successes, self.failures
        # Exponential decay : weight halves every half_life_s
        weight = 0.5 ** (dt / self.decay_half_life_s)
        return self.successes * weight, self.failures * weight

    def record(self, success: bool, weight: float = 1.0) -> None:
        now = time.time()
        s, f = self._decayed(now)
        if success:
            s += weight
        else:
            f += weight
        self.successes = s
        self.failures = f
        self.last_update = now

    def score(self, smoothing: float = 1.0) -> float:
        """Laplace-smoothed success rate. With no data : 0.5 (uncertain)."""
        s, f = self._decayed(time.time())
        return (s + smoothing) / (s + f + 2 * smoothing)

    def confidence(self) -> float:
        """How much data backs the score, in (0, 1) — saturates above ~10 obs."""
        s, f = self._decayed(time.time())
        n = s + f
        return n / (n + 5.0)


class OutcomeLearner:
    """Listens to action / skill outcomes ; ranks strategies."""

    def __init__(self, bus: Optional[EventBus] = None):
        self._stats: Dict[str, _ActionStats] = defaultdict(_ActionStats)
        self._lock = threading.RLock()
        self._bus = bus or get_event_bus()
        self._tokens = [
            self._bus.subscribe("autonomy.iteration.completed", self._on_action_event),
            self._bus.subscribe("autonomy.iteration.failed", self._on_action_event),
            self._bus.subscribe("skill.completed", self._on_skill_event),
            self._bus.subscribe("skill.failed", self._on_skill_event),
        ]

    # ── Wire-up ──────────────────────────────────────────────
    def detach(self) -> None:
        for t in self._tokens:
            self._bus.unsubscribe(t)
        self._tokens = []

    def _on_action_event(self, event: Event) -> None:
        action = event.payload.get("action") or event.payload.get("name")
        if not action:
            return
        success = event.topic.endswith(".completed")
        self._record(f"action:{action}", success)

    def _on_skill_event(self, event: Event) -> None:
        skill = event.payload.get("skill")
        if not skill:
            return
        success = event.topic == "skill.completed"
        self._record(f"skill:{skill}", success)

    def _record(self, key: str, success: bool) -> None:
        with self._lock:
            self._stats[key].record(success)

    # ── Queries ──────────────────────────────────────────────
    def score(self, identifier: str) -> float:
        """Smoothed success-rate for an action/skill identifier.

        `identifier` should be either `action:<name>` or `skill:<name>`.
        Bare names also work — we try both prefixes.
        """
        with self._lock:
            if identifier in self._stats:
                return self._stats[identifier].score()
            for prefix in ("action:", "skill:"):
                k = prefix + identifier
                if k in self._stats:
                    return self._stats[k].score()
        return 0.5  # no data

    def recommendation(self, candidates: List[str], prefix: str = "") -> List[Tuple[str, float]]:
        """Rank candidates by score, descending.

        Returns list of (candidate, score). `prefix` lets callers
        scope to action: or skill: namespaces.
        """
        ranked = []
        for c in candidates:
            key = (prefix + c) if prefix else c
            ranked.append((c, self.score(key)))
        ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked

    def snapshot(self) -> Dict[str, Dict[str, float]]:
        with self._lock:
            return {
                k: {
                    "score": round(v.score(), 3),
                    "confidence": round(v.confidence(), 3),
                    "successes": round(v.successes, 2),
                    "failures": round(v.failures, 2),
                }
                for k, v in self._stats.items()
            }


# ── Singleton ────────────────────────────────────────────────
_LEARNER: Optional[OutcomeLearner] = None
_LEARNER_LOCK = threading.Lock()


def get_outcome_learner() -> OutcomeLearner:
    global _LEARNER
    if _LEARNER is None:
        with _LEARNER_LOCK:
            if _LEARNER is None:
                _LEARNER = OutcomeLearner()
    return _LEARNER


def reset_outcome_learner() -> None:
    """Test hook : detach + drop singleton so the next get_ wires fresh."""
    global _LEARNER
    with _LEARNER_LOCK:
        if _LEARNER is not None:
            _LEARNER.detach()
        _LEARNER = None
