"""
JARVIS MAX — Agent Builder API Routes

POST /api/v2/agents/create        — create from blueprint or objective (auto-design)
GET  /api/v2/agents               — list all agents (static + dynamic)
DELETE /api/v2/agents/{name}      — destroy a dynamic agent
"""
from __future__ import annotations

import os
from typing import Any, Optional

import structlog
from fastapi import Depends, APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from api._deps import _check_auth

log = structlog.get_logger(__name__)


def _auth(x_jarvis_token: str | None = Header(None),
          authorization: str | None = Header(None)):
    _check_auth(x_jarvis_token, authorization)



router = APIRouter(prefix="/api/v2/agents", tags=["agents"], dependencies=[Depends(_auth)])

_API_TOKEN = os.getenv("JARVIS_API_TOKEN", "")


# ── Request models ────────────────────────────────────────────

class CreateAgentRequest(BaseModel):
    # Either provide a full blueprint OR just an objective (auto-design)
    objective:     Optional[str]       = Field(None, description="Auto-design mode: describe what the agent should do")
    name:          Optional[str]       = Field(None)
    role:          Optional[str]       = Field(None)
    system_prompt: Optional[str]       = Field(None)
    description:   Optional[str]       = Field(None)
    tools:         list[str]           = Field(default_factory=list)
    timeout_s:     int                 = Field(120, ge=5, le=600)
    max_reruns:    int                 = Field(1, ge=0, le=3)


# ── Endpoints ─────────────────────────────────────────────────

@router.post("/create", status_code=201)
async def create_agent(
    req: CreateAgentRequest,
    x_jarvis_token: Optional[str] = Header(None),
):
    """
    Create a dynamic agent.
    - Provide 'objective' for auto-design via LLM.
    - Provide 'name' + 'system_prompt' for manual blueprint.
    """
    from core.agent_factory import get_agent_factory

    factory = get_agent_factory()

    # Auto-design mode
    if req.objective and not req.name:
        try:
            agent = await factory.create_from_llm(req.objective)
            bp    = factory.get_blueprint(agent.name)
            return {
                "ok":      True,
                "mode":    "auto_designed",
                "data":    bp.to_dict() if bp else {"name": agent.name},
            }
        except Exception as e:
            log.error("create_agent_auto_failed", err=str(e)[:120])
            raise HTTPException(status_code=500, detail=f"Auto-design failed: {e}")

    # Manual blueprint mode
    if not req.name or not req.system_prompt:
        raise HTTPException(
            status_code=422,
            detail="Provide either 'objective' (auto-design) or both 'name' and 'system_prompt'.",
        )

    try:
        from core.agent_factory import AgentBlueprint
        bp    = AgentBlueprint(
            name          = req.name,
            role          = req.role or "builder",
            system_prompt = req.system_prompt,
            description   = req.description or "",
            tools         = req.tools,
            timeout_s     = req.timeout_s,
            max_reruns    = req.max_reruns,
        )
        await factory.create_agent(bp)
        return {
            "ok":   True,
            "mode": "manual",
            "data": bp.to_dict(),
        }
    except Exception as e:
        log.error("create_agent_manual_failed", err=str(e)[:120])
        raise HTTPException(status_code=400, detail=str(e))


