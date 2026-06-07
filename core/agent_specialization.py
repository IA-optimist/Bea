"""
BEA MAX — Agent Specialization Engine
==========================================
Enables Bea to dynamically determine which agent type should handle
which task class.

Parts:
1. Task Clustering — group missions by intent/tool/plan/risk similarity
2. Agent Role Discovery — infer optimal agent characteristics per cluster
3. Capability Matching — map capability graph to agent archetypes
4. Specialization Heuristics — task → best archetype scoring
5. Agent Config Templates — configuration skeletons (not instantiated)
6. Output Artifacts — structured JSON exports

All functions fail-open. No orchestration changes. No agent spawning.
Purely additive and observational.

Usage:
    from core.agent_specialization import (
        get_task_clusters,
        discover_agent_roles,
        analyze_agent_capability_coverage,
        score_task_specialization,
        get_agent_config_templates,
        export_specialization_artifacts,
    )
"""
from __future__ import annotations

import structlog
log = structlog.get_logger(__name__)

import json
import os
import re
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
# EXISTING SYSTEM KNOWLEDGE (extracted from codebase analysis)
# ═══════════════════════════════════════════════════════════════

# Current agents in the system
EXISTING_AGENTS: dict[str, dict] = {
    "atlas-director":   {"role": "director",  "timeout_s": 60,  "description": "Mission orchestration, multi-cycle planning"},
    "scout-research":   {"role": "research",  "timeout_s": 120, "description": "Research, context gathering, information synthesis"},
    "map-planner":      {"role": "planner",   "timeout_s": 120, "description": "Detailed execution planning, task decomposition"},
    "forge-builder":    {"role": "builder",   "timeout_s": 180, "description": "Code generation, file writing, implementation"},
    "lens-reviewer":    {"role": "reviewer",  "timeout_s": 120, "description": "Quality validation, security review, coherence check"},
    "vault-memory":     {"role": "memory",    "timeout_s": 120, "description": "Context recall, memory retrieval, knowledge injection"},
    "shadow-advisor":   {"role": "advisor",   "timeout_s": 30,  "description": "Alternative perspectives, risk analysis, devil's advocate"},
    "pulse-ops":        {"role": "ops",       "timeout_s": 120, "description": "Operational actions, file execution, deployment prep"},
    "night-worker":     {"role": "builder",   "timeout_s": 300, "description": "Long-running multi-cycle tasks, overnight processing"},
    "image-agent":      {"role": "builder",   "timeout_s": 120, "description": "Image analysis and generation"},
    # Business layer
    "venture-builder":     {"role": "builder",   "timeout_s": 180, "description": "Business opportunity analysis"},
    "offer-designer":      {"role": "builder",   "timeout_s": 180, "description": "Commercial offer design"},
    "workflow-architect":  {"role": "planner",   "timeout_s": 180, "description": "Workflow architecture design"},
    "saas-builder":        {"role": "builder",   "timeout_s": 180, "description": "SaaS MVP blueprint generation"},
    "trade-ops":           {"role": "ops",       "timeout_s": 180, "description": "Specialized business operations"},
    # V2 agents
    "debug-agent":      {"role": "builder",   "timeout_s": 180, "description": "Debug analysis and automated fix generation"},
    "recovery-agent":   {"role": "advisor",   "timeout_s": 120, "description": "Failure recovery and rollback strategies"},
    "monitoring-agent":  {"role": "default",  "timeout_s": 120, "description": "System monitoring and anomaly detection"},
    # Bea team (meta-level)
    "bea-architect":  {"role": "planner",   "timeout_s": 180, "description": "System architecture decisions for BeaMax"},
    "bea-coder":      {"role": "builder",   "timeout_s": 240, "description": "Implementation of BeaMax changes"},
    "bea-reviewer":   {"role": "reviewer",  "timeout_s": 150, "description": "Code review for BeaMax changes"},
    "bea-qa":         {"role": "builder",   "timeout_s": 240, "description": "Test creation and execution for BeaMax"},
    "bea-devops":     {"role": "builder",   "timeout_s": 180, "description": "Deployment and environment validation"},
    "bea-watcher":    {"role": "default",   "timeout_s": 120, "description": "Log monitoring and anomaly detection"},
}

