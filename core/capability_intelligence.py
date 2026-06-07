"""
BEA MAX — Capability Intelligence Layer
=============================================
Foundational system for Bea to understand what it CAN do.

Parts:
1. Tool Semantic Profiling — structured tool descriptions with semantic tags
2. Capability Graph — tool → capability → domain → mission category
3. Auto-Discovery Engine — detect new, missing, and duplicate tools
4. Tool Reliability Profiling — passive success/failure/timeout signals
5. Capability Matching Heuristics — goal → ranked tool suggestions
6. Capability Gap Detection — identify missing abilities

All functions are fail-open. No orchestration changes. Purely additive.
Zero external dependencies (stdlib + optional structlog).

Usage:
    from core.capability_intelligence import (
        get_tool_profiles,
        get_capability_graph,
        run_auto_discovery,
        get_tool_reliability,
        match_capabilities,
        detect_capability_gaps,
        export_artifacts,
    )
"""
from __future__ import annotations

import structlog
log = structlog.get_logger(__name__)

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    import structlog
    log = structlog.get_logger(__name__)
except ImportError:
    log = structlog.get_logger(__name__)

REPO_ROOT = Path(os.environ.get("BEAMAX_REPO", ".")).resolve()


# ═══════════════════════════════════════════════════════════════
# PART 1 — TOOL SEMANTIC PROFILING
# ═══════════════════════════════════════════════════════════════

# Semantic tag taxonomy
SEMANTIC_TAGS = {
    "filesystem":           ["read_file", "write_file", "write_file_safe", "list_directory",
                             "search_in_files", "replace_in_file", "file_create", "file_delete_safe",
                             "create_directory", "list_project_structure", "count_lines",
                             "workspace_snapshot"],
    "network":              ["fetch_url", "http_get", "http_post_json", "check_url_status",
                             "doc_fetch", "search_pypi", "fetch_github_readme",
                             "api_healthcheck", "test_endpoint"],
    "code_generation":      ["build_complete_tool", "generate_tool_skeleton", "generate_tool_tests",
                             "python_snippet"],
    "analysis":             ["dependency_analyzer", "code_search_multi_file", "api_schema_generator",
                             "env_checker", "requirements_validator", "analyze_tool_need",
                             "search_codebase", "system_health_check"],
    "version_control":      ["git_status", "git_diff", "git_log", "git_branch", "git_commit",
                             "git_push", "git_pull", "git_branch_create", "git_checkout"],
    "container":            ["docker_ps", "docker_logs", "docker_restart", "docker_inspect",
                             "docker_compose_build", "docker_compose_up", "docker_compose_down"],
    "testing":              ["run_unit_tests", "run_smoke_tests", "api_healthcheck", "test_endpoint"],
    "memory":               ["memory_store_solution", "memory_store_error", "memory_store_patch",
                             "memory_search_similar", "memory_store_with_ttl",
                             "memory_cleanup_expired", "memory_deduplicate", "memory_summarize_recent",
                             "vector_search"],
    "system_modification":  ["shell_command", "run_command_safe", "docker_restart",
                             "docker_compose_up", "docker_compose_down", "docker_compose_build",
                             "git_push", "git_commit", "replace_in_file", "file_delete_safe"],
    "data_processing":      ["check_api_fields", "sync_app_fields"],
    "reasoning":            ["analyze_tool_need"],
    "external_api":         ["fetch_url", "http_get", "http_post_json", "search_pypi",
                             "fetch_github_readme"],
}

# Reverse index: tool → set of tags
_TOOL_TO_TAGS: dict[str, set[str]] = {}
for _tag, _tools in SEMANTIC_TAGS.items():
    for _tool in _tools:
        _TOOL_TO_TAGS.setdefault(_tool, set()).add(_tag)


# Side-effect risk levels
SIDE_EFFECT_RISK: dict[str, str] = {
    "none":       "no side effects — pure read/analysis",
    "low":        "writes to local files only, rollback available",
    "medium":     "modifies system state (git, memory, config)",
    "high":       "network calls, container control, data mutation",
    "critical":   "destructive actions (delete, push to remote, restart services)",
}

_TOOL_SIDE_EFFECTS: dict[str, str] = {}
for _tool_name in _TOOL_TO_TAGS:
    tags = _TOOL_TO_TAGS[_tool_name]
    if "system_modification" in tags:
        if any(kw in _tool_name for kw in ("delete", "push", "restart", "down")):
            _TOOL_SIDE_EFFECTS[_tool_name] = "critical"
        else:
            _TOOL_SIDE_EFFECTS[_tool_name] = "high"
    elif "network" in tags or "external_api" in tags:
        _TOOL_SIDE_EFFECTS[_tool_name] = "medium"
    elif "filesystem" in tags and any(kw in _tool_name for kw in ("write", "create", "replace")):
        _TOOL_SIDE_EFFECTS[_tool_name] = "low"
    else:
        _TOOL_SIDE_EFFECTS[_tool_name] = "none"


