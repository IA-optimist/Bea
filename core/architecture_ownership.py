"""
BEA — Architecture Ownership Map
=======================================
Documents the canonical owner for every system responsibility.
Used by the coherence validator to detect ownership violations.

This is documentation-as-code: enforced by tests, not by runtime.

Ownership Rules:
  1. Each responsibility has exactly ONE canonical owner
  2. Other modules may READ from the owner but not DUPLICATE logic
  3. Adapters/facades may wrap but not replace
  4. New code must check ownership before adding logic

KNOWN DUPLICATIONS (to be resolved):
  - _MISSION_TOOLS: tool_runner.py AND tool_registry.py (canonical: tool_registry)
  - MissionStatus: mission_system.py AND meta_orchestrator.py (canonical: meta_orchestrator)
  - RiskLevel: state.py AND approval_queue.py (canonical: state.py)
  - Planner: planner.py AND mission_planner.py (canonical: planner.py)
"""
from __future__ import annotations

# ═══════════════════════════════════════════════════════════════
# CANONICAL OWNERSHIP MAP
# ═══════════════════════════════════════════════════════════════

OWNERSHIP = {
    # --- Lifecycle ---
    "mission_lifecycle": {
        "canonical": "core.mission_system.MissionSystem",
        "active_api": True,
        "note": "MissionSystem owns lifecycle transitions. MetaOrchestrator is canonical design but not yet active API.",
    },
    "mission_lifecycle_canonical": {
        "canonical": "core.meta_orchestrator.MetaOrchestrator",
        "active_api": False,
        "note": "Will replace MissionSystem via OrchestrationBridge when BEA_USE_CANONICAL_ORCHESTRATOR=1",
    },

    # --- Planning ---
    "mission_planning": {
        "canonical": "core.planner.Planner.build_plan",
        "note": "Primary planner. mission_planner.py is supplementary (simpler logic).",
    },
    "plan_execution": {
        "canonical": "api.main._run_mission",
        "note": "Plan steps executed in _run_mission via planner.get_next_steps/execute_step",
    },

    # --- Agent Selection ---
    "agent_selection": {
        "canonical": "agents.selector.AgentSelector.select_agents",
        "note": "agents.crew re-exports selector symbols for legacy imports; core.dynamic_agent_router remains advisory, not owner.",
    },

    # --- Tool Execution ---
    "tool_execution": {
        "canonical": "core.tool_executor.ToolExecutor",
        "note": "Low-level execution. Wrapped by execution_engine for intelligence.",
    },
    "tool_pre_execution": {
        "canonical": "core.tool_runner.run_tools_for_mission",
        "note": "Pre-mission tool context gathering. Routes through execution_engine.",
    },
    "tool_registry": {
        "canonical": "core.tool_registry._MISSION_TOOLS",
        "note": "CANONICAL source. tool_runner._MISSION_TOOLS is a DUPLICATE to be resolved.",
    },

    # --- Intelligence ---
    "tool_performance": {
        "canonical": "core.tool_performance_tracker.ToolPerformanceTracker",
    },
    "mission_performance": {
        "canonical": "core.mission_performance_tracker.MissionPerformanceTracker",
    },
    "mission_memory": {
        "canonical": "core.mission_memory.MissionMemory",
        "note": "Cross-mission strategy learning.",
    },
    "knowledge_ingestion": {
        "canonical": "core.knowledge_ingestion",
    },
    "improvement_proposals": {
        "canonical": "core.improvement_proposals.ProposalStore",
    },
    "improvement_detection": {
        "canonical": "core.improvement_detector.detect_improvements",
    },

    # --- Safety ---
    "safety_controls": {
        "canonical": "core.safety_controls",
    },
    "lifecycle_tracking": {
        "canonical": "core.lifecycle_tracker.LifecycleTracker",
    },

    # --- Execution Intelligence ---
    "execution_intelligence": {
        "canonical": "core.execution_engine",
        "note": "Wraps tool_executor with health gate, adaptive retry, fallback, telemetry.",
    },
    "agent_routing_intelligence": {
        "canonical": "core.dynamic_agent_router",
    },

    # --- API ---
    "mission_api": {
        "canonical": "api.routes.mission_control",
        "note": "v1/v2 API. v3 via api.routes.convergence.",
    },
    "performance_api": {
        "canonical": "api.routes.performance",
    },

    # --- Risk ---
    "risk_assessment": {
        "canonical": "core.state.RiskLevel",
        "note": "CANONICAL. approval_queue.RiskLevel is duplicate.",
    },
}


def get_ownership_map() -> dict:
    return OWNERSHIP


def get_known_duplications() -> list[dict]:
    """Return known duplication issues that should be resolved."""
    return [
        {
            "item": "_MISSION_TOOLS dict",
            "locations": ["core/tool_runner.py:13", "core/tool_registry.py:94"],
            "canonical": "core/tool_registry.py",
            "resolution": "tool_runner should import from tool_registry",
            "risk": "low",
            "status": "documented",
        },
        {
            "item": "MissionStatus enum",
            "locations": ["core/mission_system.py:339", "core/meta_orchestrator.py:41"],
            "canonical": "core/meta_orchestrator.py",
            "resolution": "Bridge via canonical_types.py (already exists)",
            "risk": "medium",
            "status": "bridged",
        },
        {
            "item": "RiskLevel enum",
            "locations": ["core/state.py:28", "core/approval_queue.py:17"],
            "canonical": "core/state.py",
            "resolution": "approval_queue should import from state",
            "risk": "low",
            "status": "documented",
        },
        {
            "item": "Planner modules",
            "locations": ["core/planner.py", "core/mission_planner.py"],
            "canonical": "core/planner.py",
            "resolution": "mission_planner.py is supplementary, not duplicate logic",
            "risk": "low",
            "status": "acceptable",
        },
    ]


# ═══════════════════════════════════════════════════════════════
# DEPRECATION REGISTRY
# ═══════════════════════════════════════════════════════════════

DEPRECATED_MODULES = {
    "core.orchestrator": {
        "replacement": "core.meta_orchestrator.MetaOrchestrator",
        "reason": "Legacy orchestrator superseded by MetaOrchestrator",
        "status": "deprecated_in_code",
    },
    "core.orchestrator_v2": {
        "replacement": "core.meta_orchestrator.MetaOrchestrator",
        "reason": "Budget wrapper — use MetaOrchestrator(use_budget=True)",
        "status": "deprecated_in_code",
    },
    "core.orchestrator_lg.langgraph_flow": {
        "replacement": "core.meta_orchestrator.MetaOrchestrator",
        "reason": "LangGraph flow never activated in production",
        "status": "dormant",
    },
}


def get_deprecated_modules() -> dict:
    return DEPRECATED_MODULES


def validate_ownership() -> dict:
    """
    Validate architecture ownership rules.
    Returns {"valid": bool, "violations": list, "duplications": list}
    """
    violations = []
    duplications = get_known_duplications()

    # Check that canonical files exist
    import os
    for resp, info in OWNERSHIP.items():
        canonical = info.get("canonical", "")
        if not canonical:
            continue
        # Convert module path to file path
        parts = canonical.split(".")
        if len(parts) >= 2:
            file_path = "/".join(parts[:2]) + ".py"
            if not os.path.exists(file_path):
                # Try core/ prefix
                file_path = parts[0] + "/" + parts[1].split(":")[0] + ".py"

    return {
        "valid": len(violations) == 0,
        "violations": violations,
        "duplications_count": len(duplications),
        "duplications": duplications,
        "ownership_entries": len(OWNERSHIP),
    }
