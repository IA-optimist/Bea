"""
core/evaluation/routing_advisor.py

Pure-logic advisory module — reads benchmark results and produces non-prescriptive
routing recommendations.

Rules (invariants):
- runtime_enforced is ALWAYS False
- confidence is ALWAYS "low" or "experimental"
- skipped providers are NEVER counted as failures
- No API keys are read or produced
"""
from __future__ import annotations

from datetime import datetime, timezone


_CONFIDENCE = "low"
_CAVEAT = (
    "Informational only. Results from limited runs. "
    "Not applied at runtime. Requires human review before any routing change."
)


def compute_advice(results: list[dict]) -> dict[str, dict]:
    """
    Compute per-role advisory recommendations from benchmark results.

    Args:
        results: List of BenchmarkResult dicts (as produced by run_benchmark).

    Returns:
        Dict keyed by role name. Each value contains:
            preferred_provider, preferred_model, score,
            passed_count, failed_count, skipped_count,
            confidence, reason, runtime_enforced.

    Invariants:
        - runtime_enforced is always False
        - confidence is always "low"
        - skipped entries increment skipped_count only, never failed_count
        - preferred_provider is None when all providers were skipped
    """
    by_role: dict[str, list[dict]] = {}
    for r in results:
        role = r.get("role", "")
        by_role.setdefault(role, []).append(r)

    advice: dict[str, dict] = {}
    for role, entries in by_role.items():
        advice[role] = _advise_role(role, entries)
    return advice


def _advise_role(role: str, entries: list[dict]) -> dict:
    skipped_count = sum(1 for e in entries if e.get("skipped"))
    non_skipped = [e for e in entries if not e.get("skipped")]
    failed_count = sum(1 for e in non_skipped if not e.get("passed"))
    passed_count = sum(1 for e in non_skipped if e.get("passed"))

    best: dict | None = None
    reason: str

    if not non_skipped:
        reason = "all_providers_skipped"
        return {
            "preferred_provider": None,
            "preferred_model": None,
            "score": 0.0,
            "passed_count": 0,
            "failed_count": 0,
            "skipped_count": skipped_count,
            "confidence": _CONFIDENCE,
            "reason": reason,
            "runtime_enforced": False,
        }

    passed_entries = [e for e in non_skipped if e.get("passed")]

    if passed_entries:
        # Among passed entries: highest score, tie-broken by lowest duration_s
        best = min(
            passed_entries,
            key=lambda e: (-e.get("score", 0.0), e.get("duration_s", float("inf"))),
        )
        others_failed = [e for e in non_skipped if not e.get("passed")]
        if others_failed and len(passed_entries) == 1:
            other = others_failed[0]
            ec = other.get("error_category") or "quality_below_threshold"
            reason = (
                f"{best['provider_used']} passed (score={best['score']:.2f}); "
                f"{other['provider_used']} failed ({ec}, score={other.get('score', 0.0):.2f})."
            )
        elif len(passed_entries) > 1:
            scores_equal = len({e.get("score") for e in passed_entries}) == 1
            if scores_equal:
                reason = (
                    f"Both providers passed (score={best['score']:.2f}). "
                    f"{best['provider_used']} chosen (faster duration_s)."
                )
            else:
                reason = (
                    f"{best['provider_used']} has highest score ({best['score']:.2f}) "
                    f"among passing providers."
                )
        else:
            reason = f"{best['provider_used']} passed (score={best['score']:.2f})."
    else:
        # No passed entries — pick highest score among non-skipped
        best = max(non_skipped, key=lambda e: e.get("score", 0.0))
        reason = (
            f"No provider passed the quality threshold. "
            f"{best['provider_used']} had highest score ({best.get('score', 0.0):.2f}) "
            f"but did not pass."
        )

    return {
        "preferred_provider": best["provider_used"],
        "preferred_model": best.get("model_used", ""),
        "score": best.get("score", 0.0),
        "passed_count": passed_count,
        "failed_count": failed_count,
        "skipped_count": skipped_count,
        "confidence": _CONFIDENCE,
        "reason": reason,
        "runtime_enforced": False,
    }


def build_advisory_report(
    results: list[dict],
    source_file: str = "",
) -> dict:
    """
    Build the full advisory JSON report from benchmark results.

    Args:
        results: List of BenchmarkResult dicts.
        source_file: Path to the source benchmark file (informational only).

    Returns:
        Advisory report dict. runtime_enforced is always False for every recommendation.
    """
    return {
        "mode": "advisory",
        "source_file": source_file,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "caveat": _CAVEAT,
        "recommendations": compute_advice(results),
    }