@dataclass
class ToolProfile:
    """Semantic profile of a single tool.

    Attributes:
        name: Tool identifier.
        description: Human-readable description.
        semantic_tags: List of semantic categories (filesystem, network, etc.).
        side_effect_risk: none | low | medium | high | critical.
        dependencies: Required Python modules.
        input_schema: Description of expected inputs.
        output_schema: Description of expected outputs.
        requires_network: Whether the tool needs network access.
        idempotent: Whether repeated calls produce the same result.
        cost: Estimated execution cost (1-5).
        timeout_s: Default timeout in seconds.
    """
    name:              str
    description:       str = ""
    semantic_tags:     list[str] = field(default_factory=list)
    side_effect_risk:  str = "none"
    dependencies:      list[str] = field(default_factory=list)
    input_schema:      str = ""
    output_schema:     str = ""
    requires_network:  bool = False
    idempotent:        bool = True
    cost:              int = 1
    timeout_s:         int = 10

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "semantic_tags": self.semantic_tags,
            "side_effect_risk": self.side_effect_risk,
            "dependencies": self.dependencies,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "requires_network": self.requires_network,
            "idempotent": self.idempotent,
            "cost": self.cost,
            "timeout_s": self.timeout_s,
        }


def _get_tool_dependencies(tool_name: str) -> list[str]:
    """Infer Python module dependencies for a tool."""
    deps_map = {
        "network":       ["requests"],
        "external_api":  ["requests"],
        "memory":        ["qdrant_client"],
        "container":     [],  # docker binary, not Python
        "version_control": [],  # git binary
    }
    tags = _TOOL_TO_TAGS.get(tool_name, set())
    deps = set()
    for tag in tags:
        for d in deps_map.get(tag, []):
            deps.add(d)
    return sorted(deps)


def get_tool_profiles() -> list[ToolProfile]:
    """
    Build semantic profiles for all known tools.

    Merges data from:
    - core/tool_registry.py (ToolDefinition, _SEMANTIC_DESCRIPTIONS, _TOOL_COSTS)
    - core/tool_executor.py (_TOOL_TIMEOUTS, _TOOL_REQUIRED_PARAMS)
    - Semantic tag taxonomy (this module)

    Returns list of ToolProfile, one per known tool.
    Never raises — unknown tools get minimal profiles.
    """
    profiles = []
    try:
        # Gather data from tool_registry
        from core.tool_registry import (
            _SEMANTIC_DESCRIPTIONS, _TOOL_COSTS,
            _EXECUTOR_TIMEOUTS, _EXECUTOR_REQUIRED_PARAMS,
            get_tool_registry,
        )
        reg = get_tool_registry()
        reg_tools = {t.name: t for t in reg.list_tools()}

        # All known tool names (union of all sources)
        all_names = sorted(
            set(_SEMANTIC_DESCRIPTIONS.keys())
            | set(reg_tools.keys())
            | set(_TOOL_TO_TAGS.keys())
        )

        for name in all_names:
            desc = _SEMANTIC_DESCRIPTIONS.get(name, "")
            tags = sorted(_TOOL_TO_TAGS.get(name, set()))
            risk = _TOOL_SIDE_EFFECTS.get(name, "none")
            deps = _get_tool_dependencies(name)
            cost = _TOOL_COSTS.get(name, 3)
            timeout = _EXECUTOR_TIMEOUTS.get(name, 10)
            req_params = _EXECUTOR_REQUIRED_PARAMS.get(name, [])

            # Enrich from ToolDefinition if available
            reg_tool = reg_tools.get(name)
            input_schema = ", ".join(req_params) if req_params else ""
            output_schema = ""
            requires_net = False
            idempotent = True
            if reg_tool:
                input_schema = input_schema or reg_tool.expected_input
                output_schema = reg_tool.expected_output
                requires_net = reg_tool.requires_network
                idempotent = reg_tool.idempotent
                if not desc:
                    desc = reg_tool.description
            elif "network" in tags or "external_api" in tags:
                requires_net = True
            if risk in ("high", "critical"):
                idempotent = False

            profiles.append(ToolProfile(
                name=name,
                description=desc,
                semantic_tags=tags,
                side_effect_risk=risk,
                dependencies=deps,
                input_schema=input_schema,
                output_schema=output_schema,
                requires_network=requires_net,
                idempotent=idempotent,
                cost=cost,
                timeout_s=timeout,
            ))

    except Exception as e:
        log.debug("tool_profile_build_degraded", err=str(e)[:100])
        # Fallback: build from tag taxonomy only
        for name in sorted(_TOOL_TO_TAGS.keys()):
            profiles.append(ToolProfile(
                name=name,
                semantic_tags=sorted(_TOOL_TO_TAGS.get(name, set())),
                side_effect_risk=_TOOL_SIDE_EFFECTS.get(name, "none"),
                dependencies=_get_tool_dependencies(name),
            ))

    return profiles