# Current mission routing (TaskMode → agent plan)
MISSION_ROUTING: dict[str, list[str]] = {
    "chat":      [],
    "research":  ["vault-memory", "scout-research", "shadow-advisor", "lens-reviewer"],
    "plan":      ["vault-memory", "scout-research", "map-planner", "shadow-advisor", "lens-reviewer"],
    "code":      ["vault-memory", "scout-research", "forge-builder", "lens-reviewer", "pulse-ops"],
    "auto":      ["vault-memory", "scout-research", "shadow-advisor", "map-planner", "forge-builder", "lens-reviewer", "pulse-ops"],
    "night":     ["vault-memory", "atlas-director"],
    "improve":   ["vault-memory"],
    "business":  ["venture-builder", "offer-designer", "workflow-architect", "saas-builder", "trade-ops"],
}


# ═══════════════════════════════════════════════════════════════
# PART 1 — TASK CLUSTERING
# ═══════════════════════════════════════════════════════════════

@dataclass
class TaskCluster:
    """A cluster of similar task patterns.

    Attributes:
        name: Cluster identifier.
        description: What this cluster represents.
        intent_patterns: Regex patterns that match this cluster.
        typical_tools: Tools commonly needed for these tasks.
        typical_agents: Agents typically involved.
        plan_depth: How many planning steps (1=simple, 5=complex).
        risk_level: Typical risk (low/medium/high).
        examples: Example task descriptions.
        frequency_hint: How often this pattern occurs (common/moderate/rare).
    """
    name:            str
    description:     str = ""
    intent_patterns: list[str] = field(default_factory=list)
    typical_tools:   list[str] = field(default_factory=list)
    typical_agents:  list[str] = field(default_factory=list)
    plan_depth:      int = 1
    risk_level:      str = "low"
    examples:        list[str] = field(default_factory=list)
    frequency_hint:  str = "moderate"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "intent_patterns": self.intent_patterns,
            "typical_tools": self.typical_tools,
            "typical_agents": self.typical_agents,
            "plan_depth": self.plan_depth,
            "risk_level": self.risk_level,
            "examples": self.examples,
            "frequency_hint": self.frequency_hint,
        }


