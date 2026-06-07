"""
core/self_improvement/ — Canonical Self-Improvement Package (V3)
================================================================

CANONICAL ENTRY POINTS:
  from core.self_improvement import check_improvement_allowed
  from core.self_improvement import get_self_improvement_manager
  from core.self_improvement.engine import SelfImprovementEngine

ARCHITECTURE (V3 cycle):
  1. OBSERVE   — FailureCollector gathers runtime signals
  2. CRITIQUE  — ImprovementPlanner clusters and prioritizes
  3. GENERATE  — CandidateGenerator produces patch candidates
  4. SANDBOX   — SandboxExecutor applies patch in isolation
  5. VALIDATE  — ValidationRunner runs tests + linter
  6. PROMOTE   — PromotionPipeline applies to production or queues for review
  7. LEARN     — ImprovementMemory stores outcome for future cycles

DEAD CODE WARNING:
  core/self_improvement.py  — SHADOWED by this package, unreachable at runtime.
                              Contains legacy SelfImprovementManager.
                              Callers that need get_self_improvement_manager()
                              must import from this package (__init__.py).
  core/self_improvement_engine.py  — V2 intermediate, superseded by engine.py.
  core/self_improvement_loop.py    — V3 loop variant, partially superseded.

SAFETY CONSTANTS (anti-loop guards):
  MAX_IMPROVEMENTS_PER_RUN = 1   — never more than 1 improvement per execution
  COOLDOWN_HOURS = 24            — no improvement if last one < 24h ago
  MAX_CONSECUTIVE_FAILURES = 3   — auto-pause after 3 consecutive failures
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("bea.self_improvement")

# ── Anti-loop constants (enforced here, exported for callers) ────────────────
MAX_IMPROVEMENTS_PER_RUN = 1
COOLDOWN_HOURS = 24
MAX_CONSECUTIVE_FAILURES = 3

_HISTORY_PATH = Path("workspace/self_improvement/history.json")


def _load_history() -> list:
    """Loads history from workspace/self_improvement/history.json. Returns [] on error."""
    try:
        if _HISTORY_PATH.exists():
            return json.loads(_HISTORY_PATH.read_text("utf-8"))
    except Exception as e:
        logger.debug(f"_load_history error: {e}")
    return []


def check_improvement_allowed() -> Dict[str, object]:
    """
    Returns {"allowed": bool, "reason": str}.
    Enforces cooldown and consecutive failure limit.
    Never raises — returns allowed=False with reason on error.

    KERNEL AUTHORITATIVE: delegates to kernel.gate.check() as primary authority.
    The kernel is the single decision-maker for improvement gating.
    Fallback to local logic only if kernel.gate import fails.
    """
    # 1 — Kernel gate (authoritative)
    try:
        from kernel.improvement.gate import get_gate
        decision = get_gate().check()
        logger.debug(f"check_improvement_allowed: kernel.gate decision={decision.allowed} reason={decision.reason}")
        return {"allowed": decision.allowed, "reason": decision.reason}
    except Exception as _ke:
        logger.warning(f"check_improvement_allowed: kernel.gate unavailable ({_ke!s:.80}), falling back to local check")

    # 2 — Local fallback (kernel unavailable)
    try:
        history = _load_history()

        if not history:
            return {"allowed": True, "reason": "no_history"}

        # Cooldown check: last attempt must be >= COOLDOWN_HOURS ago
        last_ts = history[-1].get("timestamp", 0)
        hours_since = (time.time() - last_ts) / 3600.0
        if hours_since < COOLDOWN_HOURS:
            return {
                "allowed": False,
                "reason": f"cooldown_active ({hours_since:.1f}h < {COOLDOWN_HOURS}h required)",
            }

        # Consecutive failures check
        consecutive = 0
        for entry in reversed(history):
            outcome = entry.get("outcome", "SUCCESS")
            if outcome in ("FAILURE", "ROLLED_BACK"):
                consecutive += 1
            else:
                break

        if consecutive >= MAX_CONSECUTIVE_FAILURES:
            return {
                "allowed": False,
                "reason": f"max_consecutive_failures ({consecutive} >= {MAX_CONSECUTIVE_FAILURES}) — paused",
            }

        return {"allowed": True, "reason": "ok"}

    except Exception as e:
        logger.warning(f"check_improvement_allowed error: {e}")
        return {"allowed": False, "reason": f"error: {e}"}


# ── Legacy SelfImprovementManager shim ────────────────────────────────────────
# core/self_improvement.py (flat file) is SHADOWED by this package.
# Its SelfImprovementManager and get_self_improvement_manager() are therefore
# unreachable via the normal import path. We re-expose them here so callers
# that do `from core.self_improvement import get_self_improvement_manager` work.
#
# Migration target: callers should use SelfImprovementEngine.run_cycle() instead.

from dataclasses import dataclass, field

@dataclass
class SelfImprovementSuggestion:
    """Legacy suggestion type. Use ImprovementProposal from engine.py for new code."""
    problem_type: str
    mission_type: str
    frequency: int
    confidence_avg: float
    impact_estimate: str
    risk_estimate: str
    suggested_change: str
    affected_files: List[str]
    priority_score: float


class SelfImprovementManager:
    """
    LEGACY COMPATIBILITY SHIM.

    Analyses decision_memory patterns and produces improvement suggestions.
    Does NOT modify any files — suggestions only.

    For new code: use SelfImprovementEngine from core.self_improvement.engine.
    """

    def analyze_patterns(self) -> List[SelfImprovementSuggestion]:
        """
        Delegate to the real legacy implementation if available.
        Falls back to empty list if import fails (shadowed module).
        """
        try:
            # The flat file core/self_improvement.py is shadowed, so we must
            # import it via importlib to bypass the package resolution.
            import importlib.util
            import os
            flat_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "self_improvement.py"
            )
            if not os.path.exists(flat_path):
                return []
            spec = importlib.util.spec_from_file_location(
                "_legacy_si", flat_path
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod.SelfImprovementManager().analyze_patterns()
        except Exception as e:
            logger.warning(f"SelfImprovementManager.analyze_patterns fallback error: {e}")
            return []


_manager: Optional[SelfImprovementManager] = None


def get_self_improvement_manager() -> SelfImprovementManager:
    """
    Returns singleton SelfImprovementManager.

    LEGACY API — preserved for backward compatibility.
    For new code: from core.self_improvement.engine import SelfImprovementEngine
    """
    global _manager
    if _manager is None:
        _manager = SelfImprovementManager()
    return _manager


# ── Lesson / LessonMemory re-export ──────────────────────────────────────────
# Canonical source: core/self_improvement/lesson_memory.py
# Re-exported here so callers can use either:
#   from core.self_improvement import LessonMemory
#   from core.self_improvement.lesson_memory import LessonMemory  (preferred)
from core.self_improvement.lesson_memory import Lesson, LessonMemory  # noqa: E402

__all__ = [
    "check_improvement_allowed",
    "get_self_improvement_manager",
    "SelfImprovementManager",
    "SelfImprovementSuggestion",
    "Lesson",
    "LessonMemory",
]
