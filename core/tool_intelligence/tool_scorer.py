"""
Computes effectiveness score 0-1 for each tool based on observation history.
Reuses capability_scorer structure where possible.
"""
import logging
import time
from typing import Dict

logger = logging.getLogger(__name__)

_SCORE_CACHE: Dict[str, dict] = {}
_CACHE_TTL = 300  # 5 min

def compute_tool_score(tool_name: str) -> dict:
    """
    Returns {tool_score, confidence, risk_indicator, use_frequency, recent_trend}.
    Falls back to neutral score if insufficient data.
    """
    try:
        # Check cache
        cached = _SCORE_CACHE.get(tool_name)
        if cached and (time.time() - cached.get("_ts", 0)) < _CACHE_TTL:
            return {k: v for k, v in cached.items() if not k.startswith("_")}

        from core.tool_intelligence.tool_observer import get_observations
        obs = get_observations(tool_name=tool_name, limit=200)

        if not obs:
            return _neutral_score(tool_name, reason="no_data")

        total = len(obs)
        successes = sum(1 for o in obs if o.get("success"))
        rollbacks = sum(1 for o in obs if o.get("rollback_triggered"))
        avg_time = sum(o.get("execution_time", 0) for o in obs) / max(total, 1)
        avg_retries = sum(o.get("retry_count", 0) for o in obs) / max(total, 1)

        # Success rate (weight 40%)
        success_rate = successes / max(total, 1)
        # Stability: penalize rollbacks (weight 20%)
        stability = 1.0 - (rollbacks / max(total, 1))
        # Speed: normalize to 0-1 (>30s = bad, <1s = good)
        speed_score = max(0.0, 1.0 - (avg_time / 30.0))
        # Retry penalty (weight 20%)
        retry_score = max(0.0, 1.0 - (avg_retries / 3.0))

        tool_score = round(
            success_rate * 0.4 + stability * 0.2 + speed_score * 0.2 + retry_score * 0.2, 3
        )

        # Recent trend: last 20 vs previous 20
        recent = obs[-20:]
        prev = obs[-40:-20]
        recent_sr = sum(1 for o in recent if o.get("success")) / max(len(recent), 1)
        prev_sr = sum(1 for o in prev if o.get("success")) / max(len(prev), 1) if prev else recent_sr
        trend = "improving" if recent_sr > prev_sr + 0.1 else ("declining" if recent_sr < prev_sr - 0.1 else "stable")

        result = {
            "tool_name": tool_name,
            "tool_score": tool_score,
            "confidence": min(1.0, total / 50),  # confidence grows with data
            "risk_indicator": round(1.0 - stability, 3),
            "use_frequency": total,
            "recent_trend": trend,
            "success_rate": round(success_rate, 3),
        }
        _SCORE_CACHE[tool_name] = {**result, "_ts": time.time()}
        return result

    except Exception as e:
        logger.warning("[ToolScorer] compute failed for %s: %s", tool_name, e)
        return _neutral_score(tool_name, reason=str(e))

def _neutral_score(tool_name: str, reason: str = "") -> dict:
    return {
        "tool_name": tool_name,
        "tool_score": 0.5,
        "confidence": 0.0,
        "risk_indicator": 0.0,
        "use_frequency": 0,
        "recent_trend": "unknown",
        "success_rate": 0.5,
        "reason": reason,
    }

def get_tool_hints(available_tools: list) -> dict:
    """
    Returns hints dict for planner injection:
    {preferred_tools, tools_to_avoid, confidence_weights}
    """
    try:
        scores = {}
        for t in (available_tools or []):
            name = t if isinstance(t, str) else getattr(t, "name", str(t))
            scores[name] = compute_tool_score(name)

        preferred = [n for n, s in scores.items() if s.get("tool_score", 0.5) >= 0.7]
        avoid = [n for n, s in scores.items()
                 if s.get("tool_score", 0.5) < 0.3 and s.get("confidence", 0) > 0.3]
        weights = {n: s.get("tool_score", 0.5) for n, s in scores.items()}

        return {
            "preferred_tools": preferred,
            "tools_to_avoid": avoid,
            "confidence_weights": weights,
        }
    except Exception as e:
        logger.warning("[ToolScorer] get_tool_hints failed: %s", e)
        return {"preferred_tools": [], "tools_to_avoid": [], "confidence_weights": {}}
