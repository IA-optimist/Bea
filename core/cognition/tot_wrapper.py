"""
Tree-of-Thought wrapper for mission planning.
Integrates ToT with JarvisMax LLM client.
"""
import os
from typing import Optional
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
            # Use OpenRouter client
            response = llm_client.chat.completions.create(
                model=os.getenv("OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet"),
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
                temperature=0.7
            )
            return response.choices[0].message.content
        except Exception as e:
            log.error("tot_llm_call_failed", error=str(e))
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
    """Decide if ToT is beneficial for this mission."""
    # Use ToT for complex, open-ended missions
    complexity_keywords = [
        "design", "architecture", "strategy", "optimize", "compare",
        "evaluate", "analyze", "research", "plan", "create"
    ]
    
    goal_lower = goal.lower()
    return any(keyword in goal_lower for keyword in complexity_keywords)