# Pre-defined task clusters based on codebase analysis
_TASK_CLUSTERS: list[TaskCluster] = [
    TaskCluster(
        name="code_modification",
        description="Writing, modifying, or refactoring code files",
        intent_patterns=[r"(?:write|create|modify|refactor|fix|implement|add|update)\s+(?:code|script|module|function|class|file)"],
        typical_tools=["write_file", "write_file_safe", "read_file", "replace_in_file",
                        "search_in_files", "run_unit_tests"],
        typical_agents=["forge-builder", "lens-reviewer", "scout-research"],
        plan_depth=3,
        risk_level="medium",
        examples=["Write a Python script to parse JSON", "Fix the bug in auth module",
                  "Add type hints to core/planner.py"],
        frequency_hint="common",
    ),
    TaskCluster(
        name="repo_analysis",
        description="Analyzing codebase structure, dependencies, and patterns",
        intent_patterns=[r"(?:analyze|inspect|review|check|audit|scan)\s+(?:code|repo|codebase|project|dependency|import)"],
        typical_tools=["read_file", "search_in_files", "list_project_structure",
                        "dependency_analyzer", "code_search_multi_file", "count_lines"],
        typical_agents=["scout-research", "lens-reviewer"],
        plan_depth=2,
        risk_level="low",
        examples=["Analyze imports in core/", "Find unused functions", "Review security patterns"],
        frequency_hint="common",
    ),
    TaskCluster(
        name="tool_building",
        description="Creating, testing, or extending tools and toolkits",
        intent_patterns=[r"(?:build|create|generate|design)\s+(?:tool|toolkit|utility|helper)"],
        typical_tools=["analyze_tool_need", "generate_tool_skeleton", "generate_tool_tests",
                        "build_complete_tool", "write_file", "run_unit_tests"],
        typical_agents=["forge-builder", "map-planner", "lens-reviewer"],
        plan_depth=4,
        risk_level="medium",
        examples=["Create a tool for PDF parsing", "Build a monitoring toolkit"],
        frequency_hint="moderate",
    ),
    TaskCluster(
        name="debugging",
        description="Investigating failures, tracing errors, fixing bugs",
        intent_patterns=[r"(?:debug|fix|trace|investigate|diagnose)\s+(?:error|bug|failure|issue|crash|problem)"],
        typical_tools=["read_file", "check_logs", "search_in_files", "run_unit_tests",
                        "git_diff", "git_log"],
        typical_agents=["debug-agent", "scout-research", "forge-builder", "lens-reviewer"],
        plan_depth=3,
        risk_level="medium",
        examples=["Debug the timeout in agent_loop", "Fix failing tests", "Trace the import error"],
        frequency_hint="common",
    ),
    TaskCluster(
        name="planning",
        description="Creating architecture plans, migration strategies, roadmaps",
        intent_patterns=[r"(?:plan|design|architect|strategy|roadmap|propose)\s+(?:migration|refactor|architecture|system|approach)"],
        typical_tools=["read_file", "search_in_files", "list_project_structure"],
        typical_agents=["map-planner", "shadow-advisor", "scout-research"],
        plan_depth=5,
        risk_level="low",
        examples=["Design the Phase 2 migration", "Plan microservices architecture",
                  "Create a roadmap for self-improvement"],
        frequency_hint="moderate",
    ),
    TaskCluster(
        name="testing",
        description="Writing tests, running test suites, validating coverage",
        intent_patterns=[r"(?:test|validate|verify|cover)\s+(?:module|function|code|unit|integration|coverage)"],
        typical_tools=["run_unit_tests", "run_smoke_tests", "read_file", "write_file",
                        "search_in_files"],
        typical_agents=["forge-builder", "lens-reviewer"],
        plan_depth=2,
        risk_level="low",
        examples=["Write tests for circuit_breaker", "Run the full test suite",
                  "Check test coverage gaps"],
        frequency_hint="common",
    ),
    TaskCluster(
        name="research",
        description="Information gathering, comparison, knowledge synthesis",
        intent_patterns=[r"(?:research|search|find|compare|explore|learn)\s+(?:about|for|how|what|best|option)"],
        typical_tools=["fetch_url", "search_pypi", "fetch_github_readme",
                        "memory_search_similar", "search_in_files"],
        typical_agents=["scout-research", "vault-memory", "shadow-advisor"],
        plan_depth=2,
        risk_level="low",
        examples=["Research circuit breaker patterns", "Compare Redis vs Memcached",
                  "Find best Python testing frameworks"],
        frequency_hint="common",
    ),
    TaskCluster(
        name="deployment",
        description="Building, deploying, restarting services and containers",
        intent_patterns=[r"(?:deploy|restart|build|start|stop)\s+(?:\w+\s+)*?(?:service|container|docker|application|api)"],
        typical_tools=["docker_compose_build", "docker_compose_up", "docker_compose_down",
                        "docker_restart", "docker_ps", "docker_logs", "api_healthcheck"],
        typical_agents=["pulse-ops", "atlas-director"],
        plan_depth=3,
        risk_level="high",
        examples=["Deploy the new version", "Restart the bot container", "Build and start services"],
        frequency_hint="moderate",
    ),
    TaskCluster(
        name="version_control",
        description="Git operations: branching, committing, comparing, pushing",
        intent_patterns=[r"(?:commit|push|pull|branch|merge|diff|revert)\s"],
        typical_tools=["git_status", "git_diff", "git_log", "git_commit", "git_push",
                        "git_pull", "git_branch_create", "git_checkout"],
        typical_agents=["pulse-ops", "forge-builder"],
        plan_depth=2,
        risk_level="medium",
        examples=["Commit the changes", "Create a feature branch", "Push to remote"],
        frequency_hint="common",
    ),
    TaskCluster(
        name="memory_management",
        description="Storing, searching, and managing knowledge/memory entries",
        intent_patterns=[r"(?:remember|store|save|search|recall|memory)\s+(?:pattern|solution|error|knowledge|decision)"],
        typical_tools=["memory_store_solution", "memory_search_similar", "memory_store_error",
                        "memory_store_patch", "memory_deduplicate", "memory_cleanup_expired"],
        typical_agents=["vault-memory"],
        plan_depth=1,
        risk_level="low",
        examples=["Store this solution pattern", "Search for similar past errors",
                  "Clean up expired memory entries"],
        frequency_hint="moderate",
    ),
    TaskCluster(
        name="self_improvement",
        description="Improving Bea itself: code quality, capabilities, performance",
        intent_patterns=[r"(?:improve|optimize|enhance|upgrade|strengthen)\s+(?:yourself|bea|system|performance|capability)"],
        typical_tools=["read_file", "write_file", "search_in_files", "run_unit_tests",
                        "dependency_analyzer", "check_logs"],
        typical_agents=["bea-architect", "bea-coder", "bea-reviewer", "bea-qa"],
        plan_depth=4,
        risk_level="medium",
        examples=["Improve test coverage", "Optimize the retry logic", "Enhance error handling"],
        frequency_hint="moderate",
    ),
    TaskCluster(
        name="monitoring",
        description="Checking system health, logs, metrics, and anomalies",
        intent_patterns=[r"(?:monitor|check|watch|observe|inspect)\s+(?:health|logs|status|metrics|system|anomaly)"],
        typical_tools=["check_logs", "api_healthcheck", "docker_ps", "docker_logs",
                        "env_checker", "system_health_check"],
        typical_agents=["monitoring-agent", "bea-watcher", "pulse-ops"],
        plan_depth=1,
        risk_level="low",
        examples=["Check system health", "Monitor error rates", "Inspect recent logs"],
        frequency_hint="common",
    ),
]


