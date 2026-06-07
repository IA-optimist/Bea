"""
core/autonomy/builtin_skills.py — Default skills shipped with BeaMax.

These wrap existing prod functions in the SkillRegistry so the daemon /
operator can invoke them by name. Each skill is small and well-typed ;
heavier work delegates to the existing modules (canonical mission
store, profiling, llm cache, etc.).

Skills shipped here :

- `health.snapshot`    : current process health summary
- `cache.stats`        : LLM response cache hit/miss/skips
- `budget.snapshot`    : autonomy budget snapshot
- `events.recent`      : recent autonomy events from the bus
- `noop`               : sanity check / wiring smoke test

Importing this module triggers the @register_skill decorators —
applications can opt in via `from core.autonomy import builtin_skills`
or skip if they want a clean slate.
"""
from __future__ import annotations

from typing import Any, Dict

from core.autonomy.budget import get_budget_tracker
from core.autonomy.event_bus import get_event_bus
from core.autonomy.skills import SkillContext, SkillResult, register_skill


@register_skill(
    name="noop",
    description="Sanity skill : returns success with the params unchanged.",
    tags=["test", "sanity"],
)
def noop_skill(ctx: SkillContext) -> SkillResult:
    return SkillResult(success=True, output=dict(ctx.params))


@register_skill(
    name="health.snapshot",
    description="Snapshot of process health (event bus stats, budget, time).",
    tags=["health", "observability"],
)
def health_snapshot(_ctx: SkillContext) -> SkillResult:
    bus = get_event_bus()
    bt = get_budget_tracker()
    out: Dict[str, Any] = {
        "event_bus": bus.stats(),
        "budget": bt.snapshot(),
    }
    return SkillResult(success=True, output=out)


@register_skill(
    name="cache.stats",
    description="LLM response cache hit/miss/skip counters.",
    tags=["cache", "llm", "observability"],
)
def cache_stats_skill(_ctx: SkillContext) -> SkillResult:
    try:
        from core.llm_response_cache import get_cache_stats
        return SkillResult(success=True, output=get_cache_stats())
    except Exception as exc:
        return SkillResult(success=False, error=f"cache_unavailable: {exc}")


@register_skill(
    name="budget.snapshot",
    description="Autonomy budget snapshot (daily + per mission).",
    tags=["budget", "observability"],
)
def budget_snapshot_skill(_ctx: SkillContext) -> SkillResult:
    return SkillResult(success=True, output=get_budget_tracker().snapshot())


@register_skill(
    name="events.recent",
    description="Recent events on the autonomy bus matching an optional pattern.",
    tags=["debug", "observability"],
    param_schema={
        "pattern": {"type": "string", "default": "*", "description": "Glob pattern"},
        "limit":   {"type": "integer", "default": 50, "description": "Max events"},
    },
)
def events_recent_skill(ctx: SkillContext) -> SkillResult:
    pattern = ctx.params.get("pattern", "*")
    limit = int(ctx.params.get("limit", 50))
    events = get_event_bus().replay(pattern, limit=limit)
    return SkillResult(
        success=True,
        output=[
            {"topic": e.topic, "ts": e.ts, "id": e.id, "payload": e.payload}
            for e in events
        ],
    )
