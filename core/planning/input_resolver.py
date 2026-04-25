"""
core/planning/input_resolver.py — Step input resolution.

Populates step inputs before execution using:
  1. Previous step outputs (context propagation)
  2. Plan goal (extract parameters from natural language goal)
  3. Default values (from skill schema)

This module closes the gap between plan creation and execution:
  Plan template creates steps with empty inputs
  → input_resolver fills them from goal + context
  → step_executor receives populated inputs

Design:
  - Deterministic: same goal + context → same inputs
  - No LLM: rule-based extraction from goal text
  - Fail-safe: returns partial inputs rather than blocking execution
  - Transparent: logs what was resolved and from where
"""
from __future__ import annotations

import re
import structlog

log = structlog.get_logger("planning.input_resolver")


# ── Skill input schemas (cached on first use) ────────────────

_SKILL_SCHEMAS: dict[str, list[dict]] | None = None


def _get_skill_schemas() -> dict[str, list[dict]]:
    """Load skill input schemas from domain registry."""
    global _SKILL_SCHEMAS
    if _SKILL_SCHEMAS is not None:
        return _SKILL_SCHEMAS

    _SKILL_SCHEMAS = {}
    try:
        from core.skills.domain_loader import DomainSkillRegistry
        reg = DomainSkillRegistry()
        reg.load_all()
        for skill_id, skill in reg._skills.items():
            _SKILL_SCHEMAS[skill_id] = [
                {
                    "name": inp.name,
                    "required": inp.required,
                    "description": inp.description,
                    "type": inp.type,
                }
                for inp in skill.inputs
            ]
    except Exception as e:
        log.debug("skill_schema_load_failed", err=str(e)[:80])

    return _SKILL_SCHEMAS


# ── Goal parameter extraction ─────────────────────────────────

# Common patterns that indicate a sector/domain/product
_SECTOR_PATTERNS = [
    r"(?:in|for|about|sector:?)\s+['\"]?([A-Za-z][A-Za-z0-9\s&/-]{2,40})['\"]?",
    r"(?:market|industry|niche|space|domain):?\s+['\"]?([A-Za-z][A-Za-z0-9\s&/-]{2,40})['\"]?",
]

_PRODUCT_PATTERNS = [
    r"(?:product|app|tool|platform|service|saas|build|create|launch):?\s+['\"]?([A-Za-z][A-Za-z0-9\s&/-]{2,40})['\"]?",
]


def _extract_from_goal(goal: str) -> dict[str, str]:
    """
    Extract structured parameters from a natural language goal.

    Returns dict of parameter_name → value.
    Conservative: only extracts high-confidence matches.
    """
    if not goal:
        return {}

    extracted: dict[str, str] = {}
    goal.lower().strip()

    # Extract sector/domain
    for pattern in _SECTOR_PATTERNS:
        match = re.search(pattern, goal, re.IGNORECASE)
        if match:
            val = match.group(1).strip().rstrip(".,;!?")
            if len(val) > 2:
                extracted["sector"] = val
                extracted["target_market"] = val
                extracted["business_context"] = val
                break

    # Extract product/service
    for pattern in _PRODUCT_PATTERNS:
        match = re.search(pattern, goal, re.IGNORECASE)
        if match:
            val = match.group(1).strip().rstrip(".,;!?")
            if len(val) > 2:
                extracted["product"] = val
                extracted["product_idea"] = val
                break

    # If no patterns matched, use the whole goal as context
    if not extracted and len(goal) > 5:
        # Use the goal itself as the primary input
        # This is a safe fallback — skills accept free-text for their required field
        extracted["sector"] = goal[:80]
        extracted["target_market"] = goal[:80]
        extracted["product"] = goal[:80]
        extracted["product_idea"] = goal[:80]
        extracted["business_context"] = goal[:80]
        extracted["opportunity"] = goal[:80]
        extracted["situation"] = goal[:80]
        extracted["feature"] = goal[:80]
        extracted["audience"] = goal[:80]

    return extracted


# ── Input mapping ─────────────────────────────────────────────

# Semantic equivalences: if a skill needs X and we have Y, use Y
_EQUIVALENCES: dict[str, list[str]] = {
    "sector": ["target_market", "business_context", "market", "industry", "niche"],
    "target_market": ["sector", "market", "audience"],
    "product": ["product_idea", "service", "app", "tool", "platform", "feature"],
    "product_idea": ["product", "service", "idea"],
    "business_context": ["sector", "target_market", "context", "situation"],
    "opportunity": ["product", "product_idea", "business_context"],
    "situation": ["business_context", "sector", "product", "context"],
    "feature": ["product", "product_idea", "service"],
    "audience": ["target_market", "sector", "market"],
}


def _find_equivalent(needed: str, available: dict) -> str | None:
    """Find a semantically equivalent value from available data."""
    if needed in available:
        return available[needed]
    for equiv in _EQUIVALENCES.get(needed, []):
        if equiv in available:
            return available[equiv]
    return None


# ── Main resolution function ──────────────────────────────────

def resolve_step_inputs(
    step_target_id: str,
    step_inputs: dict,
    goal: str,
    context_outputs: dict,
) -> dict:
    """
    Resolve all inputs for a step, populating missing required fields.

    Priority order:
      1. Explicit step.inputs (highest — user/template specified)
      2. Previous step outputs (context propagation)
      3. Goal extraction (parsed from plan goal text)
      4. Defaults from skill schema

    Args:
        step_target_id: Skill/tool/action ID
        step_inputs: Inputs already defined on the step
        goal: Plan goal text
        context_outputs: Merged outputs from previous steps

    Returns:
        dict of fully resolved inputs (superset of step_inputs)
    """
    resolved = dict(context_outputs)  # Start with context
    resolved.update(step_inputs)      # Step inputs override context

    # Get skill schema for this step
    schemas = _get_skill_schemas()
    schema = schemas.get(step_target_id, [])

    if not schema:
        # No schema available — pass through as-is
        return resolved

    # Identify missing required inputs
    required = [s["name"] for s in schema if s.get("required", True)]
    missing = [r for r in required if r not in resolved]

    if not missing:
        log.debug("inputs_complete", step=step_target_id)
        return resolved

    # Extract from goal
    goal_params = _extract_from_goal(goal)

    # Fill missing from goal + equivalences
    for needed in missing:
        # Direct from goal
        if needed in goal_params:
            resolved[needed] = goal_params[needed]
            log.debug("input_from_goal", step=step_target_id,
                      input=needed, source="goal_extraction")
            continue

        # Semantic equivalence from resolved
        equiv = _find_equivalent(needed, resolved)
        if equiv:
            resolved[needed] = equiv
            log.debug("input_from_equiv", step=step_target_id,
                      input=needed, source="equivalence")
            continue

        # Semantic equivalence from goal
        equiv = _find_equivalent(needed, goal_params)
        if equiv:
            resolved[needed] = equiv
            log.debug("input_from_goal_equiv", step=step_target_id,
                      input=needed, source="goal_equivalence")
            continue

        # Last resort: use goal text as the value
        if goal and len(goal) > 3:
            resolved[needed] = goal[:100]
            log.debug("input_from_goal_fallback", step=step_target_id,
                      input=needed, source="goal_text_fallback")

    # Add goal as context for all steps
    resolved.setdefault("goal", goal)

    return resolved