def get_task_clusters() -> list[TaskCluster]:
    """Return all defined task clusters. Never raises."""
    return list(_TASK_CLUSTERS)


def classify_task(task_text: str) -> list[dict]:
    """
    Classify a task text against known clusters.

    Returns ranked list of matching clusters with confidence scores.
    """
    try:
        task_lower = task_text.lower()
        results = []
        for cluster in _TASK_CLUSTERS:
            score = 0.0
            matched_patterns = []

            # Pattern matching
            for pattern in cluster.intent_patterns:
                try:
                    if re.search(pattern, task_lower):
                        score += 0.5
                        matched_patterns.append(pattern[:50])
                except re.error as _exc:
                    log.warning("swallowed_exception", action="pattern_regex_match", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

            # Keyword overlap with tools
            task_words = set(re.findall(r'\w+', task_lower))
            tool_words = set()
            for tool in cluster.typical_tools:
                tool_words.update(tool.replace("_", " ").split())
            overlap = len(task_words & tool_words)
            score += min(overlap * 0.1, 0.3)

            # Example similarity
            for example in cluster.examples:
                example_words = set(re.findall(r'\w+', example.lower()))
                ex_overlap = len(task_words & example_words)
                if ex_overlap >= 3:
                    score += 0.2
                    break

            if score > 0.1:
                results.append({
                    "cluster": cluster.name,
                    "score": round(min(score, 1.0), 3),
                    "matched_patterns": matched_patterns,
                    "plan_depth": cluster.plan_depth,
                    "risk_level": cluster.risk_level,
                })

        results.sort(key=lambda r: r["score"], reverse=True)
        return results
    except Exception as e:
        log.debug("task_classification_failed", err=str(e)[:100])
        return []


# ═══════════════════════════════════════════════════════════════
# PART 2 — AGENT ROLE DISCOVERY
# ═══════════════════════════════════════════════════════════════

@dataclass
class AgentArchetype:
    """A discovered agent archetype based on task cluster analysis.

    Attributes:
        name: Archetype identifier.
        description: What this agent type does.
        primary_clusters: Task clusters this archetype handles best.
        required_capabilities: Capabilities from the graph this agent needs.
        reasoning_depth: How much reasoning is needed (1=simple, 5=deep).
        tool_density: How many tools are typically used (1=few, 5=many).
        risk_tolerance: How much risk this agent can accept (1=minimal, 5=high).
        code_impact: How much code this agent typically modifies (0=none, 5=extensive).
        existing_agents: Current agents that match this archetype.
        coverage_status: "covered" | "partial" | "missing".
    """
    name:                 str
    description:          str = ""
    primary_clusters:     list[str] = field(default_factory=list)
    required_capabilities: list[str] = field(default_factory=list)
    reasoning_depth:      int = 1
    tool_density:         int = 1
    risk_tolerance:       int = 1
    code_impact:          int = 0
    existing_agents:      list[str] = field(default_factory=list)
    coverage_status:      str = "covered"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "primary_clusters": self.primary_clusters,
            "required_capabilities": self.required_capabilities,
            "reasoning_depth": self.reasoning_depth,
            "tool_density": self.tool_density,
            "risk_tolerance": self.risk_tolerance,
            "code_impact": self.code_impact,
            "existing_agents": self.existing_agents,
            "coverage_status": self.coverage_status,
        }


