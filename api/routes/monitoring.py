"""
JARVIS MAX — Monitoring Router (Phase 3 + Phase 8)

Routes :
  GET /api/v2/system/health   — santé système
  GET /api/v2/system/metrics  — métriques mission
  GET /api/v2/debug/report    — rapport debug global
  GET /api/v2/debug/mission/{id} — analyse d'une mission
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Header

from api._deps import require_auth

router = APIRouter(tags=["monitoring"], dependencies=[Depends(require_auth)])

_start_time = time.time()
_WORKSPACE_DIR = Path(os.environ.get("WORKSPACE_DIR", "workspace"))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mission_system():
    from core.mission_system import get_mission_system
    return get_mission_system()


def _state_store():
    from api.mission_store import MissionStateStore
    return MissionStateStore.get()


def _memory_layers() -> dict:
    try:
        from memory.memory_bus import MemoryBus
        from config.settings import get_settings
        bus = MemoryBus(get_settings())
        counts: dict[str, int] = {}
        for layer_name in ("short_term", "working_memory", "episodic", "semantic", "procedural"):
            try:
                layer = getattr(bus, f"_{layer_name}", None) or getattr(bus, layer_name, None)
                if layer and hasattr(layer, "__len__"):
                    counts[layer_name] = len(layer)
                else:
                    counts[layer_name] = -1
            except Exception:
                counts[layer_name] = -1
        return counts
    except Exception:
        return {}


def _last_mission_at() -> str | None:
    try:
        ms       = _mission_system()
        missions = ms.list_missions(limit=1)
        if missions:
            ts = missions[0].updated_at or missions[0].created_at
            return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
    except Exception:
        _silent_log.debug("suppressed_exception", src='monitoring.py')
    return None


from api._deps import _check_auth
_silent_log = __import__("structlog").get_logger(__name__)


# ══════════════════════════════════════════════════════════════
# HEALTH
# ══════════════════════════════════════════════════════════════

@router.get("/api/v2/system/health")
async def system_health(x_jarvis_token: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    """Santé système complète — uptime, containers, mémoire, dernière mission."""
    _check_auth(x_jarvis_token, authorization)

    # Container status (docker socket ou simple fichier de présence)
    containers: dict[str, str] = {}
    try:
        import subprocess
        result = subprocess.run(
            ["docker", "ps", "--filter", "name=jarvis", "--format", "{{.Names}}:{{.Status}}"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.strip().splitlines():
            if ":" in line:
                name, status = line.split(":", 1)
                containers[name.strip()] = "up" if "Up" in status else status.strip()
    except Exception:
        containers["jarvis_core"] = "unknown"

    # Memory Facade health (P5 — unified memory)
    facade_health: dict = {}
    try:
        from core.memory_facade import get_memory_facade
        facade_health = get_memory_facade().health()
    except Exception:
        facade_health = {"available": False, "error": "import_failed"}

    return {
        "status":           "healthy",
        "uptime_s":         int(time.time() - _start_time),
        "containers":       containers,
        "memory_layers":    _memory_layers(),
        "memory_facade":    facade_health,
        "last_mission_at":  _last_mission_at(),
    }


# ══════════════════════════════════════════════════════════════
# METRICS
# ══════════════════════════════════════════════════════════════

@router.get("/api/v2/system/metrics")
async def system_metrics(x_jarvis_token: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    """Métriques calculées depuis MissionStateStore et traces d'exécution."""
    _check_auth(x_jarvis_token, authorization)

    ms           = _mission_system()
    all_missions = ms.list_missions(limit=500)
    total        = len(all_missions)

    # Missions par statut
    by_status: dict[str, int] = {}
    for m in all_missions:
        by_status[m.status] = by_status.get(m.status, 0) + 1

    # Taux de succès
    done_count   = by_status.get("DONE", 0)
    success_rate = round(done_count / total, 3) if total else 0.0

    # Latence moyenne depuis les advisory scores
    latencies    = []
    advisory_scores = []
    for m in all_missions:
        if m.advisory_score and m.advisory_score > 0:
            advisory_scores.append(m.advisory_score)
        upd = getattr(m, "updated_at", 0)
        crt = getattr(m, "created_at", 0)
        if upd and crt and upd > crt:
            latencies.append(int((upd - crt) * 1000))

    avg_latency_ms    = int(sum(latencies) / len(latencies)) if latencies else 0
    avg_advisory_score = round(sum(advisory_scores) / len(advisory_scores), 2) if advisory_scores else 0.0

    # Agent error rates et retry rate depuis trace JSONL
    agent_error_rates: dict[str, float] = {}
    retry_rate = 0.0
    try:
        from agents.debug_agent import DebugMonitor
        monitor       = DebugMonitor()
        report        = monitor.generate_debug_report()
        agent_error_rates = report.get("agent_error_rates", {})
        retry_rate    = report.get("retry_rate", 0.0)
    except Exception:
        _silent_log.debug("suppressed_exception", src='monitoring.py')

    return {
        "total_missions":      total,
        "success_rate":        success_rate,
        "avg_latency_ms":      avg_latency_ms,
        "avg_advisory_score":  avg_advisory_score,
        "agent_error_rates":   agent_error_rates,
        "retry_rate":          retry_rate,
        "missions_by_status":  by_status,
    }


