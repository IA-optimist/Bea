"""
BEA MAX — Dynamic Agent Factory
Creates new agent classes at runtime from blueprints and registers them in AgentCrew.

Usage:
    factory = AgentFactory(settings)
    bp      = AgentBlueprint(name="summarizer", role="builder",
                             system_prompt="You are a concise summarizer.")
    agent   = factory.create_agent(bp)
    agent   = await factory.create_from_llm("An agent that summarizes emails")
    factory.destroy_agent("summarizer")
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any

import structlog
from pydantic import BaseModel, Field

log = structlog.get_logger(__name__)


# ── Blueprint ─────────────────────────────────────────────────

class AgentBlueprint(BaseModel):
    name:          str           = Field(..., min_length=1, max_length=64,
                                         pattern=r'^[a-z0-9_-]+$')
    role:          str           = Field("builder",
                                         description="LLM role key (builder/planner/reviewer/default)")
    system_prompt: str           = Field(..., min_length=10, max_length=8000)
    description:   str           = Field("", description="Human-readable purpose")
    tools:         list[str]     = Field(default_factory=list,
                                         description="Tool names this agent may use")
    timeout_s:     int           = Field(120, ge=5, le=600)
    max_reruns:    int           = Field(1, ge=0, le=3)
    created_at:    float         = Field(default_factory=time.time)
    created_by:    str           = Field("factory")

    class Config:
        extra = "allow"

    def to_dict(self) -> dict:
        return self.model_dump()


# ── DynamicAgent base ─────────────────────────────────────────

def _make_dynamic_agent_class(bp: AgentBlueprint, settings):
    """
    Dynamically create a concrete BaseAgent subclass from a blueprint.
    Returns an instantiated agent, not the class.
    """
    from agents.crew import BaseAgent
    from core.state import BeaSession

    class DynamicAgent(BaseAgent):
        name:      str = bp.name
        role:      str = bp.role
        timeout_s: int = bp.timeout_s

        def __init__(self, s):
            super().__init__(s)
            self._blueprint = bp

        def system_prompt(self) -> str:
            return bp.system_prompt

        def user_message(self, session: BeaSession) -> str:
            return self._task(session)

    DynamicAgent.__name__     = f"DynamicAgent_{bp.name}"
    DynamicAgent.__qualname__ = f"DynamicAgent_{bp.name}"
    return DynamicAgent(settings)


# ── AgentFactory ──────────────────────────────────────────────

class AgentFactory:
    """
    Creates and manages runtime-generated agents.
    Thread/async safe via asyncio.Lock.
    """

    def __init__(self, settings=None) -> None:
        self.s            = settings or self._get_settings()
        self._lock        = asyncio.Lock()
        self._blueprints: dict[str, AgentBlueprint] = {}   # name → blueprint
        self._crew        = None   # lazy AgentCrew reference

    @staticmethod
    def _get_settings():
        try:
            from config.settings import get_settings
            return get_settings()
        except Exception:
            return None

    def _get_crew(self):
        if self._crew is None:
            try:
                from agents.crew import AgentCrew
                self._crew = AgentCrew(self.s)
            except Exception as e:
                log.warning("agent_factory_crew_unavailable", err=str(e)[:80])
        return self._crew

    # ── create_agent ──────────────────────────────────────────

    async def create_agent(self, blueprint: AgentBlueprint):
        """
        Instantiate a DynamicAgent from blueprint and register it in AgentCrew.
        Returns the new agent instance.
        """
        async with self._lock:
            if blueprint.name in self._blueprints:
                log.warning("agent_factory_overwriting", name=blueprint.name)

            agent = _make_dynamic_agent_class(blueprint, self.s)
            self._blueprints[blueprint.name] = blueprint

            crew = self._get_crew()
            if crew is not None:
                crew.registry[blueprint.name] = agent
                log.info("agent_factory_registered", name=blueprint.name, role=blueprint.role)
            else:
                log.warning("agent_factory_no_crew", name=blueprint.name)

            return agent

    # ── create_from_llm ───────────────────────────────────────

    async def create_from_llm(self, objective: str) -> Any:
        """
        Ask an LLM to design a blueprint for the given objective,
        then create and register the agent.
        Returns the new agent, or raises on failure.
        """
        blueprint = await self._design_blueprint(objective)
        log.info("agent_factory_llm_designed", name=blueprint.name, objective=objective[:80])
        return await self.create_agent(blueprint)

    async def _design_blueprint(self, objective: str) -> AgentBlueprint:
        """Call LLM to produce a JSON blueprint, with fallback to a safe default."""
        design_prompt = f"""Design a BeaMax agent blueprint as a JSON object.

