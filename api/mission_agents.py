"""Agent list and manual trigger helpers for mission routes."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any


def serialize_agent_registry(registry: dict[str, Any]) -> list[dict[str, Any]]:
    """Serialize AgentCrew registry entries for the public API."""
    return [
        {
            "name": name,
            "role": getattr(agent, "role", "?"),
            "timeout": getattr(agent, "timeout_s", "?"),
            "status": "registered",
        }
        for name, agent in registry.items()
    ]


def list_registered_agents() -> dict[str, Any]:
    """Build the /api/v2/agents response payload."""
    try:
        from agents.crew import AgentCrew
        from config.settings import get_settings

        crew = AgentCrew(get_settings())
        agents = serialize_agent_registry(crew.registry)
        return {"ok": True, "data": {"agents": agents, "total": len(agents)}}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def schedule_agent_trigger(
    *,
    background_tasks: Any,
    agent_id: str,
    mission: str,
    get_orchestrator: Callable[[], Any],
    logger: Any,
) -> dict[str, Any]:
    """Schedule a manual agent trigger and return the API response payload."""

    async def _run() -> None:
        try:
            orchestrator = get_orchestrator()
            session = __import__("core.state", fromlist=["JarvisSession"]).JarvisSession(
                session_id=f"manual-{agent_id}",
                user_input=mission,
                mode="auto",
            )
            session.mission_summary = mission
            session.agents_plan = [{"agent": agent_id, "task": mission, "priority": 1}]
            await orchestrator.agents.run(agent_id, session)
        except Exception as exc:
            logger.error("agent_trigger_failed", agent=agent_id, err=str(exc)[:100])

    background_tasks.add_task(_run)
    return {"ok": True, "data": {"agent_id": agent_id, "status": "triggered"}}