# Discovered archetypes based on cluster analysis
_AGENT_ARCHETYPES: list[AgentArchetype] = [
    AgentArchetype(
        name="architect",
        description="Deep reasoning about system design, interfaces, and migration paths. Reads everything, writes nothing.",
        primary_clusters=["planning", "repo_analysis"],
        required_capabilities=["filesystem_read", "filesystem_search", "code_analyze"],
        reasoning_depth=5, tool_density=2, risk_tolerance=1, code_impact=0,
        existing_agents=["map-planner", "shadow-advisor", "bea-architect"],
        coverage_status="covered",
    ),
    AgentArchetype(
        name="implementer",
        description="Writes code, creates files, implements changes. Focused execution with moderate reasoning.",
        primary_clusters=["code_modification", "tool_building"],
        required_capabilities=["filesystem_write", "filesystem_read", "code_generate", "test_execute"],
        reasoning_depth=3, tool_density=4, risk_tolerance=3, code_impact=5,
        existing_agents=["forge-builder", "night-worker", "bea-coder"],
        coverage_status="covered",
    ),
    AgentArchetype(
        name="reviewer",
        description="Validates outputs for correctness, security, and quality. Read-only, high standards.",
        primary_clusters=["repo_analysis", "testing"],
        required_capabilities=["filesystem_read", "filesystem_search", "code_analyze", "test_execute"],
        reasoning_depth=4, tool_density=3, risk_tolerance=1, code_impact=0,
        existing_agents=["lens-reviewer", "bea-reviewer"],
        coverage_status="covered",
    ),
    AgentArchetype(
        name="researcher",
        description="Gathers information from multiple sources, synthesizes knowledge. Network access needed.",
        primary_clusters=["research"],
        required_capabilities=["http_read", "memory_read", "filesystem_search", "package_search"],
        reasoning_depth=3, tool_density=3, risk_tolerance=1, code_impact=0,
        existing_agents=["scout-research"],
        coverage_status="covered",
    ),
    AgentArchetype(
        name="debugger",
        description="Traces errors, reads logs, identifies root causes. Combines analysis with targeted fixes.",
        primary_clusters=["debugging"],
        required_capabilities=["filesystem_read", "code_analyze", "vcs_inspect", "test_execute"],
        reasoning_depth=4, tool_density=4, risk_tolerance=2, code_impact=3,
        existing_agents=["debug-agent"],
        coverage_status="partial",  # only one agent, no fallback
    ),
    AgentArchetype(
        name="tester",
        description="Writes and runs tests, measures coverage, validates changes. Test-focused specialist.",
        primary_clusters=["testing"],
        required_capabilities=["test_execute", "filesystem_write", "filesystem_read", "code_analyze"],
        reasoning_depth=2, tool_density=3, risk_tolerance=1, code_impact=2,
        existing_agents=["bea-qa"],
        coverage_status="partial",  # only bea-qa, no general test agent
    ),
    AgentArchetype(
        name="operator",
        description="Executes deployment, manages containers, handles operational tasks. High-risk, high-trust.",
        primary_clusters=["deployment", "version_control"],
        required_capabilities=["container_control", "container_inspect", "vcs_mutate", "vcs_publish", "system_execute"],
        reasoning_depth=2, tool_density=4, risk_tolerance=4, code_impact=1,
        existing_agents=["pulse-ops"],
        coverage_status="covered",
    ),
    AgentArchetype(
        name="memory_curator",
        description="Manages knowledge storage, retrieval, and maintenance. Memory-focused specialist.",
        primary_clusters=["memory_management"],
        required_capabilities=["memory_read", "memory_write", "memory_manage"],
        reasoning_depth=2, tool_density=3, risk_tolerance=1, code_impact=0,
        existing_agents=["vault-memory"],
        coverage_status="covered",
    ),
    AgentArchetype(
        name="monitor",
        description="Watches system health, detects anomalies, reads logs. Continuous observation.",
        primary_clusters=["monitoring"],
        required_capabilities=["filesystem_read", "env_inspect", "container_inspect", "http_read"],
        reasoning_depth=2, tool_density=3, risk_tolerance=1, code_impact=0,
        existing_agents=["monitoring-agent", "bea-watcher"],
        coverage_status="covered",
    ),
    AgentArchetype(
        name="recovery_specialist",
        description="Handles failure recovery, rollback strategies, and disaster mitigation.",
        primary_clusters=["debugging", "deployment"],
        required_capabilities=["filesystem_read", "vcs_inspect", "container_inspect", "system_execute"],
        reasoning_depth=4, tool_density=3, risk_tolerance=3, code_impact=2,
        existing_agents=["recovery-agent"],
        coverage_status="partial",  # only one agent
    ),
    AgentArchetype(
        name="meta_improver",
        description="Self-improvement specialist — analyzes Bea's own code and suggests improvements.",
        primary_clusters=["self_improvement", "repo_analysis"],
        required_capabilities=["filesystem_read", "filesystem_write", "code_analyze", "test_execute", "vcs_mutate"],
        reasoning_depth=5, tool_density=5, risk_tolerance=2, code_impact=4,
        existing_agents=["bea-architect", "bea-coder", "bea-reviewer", "bea-qa"],
        coverage_status="covered",
    ),
]


