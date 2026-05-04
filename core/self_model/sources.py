"""
core/self_model/sources.py — Runtime data sources for the Self-Model.

Each function extracts truth from one runtime subsystem.
All functions are fail-open: if a source is unavailable, return empty/defaults.
No function ever modifies state — read-only introspection.
"""
from __future__ import annotations

import os
import structlog

log = structlog.get_logger()


# ── Capability Graph ──────────────────────────────────────────────────────────

def read_capability_graph() -> list[dict]:
    """Read all capabilities from the cognitive CapabilityGraph."""
    try:
        from core.cognitive_bridge import get_bridge
        bridge = get_bridge()
        graph = bridge.capability_graph
        return graph.get_all() if hasattr(graph, "get_all") else []
    except Exception as e:
        log.debug("self_model.source.capability_graph_unavailable", error=str(e)[:80])
        return []


# ── MCP Registry ──────────────────────────────────────────────────────────────

def read_mcp_registry() -> list[dict]:
    """Read all MCP server entries from the registry."""
    try:
        from core.mcp.mcp_registry import get_mcp_registry
        registry = get_mcp_registry()
        return [s.safe_dict() if hasattr(s, "safe_dict") else vars(s)
                for s in registry.list_all()]
    except Exception as e:
        log.debug("self_model.source.mcp_registry_unavailable", error=str(e)[:80])
        return []


# ── Module Manager ────────────────────────────────────────────────────────────

def read_modules() -> dict[str, list[dict]]:
    """Read all modules (agents, skills, connectors, MCP) from the manager."""
    try:
        from core.modules.module_manager import get_module_manager
        mgr = get_module_manager()
        result = {}
        for mtype in ("agent", "skill", "mcp", "connector"):
            items = mgr.list_modules(mtype)
            result[mtype] = items if isinstance(items, list) else []
        return result
    except Exception as e:
        log.debug("self_model.source.module_manager_unavailable", error=str(e)[:80])
        return {}


# ── Tool Permissions ──────────────────────────────────────────────────────────

def read_tool_permissions() -> list[dict]:
    """Read gated tool permissions from the SuperAGI patterns layer."""
    try:
        from core.superagi_patterns import get_tool_permissions
        perms = get_tool_permissions()
        return perms.list_all() if hasattr(perms, "list_all") else []
    except Exception as e:
        log.debug("self_model.source.tool_permissions_unavailable", error=str(e)[:80])
        return []


# ── Agent Reputation ──────────────────────────────────────────────────────────

def read_agent_reputation() -> dict[str, dict]:
    """Read agent reputation scores from the cognitive layer."""
    try:
        from core.cognitive_bridge import get_bridge
        bridge = get_bridge()
        rep = bridge.agent_reputation
        if hasattr(rep, "get_all"):
            return rep.get_all()
        return {}
    except Exception as e:
        log.debug("self_model.source.agent_reputation_unavailable", error=str(e)[:80])
        return {}


# ── Protected Paths ───────────────────────────────────────────────────────────

def read_protected_paths() -> dict:
    """Read self-improvement protected paths."""
    try:
        from core.self_improvement.protected_paths import (
            PROTECTED_FILES, PROTECTED_DIRS, PROTECTED_PATTERNS,
        )
        return {
            "files": list(PROTECTED_FILES) if hasattr(PROTECTED_FILES, "__iter__") else [],
            "dirs": list(PROTECTED_DIRS) if hasattr(PROTECTED_DIRS, "__iter__") else [],
            "patterns": list(PROTECTED_PATTERNS) if hasattr(PROTECTED_PATTERNS, "__iter__") else [],
        }
    except Exception as e:
        log.debug("self_model.source.protected_paths_unavailable", error=str(e)[:80])
        return {"files": [], "dirs": [], "patterns": []}


# ── System Health Probes ──────────────────────────────────────────────────────

def probe_auth_health() -> dict:
    """Check if auth system is functional."""
    try:
        from api._deps import _API_TOKEN
        return {"healthy": True, "has_static_token": bool(_API_TOKEN),
                "jwt_available": True}
    except Exception as e:
        return {"healthy": False, "error": str(e)[:80]}


def probe_cognitive_health() -> dict:
    """Check if cognitive bridge is available."""
    try:
        from core.cognitive_bridge import get_bridge
        bridge = get_bridge()
        modules = bridge.list_modules() if hasattr(bridge, "list_modules") else []
        return {"healthy": True, "modules_count": len(modules)}
    except Exception as e:
        return {"healthy": False, "error": str(e)[:80]}


def probe_si_pipeline_health() -> dict:
    """Check if self-improvement pipeline is importable and functional."""
    try:
        from core.self_improvement.promotion_pipeline import PromotionPipeline
        pp = PromotionPipeline()
        return {"healthy": True, "repo_root": str(pp.repo_root)}
    except Exception as e:
        return {"healthy": False, "error": str(e)[:80]}


def probe_mission_system_health() -> dict:
    """Check if mission system is functional."""
    try:
        from core.mission_system import get_mission_system
        ms = get_mission_system()
        stats = ms.stats() if hasattr(ms, "stats") else {}
        return {"healthy": True, "total_missions": stats.get("total", 0)}
    except Exception as e:
        return {"healthy": False, "error": str(e)[:80]}


def probe_docker_health() -> dict:
    """Check if Docker runtime is available (for sandbox execution)."""
    try:
        import subprocess
        result = subprocess.run(
            ["docker", "info"], capture_output=True, text=True, timeout=5,
        )
        return {"healthy": result.returncode == 0}
    except Exception:
        return {"healthy": False, "error": "Docker not available"}


# ── Autonomy Config ───────────────────────────────────────────────────────────

def read_autonomy_config() -> dict:
    """Read current autonomy configuration from settings/env."""
    try:
        from config.settings import get_settings
        s = get_settings()
        return {
            "mode": getattr(s, "autonomy_mode", "supervised_execute"),
            "max_risk_auto": getattr(s, "max_risk_auto_approve", "low"),
            "max_files_per_patch": getattr(s, "max_files_per_patch", 3),
            "max_steps": getattr(s, "max_steps_per_mission", 50),
        }
    except Exception:
        return {
            "mode": os.getenv("AUTONOMY_MODE", "supervised_execute"),
            "max_risk_auto": os.getenv("MAX_RISK_AUTO_APPROVE", "low"),
            "max_files_per_patch": int(os.getenv("MAX_FILES_PER_PATCH", "3")),
            "max_steps": int(os.getenv("MAX_STEPS_PER_MISSION", "50")),
        }
