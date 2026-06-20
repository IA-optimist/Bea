"""
BeaTeam Dispatcher — orchestrates the architect→coder→reviewer→qa chain.
Activated when mode in ("improve", "lab", "dev").
Integrates Global Workspace Theory for inter-agent consciousness.
"""
from __future__ import annotations
import structlog
from pathlib import Path
from core.global_workspace import get_workspace

log = structlog.get_logger(__name__)

AGENTS_DIR = Path(__file__).parent.parent.parent / "agents" / "bea_team"

def load_agent_prompt(agent_name: str) -> str:
    """Load system prompt from agent markdown file."""
    path = AGENTS_DIR / f"{agent_name}.md"
    if not path.exists():
        return f"You are {agent_name} agent for BeaMax."
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
            # FIXED: LangChain BaseChatModel uses .ainvoke(), not .achat()
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": context}
            ]
            response = await llm_client.ainvoke(messages)
            result = response.content if hasattr(response, "content") else str(response)
            chain_results.append({"agent": agent_name, "output": result[:500], "success": True})

            # Global Workspace Theory: Publish agent output to shared consciousness
            await get_workspace().publish(
                agent=agent_name,
                content=result,
                confidence=0.8,
                metadata={'mission_id': mission_id, 'goal': goal[:100]}
            )

            # Pass result to next agent as context
            context = f"Previous {agent_name} output:\n{result}\n\nOriginal goal: {goal}"
            log.info("bea_team.agent_complete", agent=agent_name, mission_id=mission_id)
        except Exception as e:
            log.warning("bea_team.agent_failed", agent=agent_name, err=str(e)[:80])
            chain_results.append({"agent": agent_name, "output": "", "success": False, "error": str(e)[:80]})
            continue

    final = chain_results[-1]["output"] if chain_results and chain_results[-1]["success"] else ""
    return {
        "status": "done" if final else "partial",
        "result": final,
        "chain": chain_results,
        "agents_run": [r["agent"] for r in chain_results]
    }