# ═══════════════════════════════════════════════════════════════
# PART 2 — CAPABILITY GRAPH
# ═══════════════════════════════════════════════════════════════

# Normalized ontology: tool → capability → domain → mission_category
_CAPABILITY_MAP: dict[str, str] = {
    # Filesystem tools → filesystem capabilities
    "read_file":              "filesystem_read",
    "write_file":             "filesystem_write",
    "write_file_safe":        "filesystem_write",
    "list_directory":         "filesystem_read",
    "search_in_files":        "filesystem_search",
    "replace_in_file":        "filesystem_write",
    "file_create":            "filesystem_write",
    "file_delete_safe":       "filesystem_delete",
    "create_directory":       "filesystem_write",
    "list_project_structure": "filesystem_read",
    "count_lines":            "filesystem_read",
    "workspace_snapshot":     "filesystem_read",
    # Version control
    "git_status":             "vcs_inspect",
    "git_diff":               "vcs_inspect",
    "git_log":                "vcs_inspect",
    "git_branch":             "vcs_inspect",
    "git_commit":             "vcs_mutate",
    "git_push":               "vcs_publish",
    "git_pull":               "vcs_sync",
    "git_branch_create":      "vcs_mutate",
    "git_checkout":           "vcs_mutate",
    # Network / API
    "fetch_url":              "http_read",
    "http_get":               "http_read",
    "http_post_json":         "http_write",
    "check_url_status":       "http_read",
    "doc_fetch":              "http_read",
    "search_pypi":            "package_search",
    "fetch_github_readme":    "http_read",
    "api_healthcheck":        "http_read",
    "test_endpoint":          "http_read",
    # Code generation
    "build_complete_tool":    "code_generate",
    "generate_tool_skeleton": "code_generate",
    "generate_tool_tests":    "code_generate",
    "python_snippet":         "code_execute",
    # Analysis
    "dependency_analyzer":    "code_analyze",
    "code_search_multi_file": "code_analyze",
    "api_schema_generator":   "code_analyze",
    "env_checker":            "env_inspect",
    "requirements_validator": "env_inspect",
    "analyze_tool_need":      "meta_reasoning",
    "search_codebase":        "code_analyze",
    "system_health_check":    "env_inspect",
    # Container
    "docker_ps":              "container_inspect",
    "docker_logs":            "container_inspect",
    "docker_restart":         "container_control",
    "docker_inspect":         "container_inspect",
    "docker_compose_build":   "container_control",
    "docker_compose_up":      "container_control",
    "docker_compose_down":    "container_control",
    # Testing
    "run_unit_tests":         "test_execute",
    "run_smoke_tests":        "test_execute",
    # Memory
    "memory_store_solution":  "memory_write",
    "memory_store_error":     "memory_write",
    "memory_store_patch":     "memory_write",
    "memory_search_similar":  "memory_read",
    "memory_store_with_ttl":  "memory_write",
    "memory_cleanup_expired": "memory_manage",
    "memory_deduplicate":     "memory_manage",
    "memory_summarize_recent":"memory_read",
    "vector_search":          "memory_read",
    # System
    "shell_command":          "system_execute",
    "run_command_safe":       "system_execute",
    # Data processing
    "check_api_fields":       "data_validate",
    "sync_app_fields":        "data_sync",
}

_CAPABILITY_TO_DOMAIN: dict[str, str] = {
    "filesystem_read":    "filesystem",
    "filesystem_write":   "filesystem",
    "filesystem_search":  "filesystem",
    "filesystem_delete":  "filesystem",
    "vcs_inspect":        "version_control",
    "vcs_mutate":         "version_control",
    "vcs_publish":        "version_control",
    "vcs_sync":           "version_control",
    "http_read":          "networking",
    "http_write":         "networking",
    "package_search":     "networking",
    "code_generate":      "development",
    "code_execute":       "development",
    "code_analyze":       "development",
    "env_inspect":        "environment",
    "meta_reasoning":     "reasoning",
    "container_inspect":  "infrastructure",
    "container_control":  "infrastructure",
    "test_execute":       "quality_assurance",
    "memory_write":       "knowledge",
    "memory_read":        "knowledge",
    "memory_manage":      "knowledge",
    "system_execute":     "system_operations",
    "data_validate":      "data_management",
    "data_sync":          "data_management",
}

