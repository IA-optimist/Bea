"""
core/orchestration/mission_classifier.py — Classify missions by type, urgency,
complexity, risk, and determine execution strategy.

Pure logic — no LLM calls, no side effects. Fast and deterministic.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class TaskType(str, Enum):
    QUERY = "query"              # simple question / lookup
    ANALYSIS = "analysis"        # data analysis, audit, review
    IMPLEMENTATION = "implementation"  # build, code, create
    DEBUGGING = "debugging"      # fix, repair, diagnose
    DEPLOYMENT = "deployment"    # deploy, release, infra
    RESEARCH = "research"        # search, investigate
    SYSTEM_OPS = "system_ops"    # server, docker, monitoring
    IMPROVEMENT = "improvement"  # self-improve, optimize
    WORKFLOW = "workflow"        # multi-step coordinated
    BUSINESS = "business"
    OTHER = "other"


class Urgency(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class Complexity(str, Enum):
    TRIVIAL = "trivial"      # single-step, direct answer
    SIMPLE = "simple"        # 1-2 steps, one tool
    MODERATE = "moderate"    # 3-5 steps, multiple tools
    COMPLEX = "complex"      # 5+ steps, dependencies, risk


@dataclass
class MissionClassification:
    """Result of classifying a mission goal."""
    task_type: TaskType = TaskType.OTHER
    urgency: Urgency = Urgency.NORMAL
    complexity: Complexity = Complexity.SIMPLE
    risk_level: str = "low"           # low / medium / high / critical
    needs_approval: bool = False
    needs_planning: bool = False
    needs_memory: bool = True
    needs_skills: bool = True
    suggested_tools: list[str] = field(default_factory=list)
    reasoning: str = ""
    value_score: float = 0.5          # 0-1, higher = more valuable to execute
    planning_depth: int = 1           # 0=direct, 1=single, 2=multi, 3=decompose

    def to_dict(self) -> dict:
        return {
            "task_type": self.task_type.value,
            "urgency": self.urgency.value,
            "complexity": self.complexity.value,
            "risk_level": self.risk_level,
            "value_score": self.value_score,
            "planning_depth": self.planning_depth,
            "needs_approval": self.needs_approval,
            "needs_planning": self.needs_planning,
            "needs_memory": self.needs_memory,
            "needs_skills": self.needs_skills,
            "suggested_tools": self.suggested_tools,
            "reasoning": self.reasoning,
        }


# ── Keyword patterns ─────────────────────────────────────────────

_TYPE_PATTERNS: dict[TaskType, list[str]] = {
    TaskType.QUERY: ["what is", "who is", "how many", "when", "where", "explain", "define", "tell me", "?"],
    TaskType.ANALYSIS: ["analyze", "analyse", "review", "audit", "compare", "evaluate", "assess", "inspect"],
    TaskType.IMPLEMENTATION: ["create", "build", "implement", "write", "add", "develop", "code", "make"],
    TaskType.DEBUGGING: ["fix", "debug", "repair", "solve", "error", "bug", "broken", "crash", "failing"],
    TaskType.DEPLOYMENT: ["deploy", "release", "docker", "nginx", "server", "production", "rollback"],
    TaskType.RESEARCH: ["search", "find", "research", "look for", "investigate", "discover"],
    TaskType.SYSTEM_OPS: ["restart", "monitor", "status", "health", "logs", "disk", "process", "service"],
    TaskType.IMPROVEMENT: ["improve", "optimize", "refactor", "upgrade", "enhance", "performance"],
    TaskType.WORKFLOW: ["pipeline", "workflow", "sequence", "batch", "orchestrate"],
}

_RISK_KEYWORDS = {
    "critical": ["production", "database", "credentials", "secret", "delete all", "rm -rf", "drop table"],
    "high": ["deploy", "server", "docker", "nginx", "firewall", "ssl", "migration", "revert"],
    "medium": ["write", "modify", "update", "change", "edit", "create file", "install"],
}

_URGENCY_KEYWORDS = {
    "critical": ["urgent", "emergency", "down", "outage", "p0", "critical"],
    "high": ["asap", "important", "priority", "soon", "quickly"],
}


def classify(goal: str) -> MissionClassification:
    """
    Classify a mission goal deterministically.
    No LLM calls — pure keyword analysis + heuristics.
    """
    g = goal.lower().strip()
    set(re.findall(r"[a-z]+", g))

    # Task type
    task_type = _detect_type(g)

    # Urgency
    urgency = Urgency.NORMAL
    for level, keywords in _URGENCY_KEYWORDS.items():
        if any(kw in g for kw in keywords):
            urgency = Urgency(level)
            break

    # Risk
    risk_level = "low"
    for level, keywords in _RISK_KEYWORDS.items():
        if any(kw in g for kw in keywords):
            risk_level = level
            break

    # Complexity (based on goal length and type)
    complexity = _estimate_complexity(g, task_type)

    # Read-only tasks cannot be high/critical risk
    read_only_indicators = ["review", "analyze", "inspect", "list", "show", "describe",
                           "explain", "identify", "what is", "what are", "compare", "audit"]
    is_read_only = any(ind in g for ind in read_only_indicators)
    if is_read_only and risk_level in ("high", "critical"):
        risk_level = "medium"  # Downgrade: read-only tasks have bounded impact

    # Needs approval?
    needs_approval = risk_level in ("high", "critical")

    # Needs planning?
    needs_planning = complexity in (Complexity.MODERATE, Complexity.COMPLEX)

    # Needs memory/skills? (skip for trivial queries)
    needs_memory = complexity != Complexity.TRIVIAL
    needs_skills = complexity != Complexity.TRIVIAL and task_type != TaskType.QUERY

    # Suggested tools
    tools = _suggest_tools(task_type, g)

    reasoning = (
        f"Type={task_type.value} based on goal keywords. "
        f"Complexity={complexity.value} ({len(g)} chars). "
        f"Risk={risk_level}."
    )

    c = MissionClassification(
        task_type=task_type,
        urgency=urgency,
        complexity=complexity,
        risk_level=risk_level,
        needs_approval=needs_approval,
        needs_planning=needs_planning,
        needs_memory=needs_memory,
        needs_skills=needs_skills,
        suggested_tools=tools,
        reasoning=reasoning,
    )

    # ── Value scoring ─────────────────────────────────
    # Factors: urgency, user impact, feasibility, waste risk
    urgency_w = {"low": 0.2, "normal": 0.5, "high": 0.8, "critical": 1.0}
    # Feasibility: simpler tasks are more likely to succeed
    feasibility = {"trivial": 0.95, "simple": 0.85, "moderate": 0.65, "complex": 0.4}
    # User impact: certain task types are inherently more valuable
    impact = {
        "research": 0.7, "analysis": 0.8, "creation": 0.8,
        "deployment": 0.9, "debugging": 0.9, "system_ops": 0.7,
        "monitoring": 0.5, "query": 0.3, "business": 0.85, "other": 0.5,
    }
    u = urgency_w.get(c.urgency.value, 0.5)
    f = feasibility.get(c.complexity.value, 0.6)
    i = impact.get(c.task_type.value, 0.5)
    # Value = impact-weighted urgency, penalized by infeasibility
    c.value_score = round(u * 0.4 + i * 0.3 + f * 0.3, 3)

    # ── Planning depth from complexity ────────────────
    depth_map = {"trivial": 0, "simple": 1, "moderate": 2, "complex": 3}
    c.planning_depth = depth_map.get(c.complexity.value, 1)

    return c


def _detect_type(g: str) -> TaskType:
    scores: dict[TaskType, int] = {}
    for ttype, patterns in _TYPE_PATTERNS.items():
        score = sum(1 for p in patterns if p in g)
        if score > 0:
            scores[ttype] = score
    if not scores:
        # Business intent
        business_kw = {"business", "opportunity", "revenue", "offer", "service",
                       "customer", "pricing", "saas", "landing", "prospect",
                       "monetize", "startup", "acquisition"}
        if any(kw in g for kw in business_kw):
            return TaskType.BUSINESS
        return TaskType.OTHER

    # Check if business keywords are present even with other type matches
    business_kw = {"business", "opportunity", "revenue", "offer",
                   "monetize", "startup", "saas", "prospect"}
    biz_score = sum(1 for kw in business_kw if kw in g)
    if biz_score >= 2:
        return TaskType.BUSINESS

    return max(scores, key=scores.get)


def _estimate_complexity(g: str, task_type: TaskType) -> Complexity:
    length = len(g)
    if length < 30 and task_type == TaskType.QUERY:
        return Complexity.TRIVIAL
    if length < 60:
        return Complexity.SIMPLE
    if length < 150:
        return Complexity.MODERATE
    return Complexity.COMPLEX


def _suggest_tools(task_type: TaskType, g: str) -> list[str]:
    tools = []
    if task_type in (TaskType.SYSTEM_OPS, TaskType.DEPLOYMENT, TaskType.DEBUGGING):
        tools.append("shell")
    if task_type == TaskType.RESEARCH:
        tools.append("http_get")
    if "file" in g or "code" in g or "script" in g:
        tools.append("file_write")
    if "test" in g:
        tools.append("test_runner")
    if "git" in g:
        tools.append("git")
    if "docker" in g:
        tools.append("shell")
    return tools[:5]