Objective: {objective}

Return ONLY valid JSON with these exact fields:
{{
  "name": "<lowercase-hyphenated, e.g. email-summarizer>",
  "role": "<one of: builder, planner, reviewer, default>",
  "system_prompt": "<detailed system prompt, 2-5 sentences>",
  "description": "<one sentence description>",
  "tools": [],
  "timeout_s": <integer 30-300>,
  "max_reruns": <0, 1, or 2>
}}

Return only the JSON object, no markdown fences."""

        raw_json = None

        # Try LLMFactory
        try:
            from config.settings import get_settings
            from core.llm_factory import LLMFactory
            from langchain_core.messages import HumanMessage, SystemMessage
            llm  = LLMFactory(get_settings()).get("builder")
            msgs = [
                SystemMessage(content="You are a JSON-only blueprint designer. Return only valid JSON."),
                HumanMessage(content=design_prompt),
            ]
            resp     = await llm.ainvoke(msgs)
            raw_json = resp.content if hasattr(resp, "content") else str(resp)
        except Exception as e:
            log.debug("agent_factory_llm_design_failed", err=str(e)[:80])

        # Try direct OpenAI
        if not raw_json:
            api_key = os.getenv("OPENAI_API_KEY", "")
            if api_key:
                try:
                    import openai as _openai
                    client = _openai.AsyncOpenAI(api_key=api_key)
                    resp   = await client.chat.completions.create(
                        model      = "gpt-4o-mini",
                        messages   = [
                            {"role": "system", "content": "Return only valid JSON."},
                            {"role": "user",   "content": design_prompt},
                        ],
                        max_tokens = 512,
                        response_format={"type": "json_object"},
                    )
                    raw_json = resp.choices[0].message.content or ""
                except Exception as e:
                    log.debug("agent_factory_openai_design_failed", err=str(e)[:80])

        # Parse JSON
        if raw_json:
            try:
                # Strip markdown fences if present
                cleaned = raw_json.strip()
                if cleaned.startswith("```"):
                    cleaned = "\n".join(cleaned.split("\n")[1:])
                    cleaned = cleaned.rstrip("`").strip()
                data = json.loads(cleaned)
                return AgentBlueprint(**data)
            except Exception as e:
                log.warning("agent_factory_blueprint_parse_failed", err=str(e)[:80])

        # Fallback: derive from objective
        safe_name = (
            objective.lower()
            .replace(" ", "-")
            .replace("_", "-")
            [:32]
            .strip("-")
        )
        # Sanitize to allowed chars
        import re
        safe_name = re.sub(r"[^a-z0-9-]", "", safe_name) or "custom-agent"
        return AgentBlueprint(
            name          = safe_name,
            role          = "builder",
            system_prompt = (
                f"You are a specialized BeaMax agent. "
                f"Your objective: {objective}. "
                f"Respond concisely and focus on achieving the stated goal."
            ),
            description   = objective[:120],
        )

    # ── list / destroy ────────────────────────────────────────

    def list_dynamic_agents(self) -> list[dict]:
        """Returns blueprint info for all runtime-created agents."""
        return [bp.to_dict() for bp in self._blueprints.values()]

    async def destroy_agent(self, name: str) -> bool:
        """Unregister an agent from crew and remove its blueprint."""
        async with self._lock:
            if name not in self._blueprints:
                return False
            del self._blueprints[name]
            crew = self._get_crew()
            if crew and name in crew.registry:
                del crew.registry[name]
            log.info("agent_factory_destroyed", name=name)
            return True

    def get_blueprint(self, name: str) -> AgentBlueprint | None:
        return self._blueprints.get(name)


# ── Singleton ─────────────────────────────────────────────────

_factory: AgentFactory | None = None


def get_agent_factory(settings=None) -> AgentFactory:
    global _factory
    if _factory is None:
        _factory = AgentFactory(settings)
    return _factory