_DOMAIN_TO_MISSION: dict[str, list[str]] = {
    "filesystem":          ["coding_task", "debug_task", "system_task"],
    "version_control":     ["coding_task", "self_improvement_task"],
    "networking":          ["research_task", "system_task", "evaluation_task"],
    "development":         ["coding_task", "self_improvement_task"],
    "environment":         ["debug_task", "system_task"],
    "reasoning":           ["planning_task", "architecture_task"],
    "infrastructure":      ["system_task", "debug_task"],
    "quality_assurance":   ["coding_task", "evaluation_task"],
    "knowledge":           ["research_task", "self_improvement_task"],
    "system_operations":   ["system_task", "debug_task"],
    "data_management":     ["system_task", "coding_task"],
}


@dataclass
class CapabilityGraph:
    """The full capability ontology graph.

    Layers:
        tools → capabilities → domains → mission_categories
    """
    tool_to_capability:    dict[str, str] = field(default_factory=dict)
    capability_to_domain:  dict[str, str] = field(default_factory=dict)
    domain_to_missions:    dict[str, list[str]] = field(default_factory=dict)
    # Reverse indexes
    capability_to_tools:   dict[str, list[str]] = field(default_factory=dict)
    domain_to_capabilities: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "tool_to_capability": self.tool_to_capability,
            "capability_to_domain": self.capability_to_domain,
            "domain_to_missions": self.domain_to_missions,
            "capability_to_tools": dict(self.capability_to_tools),
            "domain_to_capabilities": dict(self.domain_to_capabilities),
            "stats": {
                "tools": len(self.tool_to_capability),
                "capabilities": len(set(self.tool_to_capability.values())),
                "domains": len(self.domain_to_missions),
            },
        }


def get_capability_graph() -> CapabilityGraph:
    """
    Build the capability graph from the normalized ontology.

    Returns a CapabilityGraph with forward and reverse indexes.
    Never raises.
    """
    try:
        graph = CapabilityGraph(
            tool_to_capability=dict(_CAPABILITY_MAP),
            capability_to_domain=dict(_CAPABILITY_TO_DOMAIN),
            domain_to_missions=dict(_DOMAIN_TO_MISSION),
        )
        # Build reverse indexes
        for tool, cap in _CAPABILITY_MAP.items():
            graph.capability_to_tools.setdefault(cap, []).append(tool)
        for cap, domain in _CAPABILITY_TO_DOMAIN.items():
            graph.domain_to_capabilities.setdefault(domain, []).append(cap)
        return graph
    except Exception as e:
        log.debug("capability_graph_build_failed", err=str(e)[:100])
        return CapabilityGraph()


def get_tools_for_capability(capability: str) -> list[str]:
    """Get all tools that provide a given capability."""
    graph = get_capability_graph()
    return graph.capability_to_tools.get(capability, [])


def get_capabilities_for_domain(domain: str) -> list[str]:
    """Get all capabilities in a domain."""
    graph = get_capability_graph()
    return graph.domain_to_capabilities.get(domain, [])


def get_tool_chain(tool_name: str) -> dict:
    """Trace a tool through the full capability chain.

    Returns:
        {"tool": "git_commit", "capability": "vcs_mutate",
         "domain": "version_control", "missions": ["coding_task", ...]}
    """
    cap = _CAPABILITY_MAP.get(tool_name, "unknown")
    domain = _CAPABILITY_TO_DOMAIN.get(cap, "unknown")
    missions = _DOMAIN_TO_MISSION.get(domain, [])
    return {
        "tool": tool_name,
        "capability": cap,
        "domain": domain,
        "missions": missions,
    }


# ═══════════════════════════════════════════════════════════════
# PART 3 — AUTO-DISCOVERY ENGINE
# ═══════════════════════════════════════════════════════════════

@dataclass
class DiscoveryReport:
    """Results of auto-discovery scan.

    Attributes:
        declared_tools: Tools defined in registry/taxonomy.
        available_tools: Tools whose dependencies are met.
        unavailable_tools: Tools with missing deps or binaries.
        unregistered_functions: Functions that look like tools but aren't in the registry.
        duplicate_capabilities: Tools with overlapping capabilities.
        timestamp: When the scan was performed.
    """
    declared_tools:       list[str] = field(default_factory=list)
    available_tools:      list[str] = field(default_factory=list)
    unavailable_tools:    list[dict] = field(default_factory=list)
    unregistered_functions: list[dict] = field(default_factory=list)
    duplicate_capabilities: list[dict] = field(default_factory=list)
    timestamp:            float = 0.0

    def to_dict(self) -> dict:
        return {
            "declared_tools": len(self.declared_tools),
            "available_tools": len(self.available_tools),
            "unavailable_tools": self.unavailable_tools,
            "unregistered_functions": self.unregistered_functions[:20],
            "duplicate_capabilities": self.duplicate_capabilities,
            "timestamp": self.timestamp,
        }


