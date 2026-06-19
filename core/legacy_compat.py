"""
BEA MAX — Legacy Compatibility Layer
==========================================
Documents and bridges all duplicate enums and parallel systems.
Does NOT modify any existing files. Provides:

1. Enum mapping tables (all 3 status systems + 2 risk systems)
2. Conversion functions for inter-system translation
3. Authority map: which system owns what
4. Deprecation markers for future cleanup

This is the single source of truth for "how do these systems relate?"

Protected files (never modified):
    - core/meta_orchestrator.py
    - core/mission_system.py
    - core/orchestrator*
    - core/state*
    - core/contracts/*
    - core/self_improvement/planner.py
"""
from __future__ import annotations



# ═══════════════════════════════════════════════════════════════
# 1. STATUS ENUM MAPPING
# ═══════════════════════════════════════════════════════════════

# Three independent MissionStatus enums exist:
#
# A. core.mission_system.MissionStatus (8 values) — ACTIVE API
#    ANALYZING, PENDING_VALIDATION, APPROVED, EXECUTING, DONE,
#    REJECTED, BLOCKED, PLAN_ONLY
#
# B. core.meta_orchestrator.MissionStatus (6 values) — CANONICAL
#    CREATED, PLANNED, RUNNING, REVIEW, DONE, FAILED
#
# C. core.workflow_graph.WorkflowStage (6 values) — HIL WRAPPER
#    PLANNING, SHADOW_CHECK, AWAITING_APPROVAL, EXECUTING, DONE, FAILED
#
# D. core.canonical_types.CanonicalMissionStatus (10 values) — BRIDGE
#    CREATED, ANALYZING, PLANNING, PENDING_APPROVAL, APPROVED,
#    EXECUTING, REVIEWING, COMPLETED, FAILED, CANCELLED

# Mapping: MissionSystem → MetaOrchestrator
_MS_TO_META = {
    "ANALYZING":          "CREATED",
    "PENDING_VALIDATION": "PLANNED",
    "APPROVED":           "PLANNED",
    "EXECUTING":          "RUNNING",
    "DONE":               "DONE",
    "REJECTED":           "FAILED",
    "BLOCKED":            "FAILED",
    "PLAN_ONLY":          "DONE",
}

# Mapping: MetaOrchestrator → MissionSystem
_META_TO_MS = {
    "CREATED": "ANALYZING",
    "PLANNED": "PENDING_VALIDATION",
    "RUNNING": "EXECUTING",
    "REVIEW":  "EXECUTING",
    "DONE":    "DONE",
    "FAILED":  "REJECTED",
}

# Mapping: WorkflowStage → MetaOrchestrator
_WF_TO_META = {
    "PLANNING":          "CREATED",
    "SHADOW_CHECK":      "PLANNED",
    "AWAITING_APPROVAL": "PLANNED",
    "EXECUTING":         "RUNNING",
    "DONE":              "DONE",
    "FAILED":            "FAILED",
}


def mission_system_to_meta(status: str) -> str:
    """Convert MissionSystem status → MetaOrchestrator status."""
    return _MS_TO_META.get(status, "CREATED")


def meta_to_mission_system(status: str) -> str:
    """Convert MetaOrchestrator status → MissionSystem status."""
    return _META_TO_MS.get(status, "ANALYZING")


def workflow_to_meta(stage: str) -> str:
    """Convert WorkflowStage → MetaOrchestrator status."""
    return _WF_TO_META.get(stage, "CREATED")


# ═══════════════════════════════════════════════════════════════
# 2. RISK LEVEL MAPPING
# ═══════════════════════════════════════════════════════════════

# Two independent RiskLevel enums exist:
#
# A. core.state.RiskLevel (3 values) — DECLARED SOURCE
#    LOW, MEDIUM, HIGH
#
# B. core.approval_queue.RiskLevel (6 values) — ACTION-LEVEL
#    READ, WRITE_LOW, WRITE_HIGH, INFRA, DELETE, DEPLOY
#
# C. core.canonical_types.CanonicalRiskLevel (6 values) — BRIDGE
#    NONE, LOW, MEDIUM, HIGH, CRITICAL, EXTREME

_ACTION_RISK_TO_STATE = {
    "read":       "low",
    "write_low":  "low",
    "write_high": "medium",
    "infra":      "high",
    "delete":     "high",
    "deploy":     "high",
}


def action_risk_to_state_risk(action_risk: str) -> str:
    """Convert approval_queue.RiskLevel → state.RiskLevel."""
    return _ACTION_RISK_TO_STATE.get(action_risk.lower(), "medium")


# ═══════════════════════════════════════════════════════════════
# 3. AUTHORITY MAP
# ═══════════════════════════════════════════════════════════════

AUTHORITY_MAP = {
    "mission_lifecycle": {
        "canonical": "MetaOrchestrator",
        "active_api": "MissionSystem",
        "convergence": "OrchestrationBridge mediates",
        "flag": "BEA_USE_CANONICAL_ORCHESTRATOR",
    },
    "risk_assessment": {
        "canonical": "core.state.RiskLevel",
        "action_level": "core.approval_queue.RiskLevel",
        "note": "Both valid — different abstraction levels",
    },
    "planning": {
        "canonical": "core.planner.Planner",
        "v3": "core.planning.planner_v3.PlannerV3",
        "convergence": "PlannerV3 wraps legacy when PLANNER_VERSION<3",
        "flag": "PLANNER_VERSION",
    },
    "memory": {
        "systems": [
            "memory.memory_bus.MemoryBus",
            "memory.memory_toolkit.MemoryToolkit",
            "core.knowledge_memory.KnowledgeMemory",
            "memory.decision_memory.DecisionMemory",
        ],
        "canonical": "core.memory_facade.MemoryFacade",
        "note": "Facade wraps all; not yet wired to API",
    },
    "tool_registry": {
        "registries": [
            "core.tool_registry._MISSION_TOOLS",
            "core.tool_runner._MISSION_TOOLS",
        ],
        "note": "Two dicts can diverge. Canonical should be tool_registry.",
    },
}


def get_authority_map() -> dict[str, object]:
    """Return the system authority map."""
    return AUTHORITY_MAP


# ═══════════════════════════════════════════════════════════════
# 4. DEPRECATION MARKERS
# ═══════════════════════════════════════════════════════════════

DEPRECATIONS = [
    {
        "system": "MissionSystem lifecycle management",
        "reason": "MetaOrchestrator is canonical authority",
        "migration": "Use OrchestrationBridge with feature flag",
        "status": "bridge_available",
        "priority": "high",
    },
    {
        "system": "core.workflow_graph.WorkflowStage",
        "reason": "Redundant with MetaOrchestrator states",
        "migration": "Map through _WF_TO_META",
        "status": "mapped",
        "priority": "low",
    },
    {
        "system": "core.tool_runner._MISSION_TOOLS dict",
        "reason": "Duplicate of core.tool_registry._MISSION_TOOLS",
        "migration": "Consolidate to single registry",
        "status": "identified",
        "priority": "medium",
    },
]


def get_deprecations() -> list[dict[str, str]]:
    """Return list of identified deprecations."""
    return DEPRECATIONS
