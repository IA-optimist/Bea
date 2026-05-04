"""
core/aios_manifest.py — AI OS Manifest.

Single entry point to query the entire AI OS structure.
Provides consistency checks and architecture overview.
"""
from __future__ import annotations
import logging
_silent_log = __import__("structlog").get_logger(__name__)

log = logging.getLogger("jarvis.aios")

AIOS_VERSION = "1.0.0"


def get_manifest() -> dict:
    """Full AI OS manifest — all modules, capabilities, tools, agents, policies."""
    manifest = {
        "version": AIOS_VERSION,
        "modules": {},
    }
    
    # Capabilities
    try:
        from core.capabilities.ai_os_capabilities import capability_summary
        manifest["modules"]["capabilities"] = capability_summary()
    except Exception as e:
        manifest["modules"]["capabilities"] = {"error": str(e)[:100]}
    
    # Memory layers
    try:
        from core.memory.memory_layers import MEMORY_TYPE_CONFIG
        manifest["modules"]["memory"] = {
            "types": list(MEMORY_TYPE_CONFIG.keys()),
            "count": len(MEMORY_TYPE_CONFIG),
        }
    except Exception as e:
        manifest["modules"]["memory"] = {"error": str(e)[:100]}
    
    # Tool OS
    try:
        from core.tools.tool_os_layer import tool_summary
        manifest["modules"]["tools"] = tool_summary()
    except Exception as e:
        manifest["modules"]["tools"] = {"error": str(e)[:100]}
    
    # Decision pipeline
    try:
        from core.orchestration.decision_pipeline import PHASE_ORDER
        manifest["modules"]["pipeline"] = {
            "phases": PHASE_ORDER,
            "count": len(PHASE_ORDER),
        }
    except Exception as e:
        manifest["modules"]["pipeline"] = {"error": str(e)[:100]}
    
    # Control profiles
    try:
        from core.policy.control_profiles import list_profiles, get_active_profile
        active = get_active_profile()
        manifest["modules"]["control"] = {
            "profiles": [p["name"] for p in list_profiles()],
            "active": active.name,
            "max_risk": active.max_risk_level,
        }
    except Exception as e:
        manifest["modules"]["control"] = {"error": str(e)[:100]}
    
    # Trace intelligence
    try:
        from core.observability.trace_intelligence import TRACE_DIR
        trace_count = len(list(TRACE_DIR.glob("*.jsonl"))) if TRACE_DIR.exists() else 0
        manifest["modules"]["traces"] = {
            "stored": trace_count,
            "dir": str(TRACE_DIR),
        }
    except Exception as e:
        manifest["modules"]["traces"] = {"error": str(e)[:100]}
    
    # Agent roles
    try:
        from core.agents.role_definitions import ROLE_DEFINITIONS, agent_role_map
        manifest["modules"]["agents"] = {
            "roles": list(ROLE_DEFINITIONS.keys()),
            "agent_count": len(agent_role_map()),
        }
    except Exception as e:
        manifest["modules"]["agents"] = {"error": str(e)[:100]}
    
    # Self-improvement safety
    try:
        from core.self_improvement.safety_boundary import PROTECTED_RUNTIME, ALLOWED_SCOPE
        manifest["modules"]["self_improvement"] = {
            "protected_files": len(PROTECTED_RUNTIME),
            "allowed_scopes": len(ALLOWED_SCOPE),
        }
    except Exception as e:
        manifest["modules"]["self_improvement"] = {"error": str(e)[:100]}
    
    # AI OS v2 modules
    try:
        from core.capabilities.semantic_router import router_stats
        manifest["modules"]["semantic_router"] = router_stats()
    except Exception as e:
        manifest["modules"]["semantic_router"] = {"error": str(e)[:100]}
    try:
        from core.memory.vector_memory import get_vector_memory
        manifest["modules"]["vector_memory"] = get_vector_memory().stats()
    except Exception as e:
        manifest["modules"]["vector_memory"] = {"error": str(e)[:100]}
    try:
        from core.resilience.recovery_engine import get_recovery_engine
        manifest["modules"]["recovery_engine"] = get_recovery_engine().stats()
    except Exception as e:
        manifest["modules"]["recovery_engine"] = {"error": str(e)[:100]}

    # Phase 3 modules
    try:
        from core.skills.skill_discovery import get_skill_discovery
        manifest["modules"]["skill_discovery"] = get_skill_discovery().dashboard_stats()
    except Exception as e:
        manifest["modules"]["skill_discovery"] = {"error": str(e)[:100]}

    # Phase 4 modules
    try:
        from core.agents.agent_registry import get_agent_registry
        manifest["modules"]["agent_registry"] = get_agent_registry().stats()
    except Exception as e:
        manifest["modules"]["agent_registry"] = {"error": str(e)[:100]}
    try:
        from core.connectors.connector_framework import get_connector_framework
        manifest["modules"]["connector_framework"] = get_connector_framework().stats()
    except Exception as e:
        manifest["modules"]["connector_framework"] = {"error": str(e)[:100]}
    try:
        from core.knowledge.ingest_pipeline import get_ingest_pipeline
        manifest["modules"]["knowledge_ingest"] = get_ingest_pipeline().stats()
    except Exception as e:
        manifest["modules"]["knowledge_ingest"] = {"error": str(e)[:100]}

    try:
        from core.self_improvement.research_loop import get_research_loop
        manifest["modules"]["research_loop"] = get_research_loop().stats()
    except Exception as e:
        manifest["modules"]["research_loop"] = {"error": str(e)[:100]}

    return manifest


def consistency_check() -> dict:
    """Check AI OS consistency across modules."""
    issues = []
    
    # Check: all tool-level capabilities have OS-level descriptors
    try:
        from core.capabilities.registry import get_registry
        from core.tools.tool_os_layer import TOOL_OS_REGISTRY
        reg = get_registry()
        for tool_name in reg:
            if tool_name not in TOOL_OS_REGISTRY:
                issues.append(f"Tool '{tool_name}' in registry but not in Tool OS layer")
    except Exception:
        _silent_log.debug("suppressed_exception", src='aios_manifest.py')
    
    # Check: all agents map to a role
    try:
        from core.agents.role_definitions import agent_role_map
        role_map = agent_role_map()
        # Known agents from the system
        known_agents = [
            "atlas-director", "scout-research", "map-planner", "forge-builder",
            "lens-reviewer", "vault-memory", "shadow-advisor", "pulse-ops",
            "night-worker", "jarvis-architect", "jarvis-coder", "jarvis-reviewer",
            "jarvis-qa", "jarvis-devops", "jarvis-watcher",
        ]
        for agent in known_agents:
            if agent not in role_map:
                issues.append(f"Agent '{agent}' has no role assignment")
    except Exception:
        _silent_log.debug("suppressed_exception", src='aios_manifest.py')
    
    # Check: all memory types have valid tier mappings
    try:
        from core.memory.memory_layers import MEMORY_TYPE_CONFIG
        valid_tiers = {"SHORT_TERM", "EPISODIC", "LONG_TERM"}
        for mt, cfg in MEMORY_TYPE_CONFIG.items():
            if cfg["tier"] not in valid_tiers:
                issues.append(f"Memory type '{mt}' has invalid tier '{cfg['tier']}'")
    except Exception:
        _silent_log.debug("suppressed_exception", src='aios_manifest.py')
    
    return {
        "consistent": len(issues) == 0,
        "issues": issues,
        "issue_count": len(issues),
    }