def run_auto_discovery() -> DiscoveryReport:
    """
    Safe auto-discovery of tool availability.

    Detects:
    - Tools declared but unavailable (missing deps)
    - Functions that look like tools but aren't registered
    - Duplicate capability coverage

    Fail-safe: returns partial report on any error.
    No behavior modification — observational only.
    """
    report = DiscoveryReport(timestamp=time.time())

    try:
        # 1. Declared tools
        all_tools = sorted(
            set(_CAPABILITY_MAP.keys()) | set(_TOOL_TO_TAGS.keys())
        )
        report.declared_tools = all_tools

        # 2. Check availability
        from core.runtime_introspection import check_tool_health
        for tool_name in all_tools:
            try:
                health = check_tool_health(tool_name)
                if health.status == "ok":
                    report.available_tools.append(tool_name)
                else:
                    report.unavailable_tools.append({
                        "tool": tool_name,
                        "status": health.status,
                        "reason": health.reason,
                    })
            except Exception:
                report.unavailable_tools.append({
                    "tool": tool_name,
                    "status": "unknown",
                    "reason": "health check failed",
                })

    except Exception as e:
        log.debug("auto_discovery_tools_failed", err=str(e)[:100])

    try:
        # 3. Scan for unregistered tool-like functions in core/tools/
        import ast
        tools_dir = REPO_ROOT / "core" / "tools"
        registered = set(report.declared_tools)
        if tools_dir.exists():
            for py_file in tools_dir.glob("*.py"):
                if py_file.name.startswith("_"):
                    continue
                try:
                    tree = ast.parse(py_file.read_text(encoding="utf-8", errors="replace"))
                    for node in ast.walk(tree):
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            if node.name.startswith("_"):
                                continue
                            if node.name not in registered:
                                report.unregistered_functions.append({
                                    "function": node.name,
                                    "file": str(py_file.relative_to(REPO_ROOT)),
                                    "line": node.lineno,
                                })
                except Exception:
                    log.debug("swallowed_exception", exc_info=True)
                    continue
    except Exception as e:
        log.debug("auto_discovery_scan_failed", err=str(e)[:100])

    try:
        # 4. Detect duplicate capabilities
        graph = get_capability_graph()
        for cap, tools in graph.capability_to_tools.items():
            if len(tools) > 2:
                report.duplicate_capabilities.append({
                    "capability": cap,
                    "tools": tools,
                    "count": len(tools),
                })
    except Exception as _exc:
        log.warning("swallowed_exception", action="capability_export_a", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    return report


# ═══════════════════════════════════════════════════════════════
# PART 4 — TOOL RELIABILITY PROFILING
# ═══════════════════════════════════════════════════════════════

@dataclass
class ToolReliability:
    """Passive reliability profile for a tool."""
    tool:            str
    total_calls:     int = 0
    successes:       int = 0
    failures:        int = 0
    timeouts:        int = 0
    retries:         int = 0
    avg_duration_ms: float = 0.0
    last_error:      str = ""
    last_success_ts: float = 0.0
    last_failure_ts: float = 0.0

    @property
    def success_rate(self) -> float:
        if self.total_calls == 0:
            return 1.0  # no data = assume ok
        return self.successes / self.total_calls

    @property
    def status(self) -> str:
        if self.total_calls == 0:
            return "no_data"
        if self.success_rate >= 0.95:
            return "reliable"
        if self.success_rate >= 0.75:
            return "degraded"
        return "unreliable"

    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "total_calls": self.total_calls,
            "successes": self.successes,
            "failures": self.failures,
            "timeouts": self.timeouts,
            "retries": self.retries,
            "success_rate": round(self.success_rate, 3),
            "avg_duration_ms": round(self.avg_duration_ms, 1),
            "status": self.status,
            "last_error": self.last_error[:200],
            "last_success_ts": self.last_success_ts,
            "last_failure_ts": self.last_failure_ts,
        }


# Bounded in-memory reliability store
_RELIABILITY: dict[str, ToolReliability] = {}
_MAX_TOOLS_TRACKED = 200


