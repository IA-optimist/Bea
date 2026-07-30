"""Critic viability coupling test.
Mesure de régulation fonctionnelle, aucun ressenti revendiqué.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.self_critic import CRITIC_OVERALL_PASS_THRESHOLD, _MAX_RERUNS

_VIABILITY_PRUDENCE_THRESHOLD = 0.4
_MARGINAL_OVERALL_BAND = 1.5
RIGOR_FLOOR_THRESHOLD = 7.0


@dataclass
class _Scores:
    overall: float


@dataclass
class _CriticReport:
    scores: _Scores
    rerun_count: int


def force_rerun_reason(via: float, cr: _CriticReport) -> str | None:
    marginal = cr.scores.overall < (CRITIC_OVERALL_PASS_THRESHOLD + _MARGINAL_OVERALL_BAND)
    within_cap = cr.rerun_count < _MAX_RERUNS
    if via < _VIABILITY_PRUDENCE_THRESHOLD and marginal and within_cap:
        return "viability"
    if cr.scores.overall < RIGOR_FLOOR_THRESHOLD and within_cap:
        return "floor"
    return None


def should_force_rerun(via: float, cr: _CriticReport) -> bool:
    return force_rerun_reason(via, cr) is not None


def _case(
    name: str,
    via: float,
    overall: float,
    rerun_count: int,
    expected: bool,
    expected_reason: str | None = None,
) -> bool:
    cr = _CriticReport(scores=_Scores(overall=overall), rerun_count=rerun_count)
    got = should_force_rerun(via, cr)
    reason = force_rerun_reason(via, cr)
    ok = got == expected and reason == expected_reason
    sys.stdout.write(
        f"{name}: {'PASS' if ok else 'FAIL'}  via={via:.2f} overall={overall:.2f} "
        f"rerun_count={rerun_count} -> {got} reason={reason}\n"
    )
    return ok


def main() -> None:
    sys.stdout.write("# Critic viability coupling\n")
    sys.stdout.write("Mesure de regu1ation fonctionnelle, aucun ressenti.\n")

    results = [
        _case("high_viability_low_score_floor_triggers", 0.9, 6.8, 0, True, "floor"),
        _case("high_viability_above_floor_no_trigger", 0.9, 7.2, 0, False),
        _case("low_viability_not_marginal", 0.2, 8.0, 0, False),
        _case("low_viability_force", 0.2, 6.5, 0, True, "viability"),
        _case("low_viability_below_floor_via_viability_path", 0.2, 6.8, 0, True, "viability"),
        _case("low_viability_cap_reached", 0.2, 6.5, _MAX_RERUNS, False),
        _case("floor_respects_cap", 0.9, 6.8, _MAX_RERUNS, False),
    ]

    monotone_ok = (
        not should_force_rerun(0.9, _CriticReport(_Scores(7.2), 0))
        and should_force_rerun(0.2, _CriticReport(_Scores(6.5), 0))
    )
    sys.stdout.write(f"monotone_direction: {'PASS' if monotone_ok else 'FAIL'}\n")

    global_ok = all(results) and monotone_ok
    sys.stdout.write(f"overall: {'PASS' if global_ok else 'FAIL'}\n")
    raise SystemExit(0 if global_ok else 1)


if __name__ == "__main__":
    main()
