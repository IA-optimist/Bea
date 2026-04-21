"""
Injects tool intelligence hints into planner context.
Fail-open: if disabled or error, returns empty hints dict.
"""
import logging
import os

logger = logging.getLogger(__name__)
_ENABLED = os.getenv("USE_TOOL_INTELLIGENCE", "false").lower() == "true"

def get_hints_for_planner(available_tools: list = None, objective: str = "") -> dict:
    """
    Returns hints dict to inject into planner context.
    Only active when USE_TOOL_INTELLIGENCE=true.
    """
    if not _ENABLED:
        return {}
    try:
        from core.tool_intelligence.tool_scorer import get_tool_hints
        hints = get_tool_hints(available_tools or [])
        logger.debug("[ToolIntelligence] hints for planner: preferred=%s avoid=%s",
                     hints.get("preferred_tools"), hints.get("tools_to_avoid"))
        return hints
    except Exception as e:
        logger.warning("[ToolIntelligence] get_hints_for_planner failed (fail-open): %s", e)
        return {}