def record_tool_outcome(
    tool_name: str,
    success: bool,
    duration_ms: int = 0,
    error: str = "",
    was_retry: bool = False,
    was_timeout: bool = False,
) -> None:
    """
    Record a tool execution outcome for reliability profiling.

    This is passive — it records but does NOT influence tool selection
    or retry behavior. Purely observational.
    """
    try:
        if tool_name not in _RELIABILITY:
            if len(_RELIABILITY) >= _MAX_TOOLS_TRACKED:
                # Drop the tool with the fewest calls
                min_tool = min(_RELIABILITY, key=lambda k: _RELIABILITY[k].total_calls)
                del _RELIABILITY[min_tool]
            _RELIABILITY[tool_name] = ToolReliability(tool=tool_name)

        r = _RELIABILITY[tool_name]
        r.total_calls += 1
        if success:
            r.successes += 1
            r.last_success_ts = time.time()
        else:
            r.failures += 1
            r.last_failure_ts = time.time()
            r.last_error = error[:200]
        if was_timeout:
            r.timeouts += 1
        if was_retry:
            r.retries += 1
        # Running average duration
        if duration_ms > 0:
            if r.avg_duration_ms == 0:
                r.avg_duration_ms = float(duration_ms)
            else:
                r.avg_duration_ms = r.avg_duration_ms * 0.9 + duration_ms * 0.1
    except Exception:
        log.debug("swallowed_exception", exc_info=True)


def get_tool_reliability(tool_name: Optional[str] = None) -> dict:
    """
    Get reliability profile for a tool or all tools.

    Args:
        tool_name: Specific tool, or None for all.

    Returns dict or {tool_name: dict}.
    """
    try:
        if tool_name:
            r = _RELIABILITY.get(tool_name)
            return r.to_dict() if r else {"tool": tool_name, "status": "no_data"}
        return {name: r.to_dict() for name, r in sorted(_RELIABILITY.items())}
    except Exception:
        return {}


def get_reliability_summary() -> dict:
    """Aggregate reliability summary."""
    try:
        if not _RELIABILITY:
            return {"total_tools_tracked": 0}
        total = len(_RELIABILITY)
        reliable = sum(1 for r in _RELIABILITY.values() if r.status == "reliable")
        degraded = sum(1 for r in _RELIABILITY.values() if r.status == "degraded")
        unreliable = sum(1 for r in _RELIABILITY.values() if r.status == "unreliable")
        total_calls = sum(r.total_calls for r in _RELIABILITY.values())
        total_failures = sum(r.failures for r in _RELIABILITY.values())
        worst = sorted(_RELIABILITY.values(), key=lambda r: r.success_rate)[:5]
        return {
            "total_tools_tracked": total,
            "reliable": reliable,
            "degraded": degraded,
            "unreliable": unreliable,
            "total_calls": total_calls,
            "total_failures": total_failures,
            "overall_success_rate": round(
                sum(r.successes for r in _RELIABILITY.values()) / max(total_calls, 1), 3
            ),
            "worst_tools": [r.to_dict() for r in worst if r.total_calls > 0],
        }
    except Exception:
        return {"total_tools_tracked": len(_RELIABILITY)}


def clear_reliability() -> None:
    """Clear reliability data (for testing)."""
    _RELIABILITY.clear()


# ═══════════════════════════════════════════════════════════════
# PART 5 — CAPABILITY MATCHING HEURISTICS
# ═══════════════════════════════════════════════════════════════

# Intent keywords → semantic tags
_INTENT_TAG_MAP: dict[str, list[str]] = {
    "read":          ["filesystem"],
    "write":         ["filesystem"],
    "search":        ["filesystem", "analysis"],
    "test":          ["testing"],
    "deploy":        ["container", "system_modification"],
    "commit":        ["version_control"],
    "push":          ["version_control"],
    "pull":          ["version_control"],
    "fetch":         ["network", "external_api"],
    "research":      ["network", "memory"],
    "analyze":       ["analysis"],
    "debug":         ["analysis", "testing"],
    "build":         ["code_generation", "container"],
    "generate":      ["code_generation"],
    "remember":      ["memory"],
    "learn":         ["memory"],
    "docker":        ["container"],
    "git":           ["version_control"],
    "api":           ["network", "external_api"],
    "fix":           ["filesystem", "analysis", "code_generation"],
    "create":        ["filesystem", "code_generation"],
    "delete":        ["filesystem", "system_modification"],
    "monitor":       ["analysis", "testing"],
    "validate":      ["testing", "analysis"],
    "install":       ["system_modification"],
    "configure":     ["filesystem", "system_modification"],
}


@dataclass
class CapabilityMatch:
    """A scored match between a goal and a tool cluster."""
    tool:        str
    score:       float  # 0.0-1.0
    capability:  str
    domain:      str
    reasons:     list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "score": round(self.score, 3),
            "capability": self.capability,
            "domain": self.domain,
            "reasons": self.reasons,
        }