# ══════════════════════════════════════════════════════════════
# DEBUG
# ══════════════════════════════════════════════════════════════

@router.get("/api/v2/debug/report")
async def debug_report(x_jarvis_token: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    """Rapport de debug global (fenêtre 1h)."""
    _check_auth(x_jarvis_token, authorization)
    try:
        from agents.debug_agent import DebugMonitor
        monitor = DebugMonitor()
        return {"ok": True, "data": monitor.generate_debug_report()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/api/v2/debug/mission/{mission_id}")
async def debug_mission(
    mission_id: str,
    x_jarvis_token: Optional[str] = Header(None), authorization: Optional[str] = Header(None),
):
    """Analyse de debug pour une mission spécifique."""
    _check_auth(x_jarvis_token, authorization)
    try:
        from agents.debug_agent import DebugMonitor
        monitor = DebugMonitor()
        return {"ok": True, "data": monitor.analyze_mission(mission_id)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ══════════════════════════════════════════════════════════════
# CAPABILITIES  (Phase 10+ — V3 foundations)
# ══════════════════════════════════════════════════════════════

@router.get("/api/v2/system/capabilities")
async def get_capabilities(x_jarvis_token: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    """
    Retourne l'état réel du système : modalités, agents, rôles.

    Règle : 'active' = réellement câblé et fonctionnel.
    'planned' = prévu avec ETA version. Jamais de silence.
    """
    _check_auth(x_jarvis_token, authorization)
    try:
        from agents.multimodal_router import get_multimodal_router
        caps = get_multimodal_router().get_capabilities()
    except ImportError:
        caps = {
            "modalities": {
                "text":       {"status": "active",  "description": "Texte libre"},
                "image":      {"status": "planned", "eta": "V3"},
                "audio":      {"status": "planned", "eta": "V3"},
                "document":   {"status": "planned", "eta": "V3"},
                "screenshot": {"status": "planned", "eta": "V3"},
            },
            "active":  ["text"],
            "planned": ["image", "audio", "document", "screenshot"],
        }

    _AGENT_REGISTRY = {
        "atlas-director":  {"status": "active",  "role": "orchestration"},
        "scout-research":  {"status": "active",  "role": "research"},
        "map-planner":     {"status": "active",  "role": "planning"},
        "forge-builder":   {"status": "active",  "role": "dev"},
        "lens-reviewer":   {"status": "active",  "role": "review"},
        "vault-memory":    {"status": "active",  "role": "memory"},
        "shadow-advisor":  {"status": "active",  "role": "advisory"},
        "pulse-ops":       {"status": "active",  "role": "operations"},
        "night-worker":    {"status": "active",  "role": "async"},
        "image-agent":     {"status": "planned", "role": "multimodal", "eta": "V3"},
        "debug-agent":     {"status": "planned", "role": "debug",      "eta": "V2"},
        "voice-agent":     {"status": "planned", "role": "voice",      "eta": "V3"},
    }

    return {
        "ok": True,
        "data": {
            "modalities": caps.get("modalities", {}),
            "roles":      ["dev", "cyber", "business", "saas", "research"],
            "agents":     _AGENT_REGISTRY,
            "summary": {
                "active_agents":     sum(1 for a in _AGENT_REGISTRY.values() if a["status"] == "active"),
                "planned_agents":    sum(1 for a in _AGENT_REGISTRY.values() if a["status"] == "planned"),
                "active_modalities": caps.get("active", ["text"]),
            },
            "version":      "2.0",
            "phase":        10,
            "generated_at": time.time(),
        },
    }

@router.get("/diagnostic")
async def system_diagnostic(
    x_jarvis_token: str = Header(None, alias="X-Jarvis-Token"),
    authorization: str = Header(None),
):
    """Run internal diagnostic: LLM, tools, memory, queue, errors."""
    _check_auth(x_jarvis_token, authorization)
    report = {"timestamp": time.time(), "checks": {}}

    # 1. LLM connectivity
    try:
        from core.llm_factory import LLMFactory
        from config.settings import get_settings
        factory = LLMFactory(get_settings())
        llm = factory.get("fast")
        report["checks"]["llm"] = {
            "status": "ok" if llm else "degraded",
            "provider": getattr(llm, "_jarvis_provider", "unknown") if llm else "none",
        }
    except Exception as e:
        report["checks"]["llm"] = {"status": "error", "error": str(e)[:100]}

    # 2. Tool availability
    try:
        from core.capabilities.registry import get_capability_registry
        reg = get_capability_registry()
        stats = reg.stats()
        report["checks"]["tools"] = {"status": "ok", **stats}
    except Exception as e:
        report["checks"]["tools"] = {"status": "error", "error": str(e)[:100]}

    # 3. Memory integrity
    try:
        from core.memory.memory_schema import get_memory_store
        store = get_memory_store()
        mem_stats = store.stats()
        integrity = store.integrity_check() if hasattr(store, 'integrity_check') else {"ok": True}
        status = "ok" if integrity.get("ok", True) else "degraded"
        report["checks"]["memory"] = {"status": status, **mem_stats, "integrity": integrity}
    except Exception as e:
        report["checks"]["memory"] = {"status": "error", "error": str(e)[:100]}

    # 4. Mission queue backlog
    try:
        from core.mission_system import get_mission_system
        ms = get_mission_system()
        all_missions = list(ms._missions.values())
        pending = sum(1 for m in all_missions if str(m.status) == "PENDING_VALIDATION" or getattr(m.status, "value", str(m.status)) == "PENDING_VALIDATION")
        running = sum(1 for m in all_missions if str(getattr(m.status, "value", m.status)) in ("APPROVED", "EXECUTING"))
        done = sum(1 for m in all_missions if str(getattr(m.status, "value", m.status)) in ("DONE", "COMPLETED"))
        report["checks"]["queue"] = {
            "status": "ok",
            "total": len(all_missions),
            "pending_validation": pending,
            "running": running,
            "completed": done,
        }
    except Exception as e:
        report["checks"]["queue"] = {"status": "error", "error": str(e)[:100]}

    # 5. Uptime
    report["checks"]["uptime"] = {
        "status": "ok",
        "seconds": int(time.time() - _start_time),
    }

    # Overall verdict
    statuses = [c.get("status", "error") for c in report["checks"].values()]
    report["verdict"] = "healthy" if all(s == "ok" for s in statuses) else "degraded"

    return {"ok": True, "data": report}



# ── AI OS Manifest endpoint ─────────────────────────────────────────────────

@router.get("/aios/trace-analysis")
async def aios_trace_analysis(
    x_jarvis_token: str = Header(None, alias="X-Jarvis-Token"),
    authorization: str = Header(None),
):
    """AI OS trace intelligence — error patterns and capability reliability."""
    _check_auth(x_jarvis_token, authorization)
    from core.observability.trace_intelligence import error_patterns, capability_reliability
    return {"ok": True, "data": {
        "error_patterns": error_patterns(limit=50),
        "capability_reliability": capability_reliability(),
    }}

@router.get("/aios/capabilities")
async def aios_capabilities(
    x_jarvis_token: str = Header(None, alias="X-Jarvis-Token"),
    authorization: str = Header(None),
):
    """AI OS capability inventory."""
    _check_auth(x_jarvis_token, authorization)
    from core.capabilities.ai_os_capabilities import AIOS_CAPABILITIES
    return {"ok": True, "data": {
        "capabilities": [c.to_dict() for c in AIOS_CAPABILITIES.values()],
        "total": len(AIOS_CAPABILITIES),
    }}

@router.get("/aios/tools")
async def aios_tools(
    x_jarvis_token: str = Header(None, alias="X-Jarvis-Token"),
    authorization: str = Header(None),
):
    """AI OS tool inventory."""
    _check_auth(x_jarvis_token, authorization)
    from core.tools.tool_os_layer import TOOL_OS_REGISTRY
    return {"ok": True, "data": {
        "tools": [t.to_dict() for t in TOOL_OS_REGISTRY.values()],
        "total": len(TOOL_OS_REGISTRY),
    }}

@router.get("/aios/memory")
async def aios_memory(
    x_jarvis_token: str = Header(None, alias="X-Jarvis-Token"),
    authorization: str = Header(None),
):
    """AI OS memory layer stats."""
    _check_auth(x_jarvis_token, authorization)
    from core.memory.memory_layers import get_memory_layer
    ml = get_memory_layer()
    return {"ok": True, "data": ml.stats()}

@router.get("/aios/agents")
async def aios_agents(
    x_jarvis_token: str = Header(None, alias="X-Jarvis-Token"),
    authorization: str = Header(None),
):
    """AI OS agent role map."""
    _check_auth(x_jarvis_token, authorization)
    from core.agents.role_definitions import list_roles, agent_role_map
    return {"ok": True, "data": {
        "roles": list_roles(),
        "agent_map": agent_role_map(),
    }}

@router.get("/aios/policy")
async def aios_policy(
    x_jarvis_token: str = Header(None, alias="X-Jarvis-Token"),
    authorization: str = Header(None),
):
    """AI OS policy profile status."""
    _check_auth(x_jarvis_token, authorization)
    from core.policy.control_profiles import get_active_profile, list_profiles
    active = get_active_profile()
    return {"ok": True, "data": {
        "active_profile": active.to_dict(),
        "profiles": list_profiles(),
    }}

@router.get("/aios/semantic-router")
async def aios_semantic_router(
    x_jarvis_token: str = Header(None, alias="X-Jarvis-Token"),
    authorization: str = Header(None),
):
    """AI OS semantic router stats."""
    _check_auth(x_jarvis_token, authorization)
    from core.capabilities.semantic_router import router_stats
    return {"ok": True, "data": router_stats()}

@router.get("/aios/vector-memory")
async def aios_vector_memory(
    x_jarvis_token: str = Header(None, alias="X-Jarvis-Token"),
    authorization: str = Header(None),
):
    """AI OS vector memory stats."""
    _check_auth(x_jarvis_token, authorization)
    from core.memory.vector_memory import get_vector_memory
    return {"ok": True, "data": get_vector_memory().stats()}

@router.get("/aios/recovery")
async def aios_recovery(
    x_jarvis_token: str = Header(None, alias="X-Jarvis-Token"),
    authorization: str = Header(None),
):
    """AI OS recovery engine stats."""
    _check_auth(x_jarvis_token, authorization)
    from core.resilience.recovery_engine import get_recovery_engine
    return {"ok": True, "data": get_recovery_engine().stats()}

@router.get("/aios/agents/registry")
async def aios_agent_registry(
    x_jarvis_token: str = Header(None, alias="X-Jarvis-Token"),
    authorization: str = Header(None),
):
    """AI OS agent registry with performance tracking."""
    _check_auth(x_jarvis_token, authorization)
    from core.agents.agent_registry import get_agent_registry
    return {"ok": True, "data": get_agent_registry().stats()}

@router.get("/aios/connectors")
async def aios_connectors(
    x_jarvis_token: str = Header(None, alias="X-Jarvis-Token"),
    authorization: str = Header(None),
):
    """AI OS connector framework status."""
    _check_auth(x_jarvis_token, authorization)
    from core.connectors.connector_framework import get_connector_framework
    return {"ok": True, "data": get_connector_framework().stats()}

@router.get("/aios/knowledge")
async def aios_knowledge(
    x_jarvis_token: str = Header(None, alias="X-Jarvis-Token"),
    authorization: str = Header(None),
):
    """AI OS knowledge ingestion stats."""
    _check_auth(x_jarvis_token, authorization)
    from core.knowledge.ingest_pipeline import get_ingest_pipeline
    return {"ok": True, "data": get_ingest_pipeline().stats()}

@router.get("/aios/research-loop")
async def aios_research_loop(
    x_jarvis_token: str = Header(None, alias="X-Jarvis-Token"),
    authorization: str = Header(None),
):
    """AI OS research loop stats."""
    _check_auth(x_jarvis_token, authorization)
    from core.self_improvement.research_loop import get_research_loop
    return {"ok": True, "data": get_research_loop().stats()}

@router.get("/aios/skills")
async def aios_skills(
    x_jarvis_token: str = Header(None, alias="X-Jarvis-Token"),
    authorization: str = Header(None),
):
    """AI OS skill registry with performance tracking."""
    _check_auth(x_jarvis_token, authorization)
    from core.skills.skill_discovery import get_skill_discovery
    sd = get_skill_discovery()
    return {"ok": True, "data": sd.dashboard_stats()}

@router.get("/aios/status")
async def aios_status(
    x_jarvis_token: str = Header(None, alias="X-Jarvis-Token"),
    authorization: str = Header(None),
):
    """AI OS consolidated dashboard — full system introspection."""
    _check_auth(x_jarvis_token, authorization)
    import time as _time

    status: dict = {"ok": True, "timestamp": _time.time(), "data": {}}
    d = status["data"]

    # 1. Capabilities
    try:
        from core.capabilities.ai_os_capabilities import capability_summary
        d["capabilities"] = capability_summary()
    except Exception as e:
        d["capabilities"] = {"error": str(e)[:100]}

    # 2. Tools
    try:
        from core.tool_executor import get_tool_executor
        te = get_tool_executor()
        tools = te.list_tools()
        d["tools"] = {"total": len(tools), "names": tools}
    except Exception as e:
        d["tools"] = {"error": str(e)[:100]}

    # 3. Memory stats
    try:
        from core.memory.memory_layers import get_memory_layer
        d["memory"] = get_memory_layer().stats()
    except Exception as e:
        d["memory"] = {"error": str(e)[:100]}

    # 4. Vector memory
    try:
        from core.memory.vector_memory import get_vector_memory
        d["vector_memory"] = get_vector_memory().stats()
    except Exception as e:
        d["vector_memory"] = {"error": str(e)[:100]}

    # 5. Policy profile
    try:
        from core.policy.control_profiles import get_active_profile, list_profiles
        active = get_active_profile()
        d["policy"] = {"active": active.name, "profiles": list_profiles()}
    except Exception as e:
        d["policy"] = {"error": str(e)[:100]}

    # 6. Recent missions
    try:
        ms = _mission_system()
        missions = ms.list_missions(limit=10)
        total = len(missions)
        done = sum(1 for m in missions if m.status in ("DONE", "COMPLETED"))
        failed = sum(1 for m in missions if m.status in ("FAILED",))
        d["missions"] = {
            "recent": total,
            "success_rate": round(done / total, 2) if total else 0,
            "done": done, "failed": failed,
            "statuses": {s: sum(1 for m in missions if m.status == s)
                         for s in set(m.status for m in missions)},
        }
    except Exception as e:
        d["missions"] = {"error": str(e)[:100]}

    # 7. Semantic router
    try:
        from core.capabilities.semantic_router import router_stats
        d["semantic_router"] = router_stats()
    except Exception as e:
        d["semantic_router"] = {"error": str(e)[:100]}

    # 8. Recovery engine
    try:
        from core.resilience.recovery_engine import get_recovery_engine
        d["recovery"] = get_recovery_engine().stats()
    except Exception as e:
        d["recovery"] = {"error": str(e)[:100]}

    # 9. Agent roles
    try:
        from core.agents.role_definitions import list_roles, agent_role_map
        d["agents"] = {"roles": list_roles(), "map": agent_role_map()}
    except Exception as e:
        d["agents"] = {"error": str(e)[:100]}

    # 10. Skills
    try:
        from core.skills.skill_discovery import get_skill_discovery
        sd = get_skill_discovery()
        d["skills"] = sd.dashboard_stats()
    except Exception as e:
        d["skills"] = {"error": str(e)[:100]}

    # 11. Self-improvement safety
    try:
        from core.self_improvement.safety_boundary import PROTECTED_RUNTIME, ALLOWED_SCOPE
        d["self_improvement"] = {
            "protected_files": len(PROTECTED_RUNTIME),
            "allowed_scopes": len(ALLOWED_SCOPE),
        }
    except Exception as e:
        d["self_improvement"] = {"error": str(e)[:100]}

    # 12a. Connectors
    try:
        from core.connectors.connector_framework import get_connector_framework
        d["connectors"] = get_connector_framework().stats()
    except Exception as e:
        d["connectors"] = {"error": str(e)[:100]}

    # 12b. Knowledge
    try:
        from core.knowledge.ingest_pipeline import get_ingest_pipeline
        d["knowledge"] = get_ingest_pipeline().stats()
    except Exception as e:
        d["knowledge"] = {"error": str(e)[:100]}

    # 12. Model usage
    try:
        import os
        d["models"] = {
            "default_provider": os.getenv("JARVIS_DEFAULT_PROVIDER", "openrouter"),
            "fast_model": os.getenv("JARVIS_FAST_MODEL", "gpt-4o-mini"),
            "heavy_model": os.getenv("JARVIS_ORCHESTRATOR_MODEL", "claude-sonnet-4-20250514"),
        }
    except Exception as e:
        d["models"] = {"error": str(e)[:100]}

    return status

@router.get("/aios/manifest")
async def aios_manifest(
    x_jarvis_token: str = Header(None, alias="X-Jarvis-Token"),
    authorization: str = Header(None),
):
    """Full AI OS manifest — capabilities, tools, memory, agents, policies."""
    _check_auth(x_jarvis_token, authorization)
    from core.aios_manifest import get_manifest
    return {"ok": True, "data": get_manifest()}

@router.get("/aios/consistency")
async def aios_consistency(
    x_jarvis_token: str = Header(None, alias="X-Jarvis-Token"),
    authorization: str = Header(None),
):
    """AI OS consistency check."""
    _check_auth(x_jarvis_token, authorization)
    from core.aios_manifest import consistency_check
    return {"ok": True, "data": consistency_check()}
