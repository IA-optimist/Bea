"""
Tree-of-Thought wrapper for mission planning.
Integrates ToT with BeaMax LLM client.
"""
import os
import structlog
from core.cognition.tree_of_thought import TreeOfThought

log = structlog.get_logger(__name__)


async def plan_with_tot(
    goal: str,
    llm_client,
    max_depth: int = 2,
    branching_factor: int = 3,
    mode: str = "beam"
) -> dict:
    """
    Use Tree-of-Thought to plan mission approach.
    
    Returns best plan with confidence score.
    """

    # Wrapper for LLM calls (convert to async)
    async def llm_call(prompt: str) -> str:
        try:
            from langchain_core.messages import HumanMessage
            if hasattr(llm_client, 'ainvoke'):
                response = await llm_client.ainvoke([HumanMessage(content=prompt)])
                return response.content if hasattr(response, 'content') else str(response)
            elif hasattr(llm_client, 'chat'):
                response = llm_client.chat.completions.create(
                    model=os.getenv("OPENROUTER_MODEL", "google/gemini-2.0-flash-001"),
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=500,
                    temperature=0.7
                )
                return response.choices[0].message.content
            else:
                return str(await llm_client(prompt))
        except Exception as e:
            log.error("tot_llm_call_failed", err=str(e))
            return "Error generating thought"
    # Create ToT engine
    tot = TreeOfThought(
        llm_function=llm_call,
        max_depth=max_depth,
        branching_factor=branching_factor,
        pruning_threshold=0.4,
        mode=mode
    )

    # Solve
    result = await tot.solve(goal)

    log.info(
        "tot_planning_complete",
        goal=goal[:100],
        confidence=result["confidence"],
        nodes_explored=result["nodes_explored"],
        depth=result["max_depth_reached"]
    )

    return result


def should_use_tot(goal: str) -> bool:
    """Only activate ToT for genuinely complex missions, not simple chat."""
    if len(goal.strip()) < 100:
        return False
    if "[ROUTING:" in goal and "complexity=simple" in goal:
        return False
    heavy_keywords = ["architecture", "strategy", "design a", "build a system", "roadmap"]
    return any(k in goal.lower() for k in heavy_keywords)