def discover_agent_roles() -> list[AgentArchetype]:
    """Return discovered agent archetypes. Never raises."""
    return list(_AGENT_ARCHETYPES)


def get_archetype(name: str) -> Optional[AgentArchetype]:
    """Get a specific archetype by name."""
    for a in _AGENT_ARCHETYPES:
        if a.name == name:
            return a
    return None


# ═══════════════════════════════════════════════════════════════
# PART 3 — CAPABILITY MATCHING
# ═══════════════════════════════════════════════════════════════

@dataclass
class CoverageAnalysis:
    """Analysis of agent-capability coverage.

    Attributes:
        total_archetypes: Number of defined archetypes.
        covered: Archetypes with sufficient agent coverage.
        partial: Archetypes with limited coverage (single agent, no fallback).
        missing: Archetypes with no agent coverage.
        overlapping: Agent pairs with significant capability overlap.
        routing_inefficiencies: Cases where routing doesn't match capability needs.
    """
    total_archetypes:       int = 0
    covered:                list[str] = field(default_factory=list)
    partial:                list[str] = field(default_factory=list)
    missing:                list[str] = field(default_factory=list)
    overlapping:            list[dict] = field(default_factory=list)
    routing_inefficiencies: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total_archetypes": self.total_archetypes,
            "covered": self.covered,
            "partial": self.partial,
            "missing": self.missing,
            "overlapping": self.overlapping,
            "routing_inefficiencies": self.routing_inefficiencies,
        }


