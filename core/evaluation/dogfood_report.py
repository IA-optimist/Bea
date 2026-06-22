"""
core/evaluation/dogfood_report.py

Pure-logic module for dogfood routing-advice evidence pack.

Rules (invariants):
- runtime_enforced is ALWAYS False
- mode is ALWAYS "fixture" for fixture-based reports
- skipped providers are NEVER counted as failures
- No API keys are produced or logged
"""
from __future__ import annotations

_REQUIRED_MISSION_FIELDS = {
    "mission_id", "role", "goal",
    "mode", "advised_provider", "provider_used", "model_used",
    "provider_status", "matched_advice", "success", "passed", "score",
    "duration_s", "fallback_used", "error_category", "skipped",
    "runtime_enforced",
}


def validate_mission(mission: dict) -> list[str]:
    """Return a list of validation errors (empty if OK)."""
    errors: list[str] = []
    for field in _REQUIRED_MISSION_FIELDS:
        if field not in mission:
            errors.append(f"missing field: {field}")
    if mission.get("runtime_enforced") is True:
        errors.append("runtime_enforced must be False")
    return errors


def check_matched_advice(mission: dict, advice: dict) -> bool:
    """Return True if provider_used matches the advised provider for this role."""
    role = mission.get("role", "")
    role_advice = advice.get(role) or advice.get("recommendations", {}).get(role, {})
    advised = role_advice.get("preferred_provider")
    if not advised:
        return False
    return mission.get("provider_used") == advised


def _bucket_breakdown(missions: list[dict], key: str) -> dict[str, dict]:
    breakdown: dict[str, dict] = {}
    for mission in missions:
        bucket = mission.get(key) or "unknown"
        entry = breakdown.setdefault(bucket, {
            "total": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "matched_advice": 0,
        })
        entry["total"] += 1
        if mission.get("skipped"):
            entry["skipped"] += 1
        elif mission.get("passed"):
            entry["passed"] += 1
        else:
            entry["failed"] += 1
        if mission.get("matched_advice"):
            entry["matched_advice"] += 1
    return breakdown


def compute_dogfood_summary(missions: list[dict]) -> dict:
    """Compute the summary block from a list of mission result dicts."""
    total = len(missions)
    skipped = sum(1 for m in missions if m.get("skipped"))
    non_skipped = [m for m in missions if not m.get("skipped")]
    passed = sum(1 for m in non_skipped if m.get("passed"))
    failed = total - skipped - passed
    matched = sum(1 for m in missions if m.get("matched_advice"))

    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "matched_advice": matched,
        "matched_advice_count": matched,
        "advice_match_rate": round(matched / total, 4) if total else 0.0,
        "provider_breakdown": _bucket_breakdown(missions, "provider_used"),
        "role_breakdown": _bucket_breakdown(missions, "role"),
        "runtime_enforced": False,
    }
