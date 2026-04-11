"""
JARVIS MAX — Business Agent Factory
=====================================
Instantiates business agents from templates with business-specific config.

Usage:
    from business_agents.factory import AgentFactory
    factory = AgentFactory()
    agent = factory.create("quote_agent", {
        "business_name": "Smith Heating Ltd",
        "business_type": "HVAC",
        "service_area": "London",
        "currency": "GBP",
    })
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from business_agents.template_schema import BusinessAgentTemplate, FieldSchema
from business_agents.template_registry import get_template, list_templates
_silent_log = __import__("structlog").get_logger(__name__)


@dataclass
class GeneratedAgent:
    """A concrete business agent instance generated from a template."""
    # Identity
    id: str = ""
    template_name: str = ""
    business_name: str = ""
    business_type: str = ""

    # Config
    config: dict = field(default_factory=dict)
    prompt_config: dict = field(default_factory=dict)
    capability_bindings: list[str] = field(default_factory=list)
    tool_bindings: list[str] = field(default_factory=list)
    memory_config: dict = field(default_factory=dict)

    # Metadata
    version: str = "1.0.0"
    created_at: float = field(default_factory=time.time)
    status: str = "created"       # created, tested, active, disabled
    last_test_result: dict = field(default_factory=dict)
    score: float = 0.0

    # Resolved prompts
    system_prompt: str = ""
    user_prompt_template: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "template": self.template_name,
            "business_name": self.business_name,
            "business_type": self.business_type,
            "config": self.config,
            "capabilities": self.capability_bindings,
            "tools": self.tool_bindings,
            "memory_config": self.memory_config,
            "version": self.version,
            "status": self.status,
            "last_test_result": self.last_test_result,
            "score": self.score,
            "created_at": self.created_at,
        }

    def execute(self, input_data: dict) -> dict:
        """
        Execute this agent on input data.

        Returns structured output matching the template's output_schema.
        For now, this validates input and delegates to LLM via prompt.
        """
        # Validate required inputs
        template = get_template(self.template_name)
        if template:
            missing = []
            for field_def in template.input_schema:
                if field_def.required and field_def.name not in input_data:
                    missing.append(field_def.name)
            if missing:
                return {
                    "error": f"Missing required fields: {missing}",
                    "status": "validation_error",
                    "clarifying_questions": [f"Please provide: {f}" for f in missing],
                }

        # Resolve user prompt
        user_prompt = self.user_prompt_template
        for key, value in input_data.items():
            user_prompt = user_prompt.replace(f"{{{{{key}}}}}", str(value))
        for key, value in self.config.items():
            user_prompt = user_prompt.replace(f"{{{{{key}}}}}", str(value))

        # Build execution context
        return {
            "agent_id": self.id,
            "system_prompt": self.system_prompt,
            "user_prompt": user_prompt,
            "tools": self.tool_bindings,
            "memory_scopes": list(self.memory_config.keys()),
            "status": "ready_for_llm",
            "input_validated": True,
        }


def _resolve_prompt(template_content: str, config: dict) -> str:
    """Replace {{variable}} placeholders with config values."""
    result = template_content
    for key, value in config.items():
        result = result.replace(f"{{{{{key}}}}}", str(value))
    return result


def _generate_test_scenarios(template: BusinessAgentTemplate, config: dict) -> list[dict]:
    """Generate test scenarios for a newly created agent."""
    scenarios = []

    # Scenario 1: Valid complete input
    valid_input = {}
    for f in template.input_schema:
        if f.type == "string":
            valid_input[f.name] = f"test_{f.name}_value" if f.required else ""
        elif f.type == "number":
            valid_input[f.name] = 42
        elif f.type == "boolean":
            valid_input[f.name] = True
        elif f.type == "list":
            valid_input[f.name] = ["item1"]
        elif f.type == "object":
            valid_input[f.name] = {"key": "value"}
    scenarios.append({"name": "valid_complete", "input": valid_input, "expected": "success"})

    # Scenario 2: Missing required fields
    scenarios.append({"name": "missing_required", "input": {}, "expected": "validation_error"})

    # Scenario 3: Minimal valid input (only required fields)
    minimal = {f.name: f"min_{f.name}" for f in template.input_schema
               if f.required and f.type == "string"}
    scenarios.append({"name": "minimal_valid", "input": minimal, "expected": "success"})

    return scenarios


class AgentFactory:
    """
    Factory for creating business agents from templates.

    Generated agents are stored in business_agents/generated/ and
    registered in the agent registry.
    """

    def __init__(self, persist_dir: Path | None = None):
        self._persist_dir = persist_dir or Path("business_agents/generated")
        self._agents: dict[str, GeneratedAgent] = {}
        self._load()

    def create(self, template_name: str, config: dict) -> GeneratedAgent:
        """
        Create a business agent from a template with business-specific config.

        Args:
            template_name: name of the template (e.g., "quote_agent")
            config: business-specific config (business_name, business_type, etc.)

        Returns:
            GeneratedAgent ready for testing and activation.

        Raises:
            ValueError if template not found or invalid config.
        """
        template = get_template(template_name)
        if not template:
            available = [t["name"] for t in list_templates()]
            raise ValueError(f"Template '{template_name}' not found. Available: {available}")

        # Generate unique ID
        business_name = config.get("business_name", "unknown")
        agent_id = f"ba-{template_name}-{hashlib.md5(f'{business_name}:{time.time()}'.encode()).hexdigest()[:8]}"

        # Resolve prompts
        system_prompt = _resolve_prompt(template.system_prompt.content, config)
        user_prompt_template = _resolve_prompt(template.user_prompt_template, config)

        # Generate test scenarios
        test_scenarios = _generate_test_scenarios(template, config)

        agent = GeneratedAgent(
            id=agent_id,
            template_name=template_name,
            business_name=business_name,
            business_type=config.get("business_type", template.business_type),
            config=config,
            prompt_config={
                "system_prompt_version": template.system_prompt.version,
                "variables_resolved": list(config.keys()),
            },
            capability_bindings=list(template.allowed_capabilities),
            tool_bindings=list(template.required_tools),
            memory_config={scope: {} for scope in template.memory_scopes},
            version=template.version,
            system_prompt=system_prompt,
            user_prompt_template=user_prompt_template,
        )

        # Store
        self._agents[agent.id] = agent
        self._save_agent(agent, test_scenarios)
        return agent

    def get(self, agent_id: str) -> GeneratedAgent | None:
        return self._agents.get(agent_id)

    def list_agents(self) -> list[dict]:
        return [a.to_dict() for a in self._agents.values()]

    def get_agents_by_template(self, template_name: str) -> list[GeneratedAgent]:
        return [a for a in self._agents.values() if a.template_name == template_name]

    def activate(self, agent_id: str) -> bool:
        agent = self._agents.get(agent_id)
        if agent and agent.status in ("created", "tested"):
            agent.status = "active"
            self._save_agent(agent)
            return True
        return False

    def disable(self, agent_id: str) -> bool:
        agent = self._agents.get(agent_id)
        if agent:
            agent.status = "disabled"
            self._save_agent(agent)
            return True
        return False

    def update_test_result(self, agent_id: str, result: dict) -> None:
        agent = self._agents.get(agent_id)
        if agent:
            agent.last_test_result = result
            agent.score = result.get("score", 0.0)
            if result.get("passed", False):
                agent.status = "tested"
            self._save_agent(agent)

    def _save_agent(self, agent: GeneratedAgent,
                    test_scenarios: list[dict] | None = None) -> None:
        try:
            self._persist_dir.mkdir(parents=True, exist_ok=True)
            path = self._persist_dir / f"{agent.id}.json"
            data = agent.to_dict()
            if test_scenarios:
                data["test_scenarios"] = test_scenarios
            path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        except Exception:
            _silent_log.debug("suppressed_exception", src='factory.py')

    def _load(self) -> None:
        if not self._persist_dir.exists():
            return
        for path in self._persist_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                agent = GeneratedAgent(
                    id=data.get("id", ""),
                    template_name=data.get("template", ""),
                    business_name=data.get("business_name", ""),
                    business_type=data.get("business_type", ""),
                    config=data.get("config", {}),
                    capability_bindings=data.get("capabilities", []),
                    tool_bindings=data.get("tools", []),
                    memory_config=data.get("memory_config", {}),
                    version=data.get("version", "1.0.0"),
                    status=data.get("status", "created"),
                    last_test_result=data.get("last_test_result", {}),
                    score=data.get("score", 0.0),
                    created_at=data.get("created_at", 0),
                )
                self._agents[agent.id] = agent
            except Exception:
                _silent_log.debug("suppressed_exception", src='factory.py')

    def get_registry_summary(self) -> dict:
        """Summary for the operator view."""
        agents = list(self._agents.values())
        return {
            "total_agents": len(agents),
            "by_status": {
                "created": sum(1 for a in agents if a.status == "created"),
                "tested": sum(1 for a in agents if a.status == "tested"),
                "active": sum(1 for a in agents if a.status == "active"),
                "disabled": sum(1 for a in agents if a.status == "disabled"),
            },
            "by_template": {
                name: sum(1 for a in agents if a.template_name == name)
                for name in set(a.template_name for a in agents)
            },
            "agents": [a.to_dict() for a in agents],
        }
