"""Semantic consolidator — nightly pattern extraction from episodic memory."""
from __future__ import annotations

import json
import time
from pathlib import Path

_PATTERNS_PATH = Path("workspace/memory/patterns.json")
_MAX_EPISODES = 500


def consolidate(max_episodes: int = _MAX_EPISODES) -> dict:
    """
    Read recent episodes, compute per-domain agent win-rates and timing stats,
    write workspace/memory/patterns.json, return summary.
    """
    from core.memory.episodic_store import recent_episodes

    episodes = recent_episodes(limit=max_episodes)

    # domain → agent → {wins, total, total_ms}
    domain_agent: dict[str, dict[str, dict]] = {}
    for ep in episodes:
        domain = ep["domain"] or "general"
        d = domain_agent.setdefault(domain, {})
        for ag in (ep["agents"] or ["unknown"]):
            e = d.setdefault(ag, {"wins": 0, "total": 0, "total_ms": 0})
            e["total"] += 1
            e["total_ms"] += ep.get("duration_ms", 0)
            if ep["success"]:
                e["wins"] += 1

    patterns: dict = {}
    for domain, agents in domain_agent.items():
        ranked = sorted(
            [
                {
                    "agent": ag,
                    "win_rate": s["wins"] / s["total"] if s["total"] else 0.0,
                    "avg_ms": s["total_ms"] // s["total"] if s["total"] else 0,
                    "sample": s["total"],
                }
                for ag, s in agents.items()
            ],
            key=lambda x: x["win_rate"],
            reverse=True,
        )
        patterns[domain] = {
            "best_agents": ranked[:5],
            "episode_count": sum(s["total"] for s in agents.values()),
        }

    result = {
        "ts": time.time(),
        "episodes_processed": len(episodes),
        "domains": patterns,
    }
    _PATTERNS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PATTERNS_PATH.write_text(json.dumps(result, indent=2), "utf-8")
    return result


def load_patterns() -> dict:
    try:
        return json.loads(_PATTERNS_PATH.read_text("utf-8"))
    except Exception:
        return {}
