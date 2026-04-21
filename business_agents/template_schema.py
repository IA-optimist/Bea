"""
JARVIS MAX — Business Agent Template Schema
=============================================
Defines the formal structure every business agent template must follow.

Every generated agent must declare:
  - purpose, tools, memory usage, risk level
  - expected outputs, evaluation criteria
  - prompt contracts, input/output schemas
  - fallback behavior
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RiskLevel(str, Enum):
    LOW = "low"           # read-only, no side effects
    MEDIUM = "medium"     # writes to local storage
    HIGH = "high"         # external communication (email, API calls)
    CRITICAL = "critical" # financial transactions, PII handling


class MemoryScope(str, Enum):
    AGENT_LOCAL = "agent_local_memory"
    CLIENT_CONTEXT = "client_context_memory"
    BUSINESS_PROFILE = "business_profile_memory"
    REUSABLE_RESPONSE = "reusable_response_memory"


@dataclass
class PromptContract:
    """Versioned prompt definition."""
    role: str = "system"
    content: str = ""
    version: str = "1.0.0"
    variables: list[str] = field(default_factory=list)  # {{business_name}}, etc.


@dataclass
class FieldSchema:
    """Single field in input/output schema."""
    name: str
    type: str = "string"    # string, number, boolean, list, object
    required: bool = True
    description: str = ""
    default: Any = None


@dataclass
class EvaluationRule:
    """Rule for evaluating agent output quality."""
    name: str
    description: str
    check_type: str = "presence"  # presence, length, format, keyword, schema
    target_field: str = ""
    threshold: Any = None          # min length, regex pattern, etc.


@dataclass
class FallbackBehavior:
    """What happens when the agent can't complete its task."""
    strategy: str = "escalate"  # escalate, default_response, retry, partial
    max_retries: int = 2
    default_response: str = ""
    escalation_target: str = "human"


@dataclass
class BusinessAgentTemplate:
    """
    Complete template definition for a business agent.

    This is the source of truth — every generated agent inherits from one.
    """
    # Identity
    agent_name: str = ""
    business_type: str = ""        # plumber, electrician, ecommerce, saas, etc.
    purpose: str = ""
    version: str = "1.0.0"
    category: str = ""             # quote, support, content, sales, ops

    # Capabilities
    allowed_capabilities: list[str] = field(default_factory=list)
    preferred_models: list[str] = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)

    # Memory
    memory_scopes: list[str] = field(default_factory=list)

    # Risk
    risk_profile: str = "low"

    # Prompts
    system_prompt: PromptContract = field(default_factory=PromptContract)
    user_prompt_template: str = ""

    # Schemas
    input_schema: list[FieldSchema] = field(default_factory=list)
    output_schema: list[FieldSchema] = field(default_factory=list)

    # Evaluation
    evaluation_rules: list[EvaluationRule] = field(default_factory=list)

    # Fallback
    fallback: FallbackBehavior = field(default_factory=FallbackBehavior)

    def validate(self) -> list[str]:
        """Validate template completeness. Returns list of errors."""
        errors = []
        if not self.agent_name:
            errors.append("agent_name is required")
        if not self.purpose:
            errors.append("purpose is required")
        if not self.allowed_capabilities:
            errors.append("at least one capability required")
        if not self.input_schema:
            errors.append("input_schema is required")
        if not self.output_schema:
            errors.append("output_schema is required")
        if not self.evaluation_rules:
            errors.append("at least one evaluation_rule required")
        if not self.system_prompt.content:
            errors.append("system_prompt content is required")
        if self.risk_profile not in ("low", "medium", "high", "critical"):
            errors.append(f"invalid risk_profile: {self.risk_profile}")
        return errors

    def to_dict(self) -> dict:
        return {
            "agent_name": self.agent_name,
            "business_type": self.business_type,
            "purpose": self.purpose,
            "version": self.version,
            "category": self.category,
            "allowed_capabilities": self.allowed_capabilities,
            "preferred_models": self.preferred_models,
            "required_tools": self.required_tools,
            "memory_scopes": self.memory_scopes,
            "risk_profile": self.risk_profile,
            "system_prompt": {
                "role": self.system_prompt.role,
                "content": self.system_prompt.content[:200] + "..." if len(self.system_prompt.content) > 200 else self.system_prompt.content,
                "version": self.system_prompt.version,
                "variables": self.system_prompt.variables,
            },
            "input_schema": [{"name": f.name, "type": f.type, "required": f.required}
                             for f in self.input_schema],
            "output_schema": [{"name": f.name, "type": f.type, "required": f.required}
                              for f in self.output_schema],
            "evaluation_rules": [{"name": r.name, "check_type": r.check_type}
                                 for r in self.evaluation_rules],
            "fallback": {"strategy": self.fallback.strategy,
                         "max_retries": self.fallback.max_retries},
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BusinessAgentTemplate":
        """Load template from dict (e.g., parsed YAML/JSON)."""
        t = cls()
        for key in ("agent_name", "business_type", "purpose", "version",
                     "category", "allowed_capabilities", "preferred_models",
                     "required_tools", "memory_scopes", "risk_profile",
                     "user_prompt_template"):
            if key in data:
                setattr(t, key, data[key])

        if "system_prompt" in data:
            sp = data["system_prompt"]
            t.system_prompt = PromptContract(
                role=sp.get("role", "system"),
                content=sp.get("content", ""),
                version=sp.get("version", "1.0.0"),
                variables=sp.get("variables", []),
            )

        if "input_schema" in data:
            t.input_schema = [FieldSchema(**f) for f in data["input_schema"]]

        if "output_schema" in data:
            t.output_schema = [FieldSchema(**f) for f in data["output_schema"]]

        if "evaluation_rules" in data:
            t.evaluation_rules = [EvaluationRule(**r) for r in data["evaluation_rules"]]

        if "fallback" in data:
            t.fallback = FallbackBehavior(**data["fallback"])

        return t
