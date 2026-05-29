"""
core/self_model/updater.py — Assembles the Self-Model from runtime sources.

The Updater reads from all sources and builds a complete SelfModel snapshot.
It never modifies any source — pure aggregation.

Usage:
    from core.self_model.updater import build_self_model
    model = build_self_model()  # Returns SelfModel with all dimensions populated
"""
from __future__ import annotations

import time
import structlog

from core.self_model.model import (
    SelfModel, CapabilityEntry, CapabilityStatus,
    ComponentEntry, ComponentStatus,
    HealthSignal, HealthStatus,
    ModificationBoundary, ModificationZone,
    AutonomyEnvelope, AutonomyMode,
)
from core.self_model import sources
_silent_log = __import__("structlog").get_logger(__name__)

log = structlog.get_logger()


# ── Capability mapping ────────────────────────────────────────────────────────

def _map_capability_status(raw: dict) -> CapabilityStatus:
    """Map raw capability graph entry to a CapabilityStatus."""
    constraints = raw.get("constraints", [])
    if isinstance(constraints, list):
        if "disabled" in constraints:
            return CapabilityStatus.UNAVAILABLE
        if "requires_approval" in constraints:
            return CapabilityStatus.APPROVAL_REQUIRED
        if "risk:critical" in constraints:
            return CapabilityStatus.APPROVAL_REQUIRED
    # Check reliability
    reliability = raw.get("reliability", 0.0)
    if reliability > 0 and reliability < 0.5:
        return CapabilityStatus.DEGRADED
    if raw.get("source") == "mcp" and raw.get("status") == "needs_setup":
        return CapabilityStatus.NOT_CONFIGURED
    return CapabilityStatus.READY


def _build_capabilities() -> dict[str, CapabilityEntry]:
    """Build capability entries from the capability graph."""
    capabilities: dict[str, CapabilityEntry] = {}
    try:
        raw_caps = sources.read_capability_graph()
        for cap in raw_caps:
            cap_id = cap.get("id", cap.get("name", ""))
            if not cap_id:
                continue
            status = _map_capability_status(cap)
            constraints = cap.get("constraints", [])
            capabilities[cap_id] = CapabilityEntry(
                id=cap_id,
                name=cap.get("name", cap_id),
                status=status,
                source=cap.get("source", "unknown"),
                confidence=cap.get("reliability", 0.0),
                risk_level=_extract_risk(constraints),
                dependencies=cap.get("dependencies", []),
                constraints=constraints if isinstance(constraints, list) else [],
                usage_count=cap.get("usage_count", 0),
                failure_count=cap.get("failure_count", 0),
            )
    except Exception as e:
        log.debug("self_model.updater.capabilities_failed", err=str(e)[:80])
    return capabilities


def _extract_risk(constraints: list) -> str:
    """Extract risk level from constraints list."""
    if not isinstance(constraints, list):
        return "low"
    for c in constraints:
        if isinstance(c, str) and c.startswith("risk:"):
            return c.split(":", 1)[1]
    return "low"


# ── Component mapping ─────────────────────────────────────────────────────────

_MCP_STATUS_MAP = {
    "READY": ComponentStatus.READY,
    "DISABLED": ComponentStatus.DISABLED,
    "NEEDS_SETUP": ComponentStatus.NOT_CONFIGURED,
    "RESTRICTED": ComponentStatus.APPROVAL_REQUIRED,
    "ERROR": ComponentStatus.ERROR,
}


def _build_components() -> dict[str, ComponentEntry]:
    """Build component entries from MCP registry, modules, and tool permissions."""
    components: dict[str, ComponentEntry] = {}

    # MCP servers
    try:
        for mcp in sources.read_mcp_registry():
            mcp_id = mcp.get("id", mcp.get("name", ""))
            if not mcp_id:
                continue
            raw_status = mcp.get("health", mcp.get("status", "DISABLED"))
            status = _MCP_STATUS_MAP.get(str(raw_status).upper(), ComponentStatus.UNAVAILABLE)
            components[mcp_id] = ComponentEntry(
                id=mcp_id,
                type="mcp",
                status=status,
                reason=mcp.get("reason", ""),
                required_secrets=mcp.get("required_secrets", []),
                missing_secrets=mcp.get("missing_secrets", []),
                spawnable=mcp.get("spawnable", False),
                trust_level=mcp.get("trust_level", ""),
            )
    except Exception as e:
        log.debug("self_model.updater.mcp_components_failed", err=str(e)[:80])

    # Tool permissions (gated tools)
    try:
        for tool in sources.read_tool_permissions():
            tool_name = tool.get("tool", tool.get("tool_name", ""))
            if not tool_name:
                continue
            tool_id = f"tool:{tool_name}"
            approved = tool.get("approved", False)
            components[tool_id] = ComponentEntry(
                id=tool_id,
                type="tool",
                status=ComponentStatus.READY if approved else ComponentStatus.APPROVAL_REQUIRED,
                reason="Gated tool" if not approved else "",
            )
    except Exception as e:
        log.debug("self_model.updater.tool_components_failed", err=str(e)[:80])

    # Connectors from module manager
    try:
        modules = sources.read_modules()
        for conn in modules.get("connector", []):
            conn_id = conn.get("id", conn.get("name", ""))
            if not conn_id:
                continue
            enabled = conn.get("enabled", False)
            components[f"connector:{conn_id}"] = ComponentEntry(
                id=f"connector:{conn_id}",
                type="connector",
                status=ComponentStatus.READY if enabled else ComponentStatus.DISABLED,
            )
    except Exception as e:
        log.debug("self_model.updater.connector_components_failed", err=str(e)[:80])

    return components