def match_capabilities(
    goal: str,
    risk_level: str = "medium",
    top_k: int = 10,
) -> list[CapabilityMatch]:
    """
    Match a goal to tool capabilities using heuristics.

    Scoring factors:
    1. Intent keyword → semantic tag matching (0.4 weight)
    2. Description keyword overlap (0.3 weight)
    3. Risk level compatibility (0.15 weight)
    4. Reliability history (0.15 weight)

    Returns ranked list of CapabilityMatch, best first.
    Does NOT alter any planner behavior — produces suggestions only.
    """
    try:
        goal_lower = goal.lower()
        goal_words = set(re.findall(r'\w+', goal_lower))

        profiles = get_tool_profiles()
        matches = []

        for profile in profiles:
            reasons = []
            score = 0.0

            # 1. Intent matching (0.4)
            intent_score = 0.0
            matched_tags = set()
            for keyword, tags in _INTENT_TAG_MAP.items():
                if keyword in goal_lower:
                    for tag in tags:
                        if tag in profile.semantic_tags:
                            matched_tags.add(tag)
                            intent_score += 0.15
            intent_score = min(intent_score, 0.4)
            if matched_tags:
                reasons.append(f"intent:{','.join(matched_tags)}")
            score += intent_score

            # 2. Description overlap (0.3)
            if profile.description:
                desc_words = set(re.findall(r'\w+', profile.description.lower()))
                overlap = len(goal_words & desc_words)
                desc_score = min(overlap / max(len(desc_words), 1) * 0.6, 0.3)
                if desc_score > 0.05:
                    reasons.append(f"desc_match:{overlap}words")
                score += desc_score

            # 3. Risk compatibility (0.15)
            risk_order = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
            tool_risk = risk_order.get(profile.side_effect_risk, 2)
            goal_risk = risk_order.get(risk_level, 2)
            if tool_risk <= goal_risk:
                score += 0.15
                reasons.append("risk_compatible")
            elif tool_risk == goal_risk + 1:
                score += 0.05  # slightly over
            # else: no bonus

            # 4. Reliability (0.15)
            rel = _RELIABILITY.get(profile.name)
            if rel and rel.total_calls > 0:
                rel_score = rel.success_rate * 0.15
                score += rel_score
                if rel.success_rate < 0.8:
                    reasons.append(f"reliability:{rel.status}")
            else:
                score += 0.10  # assume ok if no data
                reasons.append("no_reliability_data")

            if score > 0.1:
                cap = _CAPABILITY_MAP.get(profile.name, "unknown")
                domain = _CAPABILITY_TO_DOMAIN.get(cap, "unknown")
                matches.append(CapabilityMatch(
                    tool=profile.name,
                    score=score,
                    capability=cap,
                    domain=domain,
                    reasons=reasons,
                ))

        matches.sort(key=lambda m: m.score, reverse=True)
        return matches[:top_k]

    except Exception as e:
        log.debug("capability_matching_failed", err=str(e)[:100])
        return []


# ═══════════════════════════════════════════════════════════════
# PART 6 — CAPABILITY GAP DETECTION
# ═══════════════════════════════════════════════════════════════

@dataclass
class CapabilityGap:
    """A detected gap in Bea's capabilities."""
    gap_type:    str   # "missing_dependency" | "tool_failure_cluster" | "missing_capability" | "coverage_gap"
    description: str
    severity:    str = "medium"  # low | medium | high
    affected:    list[str] = field(default_factory=list)
    suggestion:  str = ""

    def to_dict(self) -> dict:
        return {
            "gap_type": self.gap_type,
            "description": self.description,
            "severity": self.severity,
            "affected": self.affected,
            "suggestion": self.suggestion,
        }