def analyze_agent_capability_coverage() -> CoverageAnalysis:
    """
    Analyze how well current agents cover the archetype needs.

    Returns CoverageAnalysis with coverage status, overlaps, and inefficiencies.
    Never raises.
    """
    analysis = CoverageAnalysis(total_archetypes=len(_AGENT_ARCHETYPES))

    try:
        for archetype in _AGENT_ARCHETYPES:
            if archetype.coverage_status == "covered":
                analysis.covered.append(archetype.name)
            elif archetype.coverage_status == "partial":
                analysis.partial.append(archetype.name)
            else:
                analysis.missing.append(archetype.name)
    except Exception as _exc:
        log.warning("swallowed_exception", action="archetype_missing_check", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    try:
        # Detect overlapping agents (same role, similar capabilities)
        agent_capabilities: dict[str, set[str]] = {}
        for archetype in _AGENT_ARCHETYPES:
            caps = set(archetype.required_capabilities)
            for agent in archetype.existing_agents:
                agent_capabilities.setdefault(agent, set()).update(caps)

        agents = list(agent_capabilities.keys())
        for i in range(len(agents)):
            for j in range(i + 1, len(agents)):
                a, b = agents[i], agents[j]
                caps_a, caps_b = agent_capabilities[a], agent_capabilities[b]
                overlap = caps_a & caps_b
                if len(overlap) >= 3:
                    analysis.overlapping.append({
                        "agents": [a, b],
                        "shared_capabilities": sorted(overlap),
                        "overlap_count": len(overlap),
                    })
    except Exception as _exc:
        log.warning("swallowed_exception", action="capability_signal_export_a", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    try:
        # Detect routing inefficiencies
        for mode, agents in MISSION_ROUTING.items():
            if not agents:
                continue
            # Check if all agents in the route have the right capabilities
            for agent_name in agents:
                agent_info = EXISTING_AGENTS.get(agent_name, {})
                if not agent_info:
                    analysis.routing_inefficiencies.append({
                        "mode": mode,
                        "agent": agent_name,
                        "issue": "agent not found in registry",
                    })
    except Exception as _exc:
        log.warning("swallowed_exception", action="capability_signal_export_b", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    return analysis


# ═══════════════════════════════════════════════════════════════
# PART 4 — SPECIALIZATION HEURISTICS
# ═══════════════════════════════════════════════════════════════

@dataclass
class SpecializationScore:
    """Score for how well an agent archetype matches a task."""
    archetype:    str
    score:        float  # 0.0-1.0
    reasons:      list[str] = field(default_factory=list)
    recommended_agents: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "archetype": self.archetype,
            "score": round(self.score, 3),
            "reasons": self.reasons,
            "recommended_agents": self.recommended_agents,
        }


def score_task_specialization(
    task_text: str,
    risk_level: str = "medium",
    code_impact: int = 0,
) -> list[SpecializationScore]:
    """
    Score which agent archetype should handle a task.

    Signals used:
    - Task cluster matching (which clusters does this task belong to?)
    - Tool density (how many tools does the task need?)
    - Plan depth (how complex is the planning?)
    - Risk level compatibility
    - Code impact level

    Returns ranked list of SpecializationScore, best first.
    Does NOT alter planner — produces suggestions only.
    """
    try:
        # 1. Classify task into clusters
        cluster_matches = classify_task(task_text)
        matched_clusters = {m["cluster"]: m["score"] for m in cluster_matches}

        risk_order = {"low": 1, "medium": 2, "high": 3}
        goal_risk = risk_order.get(risk_level, 2)

        results = []
        for archetype in _AGENT_ARCHETYPES:
            score = 0.0
            reasons = []

            # Cluster overlap (0.4 weight)
            cluster_score = 0.0
            for cluster_name in archetype.primary_clusters:
                if cluster_name in matched_clusters:
                    cluster_score += matched_clusters[cluster_name] * 0.2
                    reasons.append(f"cluster:{cluster_name}")
            score += min(cluster_score, 0.4)

            # Risk compatibility (0.2 weight)
            archetype_risk = archetype.risk_tolerance
            if archetype_risk >= goal_risk:
                score += 0.2
                reasons.append("risk_compatible")
            elif archetype_risk == goal_risk - 1:
                score += 0.1

            # Code impact alignment (0.2 weight)
            if code_impact > 0:
                if archetype.code_impact >= code_impact:
                    score += 0.2
                    reasons.append("code_impact_aligned")
                elif archetype.code_impact > 0:
                    score += 0.1
            else:
                if archetype.code_impact == 0:
                    score += 0.15
                    reasons.append("no_code_impact_needed")

            # Coverage bonus (0.2 weight) — prefer archetypes with actual agents
            if archetype.coverage_status == "covered":
                score += 0.2
                reasons.append("fully_covered")
            elif archetype.coverage_status == "partial":
                score += 0.1
                reasons.append("partial_coverage")

            if score > 0.15:
                results.append(SpecializationScore(
                    archetype=archetype.name,
                    score=min(score, 1.0),
                    reasons=reasons,
                    recommended_agents=archetype.existing_agents[:3],
                ))

        results.sort(key=lambda r: r.score, reverse=True)
        return results

    except Exception as e:
        log.debug("specialization_scoring_failed", err=str(e)[:100])
        return []


# ═══════════════════════════════════════════════════════════════
# PART 5 — AGENT CONFIG TEMPLATES
# ═══════════════════════════════════════════════════════════════

@dataclass
class AgentConfigTemplate:
    """Configuration skeleton for an agent archetype.

    These are templates — NOT instantiated agents. They define
    what a specialized agent would look like if created.

    Attributes:
        archetype: Which archetype this config is for.
        allowed_tools: Tools this agent type should have access to.
        risk_tolerance: Max risk level (1-5).
        max_reasoning_depth: Max reasoning steps/tokens.
        preferred_model_tier: "fast" | "standard" | "advanced".
        planning_verbosity: "minimal" | "moderate" | "detailed".
        timeout_s: Default execution timeout.
        max_retries: Max retry attempts on failure.
        requires_approval: Whether human approval is needed for actions.
    """
    archetype:            str
    allowed_tools:        list[str] = field(default_factory=list)
    risk_tolerance:       int = 1
    max_reasoning_depth:  int = 3
    preferred_model_tier: str = "standard"
    planning_verbosity:   str = "moderate"
    timeout_s:            int = 120
    max_retries:          int = 2
    requires_approval:    bool = False

    def to_dict(self) -> dict:
        return {
            "archetype": self.archetype,
            "allowed_tools": self.allowed_tools,
            "risk_tolerance": self.risk_tolerance,
            "max_reasoning_depth": self.max_reasoning_depth,
            "preferred_model_tier": self.preferred_model_tier,
            "planning_verbosity": self.planning_verbosity,
            "timeout_s": self.timeout_s,
            "max_retries": self.max_retries,
            "requires_approval": self.requires_approval,
        }


def get_agent_config_templates() -> list[AgentConfigTemplate]:
    """
    Generate configuration templates for all archetypes.

    Returns list of AgentConfigTemplate — NOT instantiated agents.
    These are suggestions for how agents COULD be configured.
    """
    templates = []
    try:
        for archetype in _AGENT_ARCHETYPES:
            # Gather all tools from the archetype's clusters
            tools = set()
            for cluster_name in archetype.primary_clusters:
                for cluster in _TASK_CLUSTERS:
                    if cluster.name == cluster_name:
                        tools.update(cluster.typical_tools)

            # Model tier based on reasoning depth
            if archetype.reasoning_depth >= 4:
                model_tier = "advanced"
            elif archetype.reasoning_depth >= 2:
                model_tier = "standard"
            else:
                model_tier = "fast"

            # Planning verbosity
            if archetype.reasoning_depth >= 4:
                verbosity = "detailed"
            elif archetype.reasoning_depth >= 2:
                verbosity = "moderate"
            else:
                verbosity = "minimal"

            # Timeout based on tool density and risk
            base_timeout = 120
            if archetype.tool_density >= 4:
                base_timeout = 240
            if archetype.risk_tolerance >= 4:
                base_timeout = 180

            templates.append(AgentConfigTemplate(
                archetype=archetype.name,
                allowed_tools=sorted(tools),
                risk_tolerance=archetype.risk_tolerance,
                max_reasoning_depth=archetype.reasoning_depth,
                preferred_model_tier=model_tier,
                planning_verbosity=verbosity,
                timeout_s=base_timeout,
                max_retries=1 if archetype.risk_tolerance >= 4 else 3,
                requires_approval=archetype.risk_tolerance >= 4 or archetype.code_impact >= 4,
            ))
    except Exception as e:
        log.debug("config_template_generation_failed", err=str(e)[:100])

    return templates


# ═══════════════════════════════════════════════════════════════
# PART 6 — OUTPUT ARTIFACTS
# ═══════════════════════════════════════════════════════════════

def export_specialization_artifacts(output_dir: str = "workspace") -> dict:
    """
    Export all specialization artifacts as JSON files.

    Produces:
    - task_clusters.json — cluster definitions with patterns and tools
    - agent_archetypes.json — discovered archetypes with coverage status
    - agent_routing_suggestions.json — coverage analysis + config templates

    Returns {filename: path}. Never raises — partial output on errors.
    """
    out = Path(output_dir)
    if not out.is_absolute():
        out = REPO_ROOT / out
    out.mkdir(parents=True, exist_ok=True)
    produced = {}

    # 1. Task clusters
    try:
        clusters = get_task_clusters()
        path = out / "task_clusters.json"
        path.write_text(
            json.dumps([c.to_dict() for c in clusters], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        produced["task_clusters.json"] = str(path)
    except Exception as e:
        log.debug("export_clusters_failed", err=str(e)[:80])

    # 2. Agent archetypes
    try:
        archetypes = discover_agent_roles()
        path = out / "agent_archetypes.json"
        path.write_text(
            json.dumps([a.to_dict() for a in archetypes], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        produced["agent_archetypes.json"] = str(path)
    except Exception as e:
        log.debug("export_archetypes_failed", err=str(e)[:80])

    # 3. Routing suggestions (coverage + templates)
    try:
        coverage = analyze_agent_capability_coverage()
        templates = get_agent_config_templates()
        routing = {
            "coverage": coverage.to_dict(),
            "config_templates": [t.to_dict() for t in templates],
            "existing_agents": {k: v for k, v in EXISTING_AGENTS.items()},
            "mission_routing": MISSION_ROUTING,
        }
        path = out / "agent_routing_suggestions.json"
        path.write_text(
            json.dumps(routing, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        produced["agent_routing_suggestions.json"] = str(path)
    except Exception as e:
        log.debug("export_routing_failed", err=str(e)[:80])

    try:
        log.info("specialization_artifacts_exported", files=list(produced.keys()))
    except Exception as _exc:
        log.warning("swallowed_exception", action="specialization_artifacts_export", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    return produced