# ── Health signals ────────────────────────────────────────────────────────────

def _build_health() -> dict[str, HealthSignal]:
    """Build health signals from system probes."""
    now = time.time()
    signals: dict[str, HealthSignal] = {}

    probes = {
        "auth_system": sources.probe_auth_health,
        "cognitive_graph": sources.probe_cognitive_health,
        "si_pipeline": sources.probe_si_pipeline_health,
        "mission_system": sources.probe_mission_system_health,
        "docker_runtime": sources.probe_docker_health,
    }

    for name, probe_fn in probes.items():
        try:
            result = probe_fn()
            healthy = result.get("healthy", False)
            detail = result.get("error", "") if not healthy else ""
            if not detail and healthy:
                # Build a useful detail string from result
                detail = ", ".join(f"{k}={v}" for k, v in result.items() if k != "healthy")
            signals[name] = HealthSignal(
                name=name,
                status=HealthStatus.HEALTHY if healthy else HealthStatus.DEGRADED,
                detail=detail[:200],
                checked_at=now,
            )
        except Exception as e:
            signals[name] = HealthSignal(
                name=name,
                status=HealthStatus.UNKNOWN,
                detail=f"Probe failed: {str(e)[:80]}",
                checked_at=now,
            )

    # Capability graph populated?
    try:
        caps = sources.read_capability_graph()
        signals["capability_graph"] = HealthSignal(
            name="capability_graph",
            status=HealthStatus.HEALTHY if len(caps) > 0 else HealthStatus.DEGRADED,
            detail=f"{len(caps)} capabilities" if caps else "empty",
            checked_at=now,
        )
    except Exception:
        signals["capability_graph"] = HealthSignal(
            name="capability_graph",
            status=HealthStatus.UNKNOWN,
            checked_at=now,
        )

    return signals


# ── Modification boundaries ───────────────────────────────────────────────────

def _build_boundaries() -> list[ModificationBoundary]:
    """Build modification boundaries from protected paths and conventions."""
    boundaries = []
    protected = sources.read_protected_paths()

    # Allowed zone
    boundaries.append(ModificationBoundary(
        zone=ModificationZone.ALLOWED,
        description="Safe for autonomous modification via SI pipeline",
        paths=[],
        examples=[
            "prompt tuning",
            "orchestration parameters",
            "module configuration",
            "sandbox patch proposals",
            "test additions",
            "documentation updates",
        ],
    ))

    # Restricted zone — protected paths
    boundaries.append(ModificationBoundary(
        zone=ModificationZone.RESTRICTED,
        description="Protected kernel paths — requires human approval",
        paths=protected.get("files", []) + protected.get("dirs", []),
        examples=[
            "core/meta_orchestrator.py",
            "core/tool_executor.py",
            "core/policy_engine.py",
            "api/auth.py",
            "config/settings.py",
        ],
    ))

    # Forbidden zone — never modify
    boundaries.append(ModificationBoundary(
        zone=ModificationZone.FORBIDDEN,
        description="Never modify — integrity-critical",
        paths=[".env", "docker-compose.yml"],
        examples=[
            "secret storage encryption logic",
            "audit log integrity",
            "event hash chain",
        ],
    ))

    return boundaries


# ── Autonomy envelope ─────────────────────────────────────────────────────────

def _build_autonomy() -> AutonomyEnvelope:
    """Build autonomy envelope from runtime config."""
    config = sources.read_autonomy_config()

    mode_map = {
        "observe": AutonomyMode.OBSERVE,
        "propose_only": AutonomyMode.PROPOSE_ONLY,
        "supervised_execute": AutonomyMode.SUPERVISED_EXECUTE,
        "sandbox_self_improve": AutonomyMode.SANDBOX_SELF_IMPROVE,
        "restricted_autonomous": AutonomyMode.RESTRICTED_AUTONOMOUS,
    }

    return AutonomyEnvelope(
        mode=mode_map.get(config.get("mode", ""), AutonomyMode.SUPERVISED_EXECUTE),
        requires_approval_for_tools=True,
        requires_approval_for_code_patch=True,
        requires_approval_for_external_calls=True,
        requires_approval_for_deployment=True,
        max_risk_auto_approve=config.get("max_risk_auto", "low"),
        max_files_per_patch=config.get("max_files_per_patch", 3),
        max_steps_per_mission=config.get("max_steps", 50),
    )


# ── Main builder ──────────────────────────────────────────────────────────────

def build_self_model() -> SelfModel:
    """
    Build a complete Self-Model snapshot from all runtime sources.

    This is the primary entry point. Each dimension is built independently
    and fail-open — a failure in one source doesn't block the others.
    """
    start = time.monotonic()

    model = SelfModel()
    model.capabilities = _build_capabilities()
    model.components = _build_components()
    model.health = _build_health()
    model.boundaries = _build_boundaries()
    model.autonomy = _build_autonomy()
    model.generation_duration_ms = (time.monotonic() - start) * 1000

    # Enrich with canonical agent architecture (fail-open)
    try:
        from core.agents.canonical_agents import get_canonical_runtime
        runtime = get_canonical_runtime()
        model.metadata = runtime.enrich_self_model(getattr(model, "metadata", {}) or {})
    except Exception:
        _silent_log.debug("suppressed_exception", src='updater.py')

    log.info(
        "self_model.built",
        capabilities=len(model.capabilities),
        components=len(model.components),
        health_signals=len(model.health),
        boundaries=len(model.boundaries),
        duration_ms=round(model.generation_duration_ms, 1),
    )

    return model
