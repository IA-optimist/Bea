"""
BEA — Operating Primitives (thin wrapper)
==========================================
This module re-exports everything from the core/primitives/ sub-package.
All existing ``from core.operating_primitives import X`` statements continue
to work unchanged — this is a pure backward-compatibility shim.

Sub-modules:
  core.primitives.scoring      — FeasibilityScore, ValueEstimate, StrategyRecommendation
  core.primitives.objectives   — PersistentObjective, ObjectiveTracker, ObjectivePortfolio
  core.primitives.workflows    — WorkflowTemplate, WorkflowTemplateStore
  core.primitives.economics    — EconomicEstimate, compute_economics, record_economic_outcome
  core.primitives.coordination — mission coordination, approval gating, business loop
"""
from __future__ import annotations

# ── scoring ──────────────────────────────────────────────────
from core.primitives.scoring import (
    FeasibilityScore,
    score_feasibility,
    ValueEstimate,
    estimate_value,
    StrategyRecommendation,
    select_strategy,
)

# ── objectives ───────────────────────────────────────────────
from core.primitives.objectives import (
    PersistentObjective,
    ObjectiveTracker,
    get_objective_tracker,
    ObjectivePortfolio,
    OBJECTIVE_DOMAINS,
)

# ── workflows ────────────────────────────────────────────────
from core.primitives.workflows import (
    WorkflowTemplate,
    STANDARD_PHASES,
    MAX_WORKFLOW_DEPTH,
    WorkflowTemplateStore,
    get_workflow_store,
)

# ── economics ────────────────────────────────────────────────
from core.primitives.economics import (
    EconomicEstimate,
    compute_economics,
    record_economic_outcome,
    get_economic_trends,
)

# ── coordination ─────────────────────────────────────────────
from core.primitives.coordination import (
    MAX_CONCURRENT_MISSIONS,
    can_accept_mission,
    prioritize_missions,
    get_operational_signals,
    OpportunitySuggestion,
    detect_opportunities,
    APPROVAL_REQUIRED_ACTIONS,
    requires_approval,
    get_approval_status,
    FocusRecommendation,
    recommend_focus,
    suggest_playbooks,
    get_operating_summary,
)

__all__ = [
    # scoring
    "FeasibilityScore", "score_feasibility",
    "ValueEstimate", "estimate_value",
    "StrategyRecommendation", "select_strategy",
    # objectives
    "PersistentObjective", "ObjectiveTracker", "get_objective_tracker",
    "ObjectivePortfolio", "OBJECTIVE_DOMAINS",
    # workflows
    "WorkflowTemplate", "STANDARD_PHASES", "MAX_WORKFLOW_DEPTH",
    "WorkflowTemplateStore", "get_workflow_store",
    # economics
    "EconomicEstimate", "compute_economics",
    "record_economic_outcome", "get_economic_trends",
    # coordination
    "MAX_CONCURRENT_MISSIONS", "can_accept_mission", "prioritize_missions",
    "get_operational_signals",
    "OpportunitySuggestion", "detect_opportunities",
    "APPROVAL_REQUIRED_ACTIONS", "requires_approval", "get_approval_status",
    "FocusRecommendation", "recommend_focus", "suggest_playbooks",
    "get_operating_summary",
]
