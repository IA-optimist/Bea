"""
Self-Improvement Loop API Routes — v2

Endpoints:
  GET  /api/v2/self-improvement/status   → allowed, reason, last, consecutive_failures
  GET  /api/v2/self-improvement/report   → full improvement stats
  POST /api/v2/self-improvement/run      → full cycle (weakness→candidates→score→execute top 1)
"""
from __future__ import annotations

import datetime
import logging

from fastapi import APIRouter

from core.security.rbac import require_role, CurrentUser
from typing import Optional as _Opt
from fastapi import Depends, Header

logger = logging.getLogger("jarvis.api.self_improvement")

# Routes en lecture (viewer+) et routes mutantes (admin only) séparées ci-dessous.
router = APIRouter(
    prefix="/api/v2/self-improvement",
    tags=["self-improvement"],
)

# ── Fail-open imports ─────────────────────────────────────────────────────────
try:
    from core.self_improvement import check_improvement_allowed
    from core.self_improvement.weakness_detector import get_weakness_detector
    from core.self_improvement.candidate_generator import get_candidate_generator
    from core.self_improvement.improvement_scorer import get_improvement_scorer
    from core.self_improvement.safe_executor import get_safe_executor
    from core.self_improvement.improvement_memory import get_improvement_memory
    _SI_AVAILABLE = True
except ImportError as _e:
    logger.warning("self_improvement module unavailable: %s", _e)
    _SI_AVAILABLE = False


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/status")
async def get_status(_user: CurrentUser = Depends(require_role("viewer"))):
    """Returns current self-improvement guard status."""
    if not _SI_AVAILABLE:
        return {
            "allowed": False,
            "reason": "module_unavailable",
            "last_improvement": None,
            "consecutive_failures": 0,
        }
    try:
        result = check_improvement_allowed()
        memory = get_improvement_memory()
        report = memory.get_improvement_report()

        last = report.get("last_improvement")
        last_str: str | None = None
        if last and last.get("timestamp"):
            last_str = datetime.datetime.fromtimestamp(
                last["timestamp"], tz=datetime.timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%SZ")

        return {
            "allowed": result.get("allowed", False),
            "reason": result.get("reason", "unknown"),
            "last_improvement": last_str,
            "consecutive_failures": report.get("consecutive_failures", 0),
        }
    except Exception as exc:
        logger.warning("get_status error: %s", exc)
        return {
            "allowed": False,
            "reason": f"error: {exc}",
            "last_improvement": None,
            "consecutive_failures": 0,
        }


@router.get("/report")
async def get_report(_user: CurrentUser = Depends(require_role("operator"))):
    """Returns full improvement history report."""
    if not _SI_AVAILABLE:
        return {"ok": False, "error": "module_unavailable"}
    try:
        memory = get_improvement_memory()
        report = memory.get_improvement_report()
        return {"ok": True, **report}
    except Exception as exc:
        logger.warning("get_report error: %s", exc)
        return {"ok": False, "error": str(exc)}


@router.post("/run")
async def run_improvement_cycle(_user: CurrentUser = Depends(require_role("admin"))):
    """
    Runs one complete self-improvement cycle:
      1. Check anti-loop guards
      2. Detect weaknesses
      3. Generate candidates (max 3)
      4. Score and rank
      5. Execute TOP 1 candidate only
      6. Record result in memory
    """
    if not _SI_AVAILABLE:
        return {"ok": False, "error": "module_unavailable"}

    try:
        # Guard check
        check_result = check_improvement_allowed()
        if not check_result.get("allowed", False):
            return {
                "ok": False,
                "skipped": True,
                "reason": check_result.get("reason"),
            }

        memory = get_improvement_memory()
        history = memory.get_history()

        # Step 1: Weaknesses
        detector = get_weakness_detector()
        weaknesses = detector.detect()

        # Step 2: Candidates
        generator = get_candidate_generator()
        candidates = generator.generate(weaknesses)

        if not candidates:
            return {"ok": True, "skipped": True, "reason": "no_candidates"}

        # Step 3: Score
        scorer = get_improvement_scorer()
        scored = scorer.score_and_rank(candidates, history)

        # Step 4: Execute TOP 1 only (anti-loop guard)
        top_candidate, top_score = scored[0]
        executor = get_safe_executor()
        result = executor.execute(top_candidate)

        # Step 5: Record
        if result.success:
            outcome = "SUCCESS"
        elif result.rollback_triggered:
            outcome = "ROLLED_BACK"
        else:
            outcome = "FAILURE"

        memory.record(
            candidate_type=top_candidate.type,
            description=top_candidate.description,
            score=top_score,
            outcome=outcome,
            applied_change=result.applied_change,
        )

        return {
            "ok": True,
            "weaknesses_detected": len(weaknesses),
            "candidates_generated": len(candidates),
            "applied": {
                "type": top_candidate.type,
                "description": top_candidate.description,
                "score": top_score,
                "outcome": outcome,
                "applied_change": result.applied_change,
                "error": result.error or None,
            },
        }

    except Exception as exc:
        logger.error("run_improvement_cycle error: %s", exc)
        return {"ok": False, "error": str(exc)}

# NOTE: GET /suggestions was removed from this router (2026-04-04).
# The canonical implementation lives in self_improvement_v2.py at
# @router.get("/api/v2/self-improvement/suggestions") which is now
# mounted first and returns the richer {suggestions, count, ok} schema.
# Keeping this handler here caused a silent route shadow where the older,
# weaker implementation always won over the v2 version.
