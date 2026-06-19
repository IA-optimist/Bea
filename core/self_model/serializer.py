"""
core/self_model/serializer.py — Serialization and export for the Self-Model.

Provides multiple output formats:
  - Full dict (for API responses)
  - Compact summary (for LLM context injection)
  - Health card (for dashboards)
  - LLM-consumable text (for MetaOrchestrator reasoning)
"""
from __future__ import annotations
from typing import Any, cast

from core.self_model.model import SelfModel
from core.self_model import queries


def with_summary(model: SelfModel) -> SelfModel:
    """Attach computed summary to the model before serialization."""
    model.summary = {
        "readiness_score": queries.readiness_score(model),
        "capabilities": queries.capability_summary(model),
        "components": queries.component_summary(model),
        "health": queries.health_summary(model),
        "autonomy_mode": model.autonomy.mode.value,
    }
    return model


def to_full_dict(model: SelfModel) -> dict[str, Any]:
    """Full serialization — for API responses."""
    model = with_summary(model)
    return cast(dict[str, Any], model.to_dict())


def to_compact(model: SelfModel) -> dict[str, Any]:
    """Compact summary — for lightweight consumers."""
    return {
        "readiness": queries.readiness_score(model),
        "ready_capabilities": len(queries.what_can_i_do(model)),
        "degraded": len(queries.what_is_degraded(model)),
        "needs_approval": len(queries.what_requires_approval(model)),
        "needs_config": len(queries.what_requires_configuration(model)),
        "missing": len(queries.what_is_missing(model)),
        "autonomy": model.autonomy.mode.value,
        "generation_ms": round(model.generation_duration_ms, 1),
    }


def to_health_card(model: SelfModel) -> dict[str, Any]:
    """Health card — for dashboard display."""
    return {
        "readiness_score": queries.readiness_score(model),
        "health_signals": {
            h.name: h.status.value for h in model.health.values()
        },
        "degraded_items": queries.what_is_degraded(model),
        "missing_items": queries.what_is_missing(model),
    }


def to_llm_context(model: SelfModel) -> str:
    """
    LLM-consumable text — for injection into MetaOrchestrator reasoning.

    This is the key output: a structured text block that an LLM can
    use to reason about what the system can and cannot do.
    """
    lines = ["## BeaMax Self-Model (Current State)", ""]

    # Readiness
    score = queries.readiness_score(model)
    lines.append(f"**Readiness:** {score:.0%}")
    lines.append(f"**Autonomy Mode:** {model.autonomy.mode.value}")
    lines.append("")

    # Ready capabilities
    ready = queries.what_can_i_do(model)
    if ready:
        lines.append(f"### Ready Capabilities ({len(ready)})")
        for c in ready[:20]:  # Cap at 20 for context window
            conf = f" (confidence: {c['confidence']:.0%})" if c.get("confidence") else ""
            lines.append(f"- {c['id']}{conf} [{c['source']}]")
        if len(ready) > 20:
            lines.append(f"- ... and {len(ready) - 20} more")
        lines.append("")

    # Approval required
    approval = queries.what_requires_approval(model)
    if approval:
        lines.append(f"### Requires Approval ({len(approval)})")
        for approval_item in approval[:10]:
            risk = f" (risk: {approval_item.get('risk', '?')})" if approval_item.get("risk") else ""
            lines.append(f"- {approval_item['id']}{risk}")
        lines.append("")

    # Degraded/unavailable
    degraded = queries.what_is_degraded(model)
    if degraded:
        lines.append(f"### Degraded ({len(degraded)})")
        for d in degraded[:10]:
            lines.append(f"- {d['id']} [{d['type']}]")
        lines.append("")

    # Missing/unconfigured
    missing = queries.what_is_missing(model)
    if missing:
        lines.append(f"### Missing/Unconfigured ({len(missing)})")
        for m in missing[:10]:
            lines.append(f"- {m['id']} ({m.get('status', '?')})")
        lines.append("")

    # Modification boundaries
    unsafe = queries.what_is_unsafe_to_modify(model)
    if unsafe:
        lines.append("### Modification Restrictions")
        for b in unsafe:
            zone = b.get("zone", "?")
            desc = b.get("description", "")
            lines.append(f"- **{zone}**: {desc}")
            for ex in b.get("examples", [])[:3]:
                lines.append(f"  - {ex}")
        lines.append("")

    # Health
    lines.append("### System Health")
    for h in model.health.values():
        emoji = {"healthy": "✅", "degraded": "⚠️", "unknown": "❓"}.get(h.status.value, "?")
        lines.append(f"- {emoji} {h.name}: {h.status.value}")
    lines.append("")

    # Autonomy flags
    autonomy: Any = model.autonomy
    lines.append("### Autonomy Flags")
    lines.append(f"- Tools require approval: {autonomy.requires_approval_for_tools}")
    lines.append(f"- Code patches require approval: {autonomy.requires_approval_for_code_patch}")
    lines.append(f"- External calls require approval: {autonomy.requires_approval_for_external_calls}")
    lines.append(f"- Max risk auto-approve: {autonomy.max_risk_auto_approve}")
    lines.append(f"- Max files per patch: {autonomy.max_files_per_patch}")

    return "\n".join(lines)
