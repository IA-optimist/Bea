"""
BEA — Safety Controls
============================
Central safety control layer for all intelligence features.

Kill switches:
- BEA_DISABLE_ALL_INTELLIGENCE: disables all intelligence layers
- BEA_DISABLE_PROPOSALS: disables improvement proposal generation
- BEA_DISABLE_AUTO_DETECTION: disables automatic issue detection
- BEA_DISABLE_DYNAMIC_ROUTING: disables performance-based routing
- BEA_DISABLE_EXECUTION_ENGINE: forces legacy tool execution path
- BEA_READ_ONLY_MODE: prevents any write operations

Feature flags (opt-in):
- BEA_USE_CANONICAL_ORCHESTRATOR: v3 orchestration path
- BEA_DYNAMIC_ROUTING: performance-based agent routing
- BEA_INTELLIGENCE_HOOKS: post-execution intelligence signals

This module is the single place to check all safety state.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger("bea.safety")


@dataclass
class SafetyState:
    """Current safety state of all intelligence features."""
    intelligence_enabled: bool = True
    proposals_enabled: bool = True
    auto_detection_enabled: bool = True
    dynamic_routing_enabled: bool = False  # opt-in
    execution_engine_enabled: bool = True
    read_only_mode: bool = False
    canonical_orchestrator: bool = False  # opt-in
    intelligence_hooks: bool = False  # opt-in

    def to_dict(self) -> dict:
        return {
            "intelligence_enabled": self.intelligence_enabled,
            "proposals_enabled": self.proposals_enabled,
            "auto_detection_enabled": self.auto_detection_enabled,
            "dynamic_routing_enabled": self.dynamic_routing_enabled,
            "execution_engine_enabled": self.execution_engine_enabled,
            "read_only_mode": self.read_only_mode,
            "canonical_orchestrator": self.canonical_orchestrator,
            "intelligence_hooks": self.intelligence_hooks,
        }


def get_safety_state() -> SafetyState:
    """Read current safety state from environment variables."""
    def _flag(name: str, default: bool = False) -> bool:
        val = os.environ.get(name, "").lower()
        if default:
            return val not in ("0", "false", "no", "off")
        return val in ("1", "true", "yes", "on")

    return SafetyState(
        intelligence_enabled=not _flag("BEA_DISABLE_ALL_INTELLIGENCE"),
        proposals_enabled=not _flag("BEA_DISABLE_PROPOSALS"),
        auto_detection_enabled=not _flag("BEA_DISABLE_AUTO_DETECTION"),
        dynamic_routing_enabled=_flag("BEA_DYNAMIC_ROUTING"),
        execution_engine_enabled=not _flag("BEA_DISABLE_EXECUTION_ENGINE"),
        read_only_mode=_flag("BEA_READ_ONLY_MODE"),
        canonical_orchestrator=_flag("BEA_USE_CANONICAL_ORCHESTRATOR"),
        intelligence_hooks=_flag("BEA_INTELLIGENCE_HOOKS"),
    )


def is_intelligence_enabled() -> bool:
    """Quick check: is any intelligence feature allowed?"""
    return os.environ.get("BEA_DISABLE_ALL_INTELLIGENCE", "").lower() not in ("1", "true", "yes", "on")


def is_proposals_enabled() -> bool:
    """Quick check: can proposals be generated?"""
    if not is_intelligence_enabled():
        return False
    return os.environ.get("BEA_DISABLE_PROPOSALS", "").lower() not in ("1", "true", "yes", "on")


def is_execution_engine_enabled() -> bool:
    """Quick check: should execution engine be used?"""
    return os.environ.get("BEA_DISABLE_EXECUTION_ENGINE", "").lower() not in ("1", "true", "yes", "on")


# ── Lifecycle Validation ─────────────────────────────────────────

EXPECTED_LIFECYCLE = [
    "mission_received",
    "plan_generated",
    "agents_selected",
    "tools_executed",
    "results_evaluated",
    "memory_updated",
    "proposals_checked",
]


def validate_lifecycle(steps_completed: list[str]) -> dict:
    """
    Validate that a mission followed the expected lifecycle.

    Returns:
    {"valid": bool, "missing": list[str], "extra": list[str], "coverage": float}
    """
    expected_set = set(EXPECTED_LIFECYCLE)
    completed_set = set(steps_completed)
    missing = expected_set - completed_set
    extra = completed_set - expected_set
    coverage = len(expected_set & completed_set) / max(len(expected_set), 1)

    return {
        "valid": len(missing) == 0,
        "missing": sorted(missing),
        "extra": sorted(extra),
        "coverage": round(coverage, 3),
        "steps_expected": len(EXPECTED_LIFECYCLE),
        "steps_completed": len(steps_completed),
    }
