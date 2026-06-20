"""
core/capabilities/ai_os_capabilities.py — AI OS Capability Registry.

Structured capability descriptions that define what Bea can do.
Each capability maps to tool chains, agent types, schemas, and policies.
Integrates with MetaOrchestrator for plan generation.

NOT a replacement for registry.py (tool-level) — this is mission-level.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Literal, Optional


@dataclass
class RetryStrategy:
    """Retry configuration for a capability."""
    max_attempts: int = 1
    backoff_seconds: float = 1.0
    retryable_errors: tuple[str, ...] = ("TRANSIENT", "TIMEOUT")

    def to_dict(self) -> dict:
        return {"max_attempts": self.max_attempts, "backoff_seconds": self.backoff_seconds,
                "retryable_errors": list(self.retryable_errors)}


@dataclass
class TimeoutProfile:
    """Timeout configuration for a capability."""
    planning_seconds: int = 30
    execution_seconds: int = 120
    review_seconds: int = 30
    total_seconds: int = 300

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AIOSCapability:
    """Full AI OS capability descriptor."""
    name: str
    description: str
    risk_level: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "MEDIUM"
    required_tools: tuple[str, ...] = ()
    required_agent_type: str = "auto"  # planner, researcher, operator, critic, auto
    input_schema: dict = field(default_factory=lambda: {"goal": "str", "context": "str?"})
    output_schema: dict = field(default_factory=lambda: {"result": "str", "confidence": "float"})
    retry_strategy: RetryStrategy = field(default_factory=RetryStrategy)
    timeout_profile: TimeoutProfile = field(default_factory=TimeoutProfile)
    policy_requirements: dict = field(default_factory=lambda: {"min_approval": "none", "budget_usd": 0.50})
    enabled: bool = True

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "risk_level": self.risk_level,
            "required_tools": list(self.required_tools),
            "required_agent_type": self.required_agent_type,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "retry_strategy": self.retry_strategy.to_dict(),
            "timeout_profile": self.timeout_profile.to_dict(),
            "policy_requirements": self.policy_requirements,
            "enabled": self.enabled,
        }


# ── AI OS Capability Definitions ──────────────────────────────────────────────

AIOS_CAPABILITIES: dict[str, AIOSCapability] = {}


def _register(cap: AIOSCapability):
    AIOS_CAPABILITIES[cap.name] = cap


_register(AIOSCapability(
    name="market_research",
    description="Research markets, competitors, trends, and opportunities",
    risk_level="LOW",
    required_tools=("web_search", "web_fetch"),
    required_agent_type="researcher",
    output_schema={"findings": "str", "sources": "list[str]", "confidence": "float"},
    timeout_profile=TimeoutProfile(execution_seconds=60, total_seconds=180),
))

_register(AIOSCapability(
    name="repo_audit",
    description="Audit a code repository for quality, security, and architecture",
    risk_level="MEDIUM",
    required_tools=("file_read", "shell_execute"),
    required_agent_type="critic",
    output_schema={"issues": "list[dict]", "score": "float", "recommendations": "list[str]"},
    timeout_profile=TimeoutProfile(execution_seconds=120, total_seconds=300),
    policy_requirements={"min_approval": "auto", "budget_usd": 1.00},
))

_register(AIOSCapability(
    name="code_generation",
    description="Generate code files, functions, or modules from specifications",
    risk_level="MEDIUM",
    required_tools=("file_write", "code_execute"),
    required_agent_type="operator",
    output_schema={"files_created": "list[str]", "code": "str", "tests": "str?"},
    retry_strategy=RetryStrategy(max_attempts=2),
    timeout_profile=TimeoutProfile(execution_seconds=90, total_seconds=240),
))

_register(AIOSCapability(
    name="api_test",
    description="Test API endpoints for correctness, performance, and security",
    risk_level="LOW",
    required_tools=("http_request", "http_test"),
    required_agent_type="operator",
    output_schema={"results": "list[dict]", "pass_rate": "float", "errors": "list[str]"},  # nosec B105 — schema field types, not credentials
    timeout_profile=TimeoutProfile(execution_seconds=60, total_seconds=120),
))

_register(AIOSCapability(
    name="document_generation",
    description="Generate structured documents: reports, specs, guides",
    risk_level="LOW",
    required_tools=("markdown_generate", "file_write"),
    required_agent_type="operator",
    output_schema={"document": "str", "format": "str", "word_count": "int"},
    timeout_profile=TimeoutProfile(execution_seconds=45, total_seconds=120),
))

_register(AIOSCapability(
    name="workflow_design",
    description="Design multi-step workflows and automation pipelines",
    risk_level="MEDIUM",
    required_tools=("file_write",),
    required_agent_type="planner",
    output_schema={"workflow": "dict", "steps": "list[dict]", "estimated_duration": "int"},
    timeout_profile=TimeoutProfile(planning_seconds=60, total_seconds=240),
))

_register(AIOSCapability(
    name="data_analysis",
    description="Analyze data sets, compute statistics, extract insights",
    risk_level="LOW",
    required_tools=("file_read", "code_execute"),
    required_agent_type="researcher",
    output_schema={"insights": "list[str]", "metrics": "dict", "visualization": "str?"},
    timeout_profile=TimeoutProfile(execution_seconds=90, total_seconds=240),
))

_register(AIOSCapability(
    name="memory_update",
    description="Store, retrieve, or reorganize system memory",
    risk_level="LOW",
    required_tools=("memory_write", "memory_read"),
    required_agent_type="auto",
    output_schema={"updated": "bool", "entries_affected": "int"},
    timeout_profile=TimeoutProfile(execution_seconds=10, total_seconds=30),
    policy_requirements={"min_approval": "none", "budget_usd": 0.01},
))

_register(AIOSCapability(
    name="system_diagnosis",
    description="Diagnose system health, performance issues, and errors",
    risk_level="MEDIUM",
    required_tools=("shell_execute", "file_read"),
    required_agent_type="operator",
    output_schema={"status": "str", "issues": "list[dict]", "recommendations": "list[str]"},
    timeout_profile=TimeoutProfile(execution_seconds=60, total_seconds=180),
    policy_requirements={"min_approval": "auto", "budget_usd": 0.50},
))


# ── Query API ────────────────────────────────────────────────────────────────

def get_capability(name: str) -> Optional[AIOSCapability]:
    """Get a capability by name."""
    return AIOS_CAPABILITIES.get(name)


def list_capabilities(risk_level: str = "", agent_type: str = "", enabled_only: bool = True) -> list[AIOSCapability]:
    """List capabilities with optional filters."""
    caps = list(AIOS_CAPABILITIES.values())
    if enabled_only:
        caps = [c for c in caps if c.enabled]
    if risk_level:
        caps = [c for c in caps if c.risk_level == risk_level]
    if agent_type:
        caps = [c for c in caps if c.required_agent_type == agent_type or c.required_agent_type == "auto"]
    return caps


def match_capability(goal: str) -> list[AIOSCapability]:
    """Simple keyword matching to suggest capabilities for a goal."""
    goal_lower = goal.lower()
    matches = []
    for cap in AIOS_CAPABILITIES.values():
        if not cap.enabled:
            continue
        # Check name and description keywords
        keywords = cap.name.replace("_", " ").split() + cap.description.lower().split()
        score = sum(1 for kw in keywords if kw in goal_lower)
        if score > 0:
            matches.append((score, cap))
    matches.sort(key=lambda x: -x[0])
    return [cap for _, cap in matches[:3]]


def capability_summary() -> dict:
    """Summary for diagnostic/API endpoints."""
    return {
        "total": len(AIOS_CAPABILITIES),
        "enabled": sum(1 for c in AIOS_CAPABILITIES.values() if c.enabled),
        "by_risk": {
            "LOW": sum(1 for c in AIOS_CAPABILITIES.values() if c.risk_level == "LOW"),
            "MEDIUM": sum(1 for c in AIOS_CAPABILITIES.values() if c.risk_level == "MEDIUM"),
            "HIGH": sum(1 for c in AIOS_CAPABILITIES.values() if c.risk_level == "HIGH"),
        },
        "capabilities": [c.name for c in AIOS_CAPABILITIES.values() if c.enabled],
    }
