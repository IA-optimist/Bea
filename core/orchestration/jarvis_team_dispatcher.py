"""
JarvisTeam Dispatcher — orchestrates the architect→coder→reviewer→qa chain.
Activated when mode in ("improve", "lab", "dev").
"""
from __future__ import annotations
import asyncio
import structlog
from pathlib import Path

log = structlog.get_logger(__name__)

AGENTS_DIR = Path(__file__).parent.parent.parent / "agents" / "jarvis_team"

def load_agent_prompt(agent_name: str) -> str:
    """Load system prompt from agent markdown file."""
    path = AGENTS_DIR / f"{agent_name}.md"
    if not path.exists():
        return f"You are {agent_name} agent for JarvisMax."
    content = path.read_text()
    # Strip frontmatter
    if content.startswith("---"):
        parts = content.split("---", 2)
        return parts[2].strip() if len(parts) >= 3 else content
    return content

async def dispatch_improve(goal: str, llm_client, mission_id: str = "") -> dict:
    """
    Run the architect→coder→reviewer→qa chain.
    Returns aggregated result.
    """
    chain_results = []
    context = goal

    for agent_name in ["architect", "coder", "reviewer", "qa"]:
        system_prompt = load_agent_prompt(agent_name)
        try:
            # Call LLM with agent system prompt
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": context}
            ]
            response = await llm_client.achat(messages)
            result = response.content if hasattr(response, "content") else str(response)
            chain_results.append({"agent": agent_name, "output": result[:500], "success": True})
            # Pass result to next agent as context
            context = f"Previous {agent_name} output:\n{result}\n\nOriginal goal: {goal}"
            log.info("jarvis_team.agent_complete", agent=agent_name, mission_id=mission_id)
        except Exception as e:
            log.warning("jarvis_team.agent_failed", agent=agent_name, error=str(e)[:80])
            chain_results.append({"agent": agent_name, "output": "", "success": False, "error": str(e)[:80]})
            break

    final = chain_results[-1]["output"] if chain_results and chain_results[-1]["success"] else ""
    return {
        "status": "done" if final else "partial",
        "result": final,
        "chain": chain_results,
        "agents_run": [r["agent"] for r in chain_results]
    }
