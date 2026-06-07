"""
api/routes/venture.py — Venture Loop API.

Endpoints under /api/v3/venture/:
  GET  /hypotheses      — List venture hypotheses
  GET  /experiments     — List experiment specs
  GET  /evaluations     — List evaluation results
  POST /run-loop        — Run a venture experiment loop
  GET  /status          — Venture layer status
"""
from __future__ import annotations

import logging
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import List

logger = logging.getLogger("bea.api.venture")

# Fail-hard on auth import: if require_auth is unavailable, the router
# must NOT register — a silent fallback to no-auth is worse than 404.
from api._deps import require_auth

router = APIRouter(
    prefix="/api/v3/venture",
    tags=["venture"],
    dependencies=[Depends(require_auth)],
)


class HypothesisRequest(BaseModel):
    problem_statement: str
    target_segment: str
    value_proposition: str
    expected_outcome: str = ""
    assumptions: List[str] = []
    risk_factors: List[str] = []
    test_strategy: str = ""
    success_signal_definition: str = ""
    experiment_type: str = "landing_page_experiment"
    max_iterations: int = 5
    budget_mode: str = "normal"


@router.get("/hypotheses")
async def list_hypotheses():
    """List all venture hypotheses."""
    from core.venture.venture_loop import get_hypotheses
    hyps = get_hypotheses()
    return {
        "hypotheses": {k: v.to_dict() for k, v in hyps.items()},
        "total": len(hyps),
    }


@router.get("/experiments")
async def list_experiments():
    """List experiment specs."""
    from core.venture.venture_loop import get_experiments
    exps = get_experiments()
    return {
        "experiments": {k: v.to_dict() for k, v in exps.items()},
        "total": len(exps),
    }


@router.get("/evaluations")
async def list_evaluations():
    """List evaluation results."""
    from core.venture.venture_loop import get_evaluations
    evals = get_evaluations()
    return {
        "evaluations": [e.to_dict() for e in evals[-50:]],
        "total": len(evals),
    }


@router.post("/run-loop")
async def run_loop(req: HypothesisRequest):
    """Run a venture experiment loop."""
    from core.venture.venture_loop import (
        VentureHypothesis, ExperimentType, run_venture_loop,
    )

    hypothesis = VentureHypothesis(
        problem_statement=req.problem_statement,
        target_segment=req.target_segment,
        value_proposition=req.value_proposition,
        expected_outcome=req.expected_outcome,
        assumptions=req.assumptions,
        risk_factors=req.risk_factors,
        test_strategy=req.test_strategy,
        success_signal_definition=req.success_signal_definition,
    )

    try:
        exp_type = ExperimentType(req.experiment_type)
    except ValueError:
        exp_type = ExperimentType.LANDING_PAGE

    max_iter = max(1, min(req.max_iterations, 5))

    result = run_venture_loop(
        hypothesis=hypothesis,
        experiment_type=exp_type,
        max_iterations=max_iter,
        budget_mode=req.budget_mode,
    )

    return result.to_dict()


@router.get("/status")
async def venture_status():
    """Venture layer status summary."""
    from core.venture.venture_loop import (
        get_hypotheses, get_experiments, get_evaluations, get_loop_results,
    )
    loops = get_loop_results()
    converged = sum(1 for l in loops if l.status == "converged")
    return {
        "active": True,
        "hypotheses": len(get_hypotheses()),
        "experiments": len(get_experiments()),
        "evaluations": len(get_evaluations()),
        "loops_run": len(loops),
        "loops_converged": converged,
        "convergence_rate": round(converged / max(1, len(loops)), 3),
    }