@router.get("")
async def list_agents(x_jarvis_token: Optional[str] = Header(None)):
    """List all registered agents — static crew + dynamic factory agents."""
    agents: list[dict[str, Any]] = []

    # Static crew agents
    try:
        from config.settings import get_settings
        from agents.crew import AgentCrew
        crew = AgentCrew(get_settings())
        for name, agent in crew.registry.items():
            agents.append({
                "name":    name,
                "role":    getattr(agent, "role", "?"),
                "timeout": getattr(agent, "timeout_s", "?"),
                "dynamic": False,
                "status":  "registered",
            })
    except Exception as e:
        log.warning("list_agents_crew_failed", err=str(e)[:80])

    # Dynamic factory agents (merge / mark as dynamic)
    try:
        from core.agent_factory import get_agent_factory
        factory = get_agent_factory()
        dynamic_names = {bp["name"] for bp in factory.list_dynamic_agents()}
        # Mark dynamic ones
        for a in agents:
            if a["name"] in dynamic_names:
                a["dynamic"] = True
        # Add any dynamic agents not yet in crew listing
        crew_names = {a["name"] for a in agents}
        for bp in factory.list_dynamic_agents():
            if bp["name"] not in crew_names:
                agents.append({
                    "name":        bp["name"],
                    "role":        bp.get("role", "?"),
                    "timeout":     bp.get("timeout_s", 120),
                    "dynamic":     True,
                    "description": bp.get("description", ""),
                    "status":      "registered",
                })
    except Exception as e:
        log.warning("list_agents_factory_failed", err=str(e)[:80])

    return {"ok": True, "data": {"agents": agents, "total": len(agents)}}


@router.get("/metadata")
async def agent_metadata():
    """Rich agent metadata: capabilities, model, risk tier, latency."""
    agents = []
    try:
        from config.settings import get_settings
        from agents.crew import AgentCrew
        s = get_settings()
        crew = AgentCrew(s)

        # Role → model mapping
        role_models = {
            "director": getattr(s, "orchestrator_model", "ollama/mistral:7b"),
            "research": getattr(s, "orchestrator_model", "ollama/mistral:7b"),
            "planner": getattr(s, "orchestrator_model", "ollama/mistral:7b"),
            "builder": getattr(s, "coder_model", "ollama/mistral:7b"),
            "reviewer": getattr(s, "coder_model", "ollama/mistral:7b"),
            "memory": "ollama/mistral:7b",
            "advisor": "ollama/mistral:7b",
            "ops": getattr(s, "orchestrator_model", "ollama/mistral:7b"),
            "default": getattr(s, "fast_model", "ollama/mistral:7b"),
        }
        role_risk = {
            "director": "LOW", "research": "LOW", "planner": "LOW",
            "builder": "MEDIUM", "reviewer": "LOW", "memory": "LOW",
            "advisor": "LOW", "ops": "MEDIUM", "default": "LOW",
        }
        role_latency = {
            "director": "2-10s", "research": "5-30s", "planner": "3-15s",
            "builder": "10-60s", "reviewer": "5-20s", "memory": "1-3s",
            "advisor": "1-5s", "ops": "3-15s", "default": "2-10s",
        }

        for name, agent in crew.registry.items():
            role = getattr(agent, "role", "default")
            tools = []
            try:
                tools = [t.name if hasattr(t, 'name') else str(t)
                         for t in getattr(agent, "tools", []) or []]
            except Exception as _exc:
                log.warning("swallowed_exception", action="agent_builder_swallow", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

            agents.append({
                "name": name,
                "role": role,
                "description": getattr(agent, "description", getattr(agent, "backstory", ""))[:200],
                "capabilities": getattr(agent, "capabilities", []) if hasattr(agent, "capabilities") else [],
                "tools": tools[:10],
                "model": role_models.get(role, "ollama/mistral:7b"),
                "risk_tier": role_risk.get(role, "LOW"),
                "expected_latency": role_latency.get(role, "2-10s"),
                "timeout_s": getattr(agent, "timeout_s", 120),
            })
    except Exception as e:
        log.warning("agent_metadata_failed", err=str(e)[:80])

    return {"ok": True, "data": {"agents": agents, "total": len(agents)}}



@router.delete("/{agent_name}")
async def destroy_agent(
    agent_name:     str,
    x_jarvis_token: Optional[str] = Header(None),
):
    """Destroy a dynamic agent by name."""
    from core.agent_factory import get_agent_factory

    factory = get_agent_factory()
    ok      = await factory.destroy_agent(agent_name)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail=f"Dynamic agent '{agent_name}' not found. Only dynamic agents can be destroyed.",
        )
    return {"ok": True, "data": {"name": agent_name, "status": "destroyed"}}