def detect_capability_gaps() -> list[CapabilityGap]:
    """
    Detect missing abilities and coverage gaps.

    Checks:
    1. Missing dependencies (tools that can't function)
    2. Tool failure clusters (tools that fail frequently)
    3. Missing capabilities (domains with no working tools)
    4. Coverage gaps (mission types with limited tool support)

    Returns list of CapabilityGap. Never raises.
    """
    gaps = []

    try:
        # 1. Missing dependencies
        discovery = run_auto_discovery()
        for unavail in discovery.unavailable_tools:
            if unavail.get("status") == "unavailable":
                gaps.append(CapabilityGap(
                    gap_type="missing_dependency",
                    description=f"Tool '{unavail['tool']}' unavailable: {unavail.get('reason', 'unknown')}",
                    severity="medium",
                    affected=[unavail["tool"]],
                    suggestion=f"Install missing dependency for {unavail['tool']}.",
                ))
    except Exception as _exc:
        log.warning("swallowed_exception", action="capability_export_b", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    try:
        # 2. Tool failure clusters
        for name, rel in _RELIABILITY.items():
            if rel.total_calls >= 3 and rel.success_rate < 0.5:
                gaps.append(CapabilityGap(
                    gap_type="tool_failure_cluster",
                    description=f"Tool '{name}' has {rel.success_rate:.0%} success rate over {rel.total_calls} calls",
                    severity="high",
                    affected=[name],
                    suggestion=f"Investigate failures: {rel.last_error[:100]}",
                ))
    except Exception as _exc:
        log.warning("swallowed_exception", action="capability_export_c", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    try:
        # 3. Missing capabilities — domains with zero available tools
        graph = get_capability_graph()
        available = set(discovery.available_tools) if discovery else set()
        for domain, caps in graph.domain_to_capabilities.items():
            domain_tools = set()
            for cap in caps:
                domain_tools.update(graph.capability_to_tools.get(cap, []))
            working = domain_tools & available
            if not working and domain_tools:
                gaps.append(CapabilityGap(
                    gap_type="missing_capability",
                    description=f"Domain '{domain}' has no working tools ({len(domain_tools)} declared)",
                    severity="high",
                    affected=sorted(domain_tools),
                    suggestion=f"Install dependencies for {domain} domain tools.",
                ))
    except Exception as _exc:
        log.warning("swallowed_exception", action="capability_export_d", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    try:
        # 4. Coverage gaps — mission types with few available tools
        from core.tool_registry import _MISSION_TOOLS
        for mission, tool_names in _MISSION_TOOLS.items():
            if not tool_names:
                continue  # intentionally empty
            available_for_mission = [t for t in tool_names if t in (discovery.available_tools if discovery else [])]
            if len(available_for_mission) < len(tool_names) * 0.5:
                gaps.append(CapabilityGap(
                    gap_type="coverage_gap",
                    description=f"Mission '{mission}' has only {len(available_for_mission)}/{len(tool_names)} tools available",
                    severity="low",
                    affected=tool_names,
                    suggestion=f"Ensure dependencies for {mission} tools are installed.",
                ))
    except Exception as _exc:
        log.warning("swallowed_exception", action="capability_export_e", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    return gaps


# ═══════════════════════════════════════════════════════════════
# PART 7 — OUTPUT ARTIFACTS
# ═══════════════════════════════════════════════════════════════

def export_artifacts(output_dir: str = "workspace") -> dict:
    """
    Export all capability intelligence artifacts as JSON files.

    Produces:
    - tool_profiles.json — semantic profiles of all tools
    - capability_graph.json — full ontology graph
    - capability_gaps.json — detected gaps
    - tool_reliability_signals.json — reliability data

    Returns dict of {filename: path} for produced files.
    Never raises — produces partial output on errors.
    """
    out = Path(output_dir)
    if not out.is_absolute():
        out = REPO_ROOT / out
    out.mkdir(parents=True, exist_ok=True)
    produced = {}

    # 1. Tool profiles
    try:
        profiles = get_tool_profiles()
        path = out / "tool_profiles.json"
        path.write_text(
            json.dumps([p.to_dict() for p in profiles], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        produced["tool_profiles.json"] = str(path)
    except Exception as e:
        log.debug("export_profiles_failed", err=str(e)[:80])

    # 2. Capability graph
    try:
        graph = get_capability_graph()
        path = out / "capability_graph.json"
        path.write_text(
            json.dumps(graph.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        produced["capability_graph.json"] = str(path)
    except Exception as e:
        log.debug("export_graph_failed", err=str(e)[:80])

    # 3. Capability gaps
    try:
        gaps = detect_capability_gaps()
        path = out / "capability_gaps.json"
        path.write_text(
            json.dumps([g.to_dict() for g in gaps], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        produced["capability_gaps.json"] = str(path)
    except Exception as e:
        log.debug("export_gaps_failed", err=str(e)[:80])

    # 4. Reliability signals
    try:
        reliability = get_tool_reliability()
        summary = get_reliability_summary()
        path = out / "tool_reliability_signals.json"
        path.write_text(
            json.dumps({"summary": summary, "tools": reliability}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        produced["tool_reliability_signals.json"] = str(path)
    except Exception as e:
        log.debug("export_reliability_failed", err=str(e)[:80])

    try:
        log.info("capability_artifacts_exported", files=list(produced.keys()))
    except Exception as _exc:
        log.warning("swallowed_exception", action="capability_artifacts_export", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    return produced