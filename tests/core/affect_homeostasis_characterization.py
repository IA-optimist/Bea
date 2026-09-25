"""Caractérisation du couplage homéostasie -> affect.

Mesure un couplage de régulation temporelle fonctionnelle. Aucun vocabulaire
de ressenti ici.
"""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.affect_state import AffectConfig, AffectState
from core.homeostasis import Homeostasis


def probe_estimator(signal: str | None):
    if signal == "positive_signal":
        return (1.0, 1.0, 1.0)
    if signal == "negative_signal":
        return (-1.0, -1.0, -1.0)
    return (0.0, 0.0, 0.0)


SEQ = [
    None,
    "positive_signal",
    None,
    None,
    "negative_signal",
    None,
    None,
]

NONTRIVIAL = (0.2, -0.1, 0.15)


def run_traj_cfg(baseline):
    aff = AffectState(
        estimator=probe_estimator,
        config=AffectConfig(momentum=0.8, rate=0.5, baseline=baseline, trajectory_len=0),
        baseline_provider=None,
    )
    trace = []
    for signal in SEQ:
        trace.append(aff.update(signal))
    return trace


def run_traj(baseline_provider=None):
    aff = AffectState(
        estimator=probe_estimator,
        config=AffectConfig(momentum=0.8, rate=0.5, baseline=NONTRIVIAL, trajectory_len=0),
        baseline_provider=baseline_provider,
    )
    trace = []
    for signal in SEQ:
        trace.append(aff.update(signal))
    return trace


def l1_area(a, b):
    return sum(abs(x - y) for p, q in zip(a, b) for x, y in zip(p, q))


def allclose_traces(a, b, tol=1e-12):
    return all(abs(x - y) <= tol for p, q in zip(a, b) for x, y in zip(p, q))


def baseline_shift(homeostasis: Homeostasis) -> float:
    tv = homeostasis.target_vad()
    bv = homeostasis.baseline_vad
    return sum(abs(x - y) for x, y in zip(tv, bv))


def main() -> None:
    print("# Couplage homéostasie -> affect")
    print("Mesure de régulation fonctionnelle, pas de ressenti.")

    affect_only = run_traj_cfg(NONTRIVIAL)
    coupled_neutral = run_traj(lambda: NONTRIVIAL)

    degraded_homeo = Homeostasis(resources=0.2, load=0.7, baseline_vad=NONTRIVIAL)
    coupled_degraded = run_traj(degraded_homeo.target_vad)

    neutral_ok = allclose_traces(affect_only, coupled_neutral, tol=1e-12)
    degraded_area = l1_area(affect_only, coupled_degraded)
    degraded_valence = [step[0] for step in coupled_degraded]
    reference_valence = [step[0] for step in affect_only]
    valence_tilt_negative = degraded_valence[-1] < reference_valence[-1]

    print(f"baseline_nontrivial: {NONTRIVIAL}")
    print(f"affect_only: {affect_only}")
    print(f"coupled_neutral: {coupled_neutral}")
    print(f"coupled_degraded: {coupled_degraded}")
    print(f"neutral_identical: {'PASS' if neutral_ok else 'FAIL'}")
    print(f"degraded_area_l1: {degraded_area:.6f}")
    print(f"degraded_valence_final: {degraded_valence[-1]:.6f}")
    print(f"reference_valence_final: {reference_valence[-1]:.6f}")
    print(f"coupling_effect: {'PASS' if degraded_area > 0.1 and valence_tilt_negative else 'FAIL'}")

    print("# attribution sweep")
    shifts = []
    for deficit in (0.0, 0.3, 0.6, 0.9):
        h = Homeostasis(resources=1.0 - deficit, load=0.0, baseline_vad=NONTRIVIAL)
        shift = baseline_shift(h)
        shifts.append(shift)
        print(f"deficit={deficit:.1f} target_vad={h.target_vad()} shift_l1={shift:.6f}")

    monotone = all(x <= y for x, y in zip(shifts, shifts[1:]))
    print(f"attribution_monotone: {'PASS' if monotone else 'FAIL'}")


if __name__ == "__main__":
    main()
