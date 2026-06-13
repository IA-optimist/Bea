"""Procedural memory — agent×domain success scores, JSON-persisted."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_SCORES_PATH = Path("workspace/memory/agent_scores.json")


def _load() -> dict[str, dict[str, dict]]:
    try:
        return json.loads(_SCORES_PATH.read_text("utf-8"))
    except Exception:
        return {}


def _save(data: dict) -> None:
    _SCORES_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SCORES_PATH.write_text(json.dumps(data, indent=2), "utf-8")


def record_outcome(domain: str, agent: str, success: bool) -> None:
    """Increment wins/total for this agent in this domain."""
    data = _load()
    domain_scores = data.setdefault(domain, {})
    entry = domain_scores.setdefault(agent, {"wins": 0, "total": 0})
    entry["total"] += 1
    if success:
        entry["wins"] += 1
    _save(data)


def best_agents(domain: str, top_k: int = 3) -> list[dict[str, Any]]:
    """Return ranked agents for a domain, with win-rate and sample size."""
    data = _load()
    domain_scores = data.get(domain, {})
    if not domain_scores:
        # fall back to cross-domain aggregate
        agg: dict[str, dict] = {}
        for d_scores in data.values():
            for agent, s in d_scores.items():
                e = agg.setdefault(agent, {"wins": 0, "total": 0})
                e["wins"] += s["wins"]
                e["total"] += s["total"]
        domain_scores = agg

    ranked = sorted(
        [
            {"agent": ag, "win_rate": s["wins"] / s["total"] if s["total"] else 0.0,
             "wins": s["wins"], "total": s["total"]}
            for ag, s in domain_scores.items()
            if s["total"] >= 2
        ],
        key=lambda x: x["win_rate"],
        reverse=True,
    )
    return ranked[:top_k]


def all_scores() -> dict[str, dict[str, dict]]:
    return _load()
