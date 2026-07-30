"""Caractérisation de la dynamique pure de AffectState.

Mesure de régulation fonctionnelle, aucun ressenti revendiqué.
Couvre la réponse à l'échelon, l'hystérésis, le retard de phase lié au momentum,
le défaut calibré et la stabilité bornée.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.affect_state import AffectConfig, AffectState

Vec3 = tuple[float, float, float]


def estimator(signal: str) -> Vec3:
    if signal == "neg":
        return (-1.0, 0.0, 0.0)
    if signal == "pos":
        return (1.0, 0.0, 0.0)
    return (0.0, 0.0, 0.0)


def make_affect(momentum: float, rate: float = 0.5) -> AffectState:
    return AffectState(
        estimator=estimator,
        config=AffectConfig(momentum=momentum, rate=rate, trajectory_len=0),
    )


def run_sequence(momentum: float, sequence: list[str | None], rate: float = 0.5) -> list[Vec3]:
    aff = make_affect(momentum, rate=rate)
    return [aff.update(signal) for signal in sequence]


def target_for(signal: str | None) -> Vec3:
    return estimator(signal) if signal is not None else (0.0, 0.0, 0.0)


def lag_area(momentum: float, sequence: list[str | None], rate: float) -> float:
    trace = run_sequence(momentum, sequence, rate=rate)
    return sum(
        abs(x - y)
        for state, signal in zip(trace, sequence)
        for x, y in zip(state, target_for(signal))
    )


def phase_delay(momentum: float) -> int:
    sequence: list[str | None] = ["neg"] * 6 + [None] * 18
    vals = [state[0] for state in run_sequence(momentum, sequence)]
    return max(range(len(vals)), key=lambda i: abs(vals[i]))


def case_step_response() -> tuple[bool, str]:
    aff = make_affect(momentum=0.8)
    descent = [aff.update("neg")[0] for _ in range(6)]
    recovery = [aff.update(None)[0] for _ in range(16)]

    delayed = -1.0 < descent[0] < 0.0
    reached_negative = min(descent) < -0.8
    recovered = abs(recovery[-1]) < abs(recovery[0])
    ok = delayed and reached_negative and recovered
    detail = (
        f"first={descent[0]:+.3f} min_descent={min(descent):+.3f} "
        f"recovery_start={recovery[0]:+.3f} recovery_end={recovery[-1]:+.3f}"
    )
    return ok, detail


def case_hysteresis() -> tuple[bool, str]:
    sequence: list[str | None] = ["neg"] * 4 + [None] * 4 + ["pos"] * 4 + [None] * 4
    reference_area = lag_area(momentum=0.0, sequence=sequence, rate=1.0)
    inertial_area = lag_area(momentum=0.8, sequence=sequence, rate=0.5)

    if reference_area > 0:
        ok = inertial_area > 3.0 * reference_area
    else:
        ok = inertial_area > 0.1
    detail = f"area_m0_rate1={reference_area:.6f} area_m08={inertial_area:.6f}"
    return ok, detail


def case_phase_delay_monotone() -> tuple[bool, str]:
    delays = {m: phase_delay(m) for m in (0.6, 0.8, 0.95)}
    ok = delays[0.6] < delays[0.8] < delays[0.95]
    return ok, f"delays={delays}"


def case_default_momentum() -> tuple[bool, str]:
    momentum = AffectConfig().momentum
    return momentum == 0.6, f"default_momentum={momentum}"


def case_bounds_stability() -> tuple[bool, str]:
    aff = AffectState(
        estimator=lambda _signal: (1.0, 1.0, 1.0),
        config=AffectConfig(momentum=0.95, rate=0.5, trajectory_len=0),
    )
    states = [aff.update("pos") for _ in range(80)]

    max_abs = max(abs(x) for state in states for x in state)
    last_deltas = [
        max(abs(a - b) for a, b in zip(states[i], states[i - 1]))
        for i in range(len(states) - 5, len(states))
    ]
    bounded = max_abs <= 1.0
    converged = all(delta < 0.01 for delta in last_deltas)
    detail = (
        f"max_abs={max_abs:.3f} last_state={tuple(round(x, 3) for x in states[-1])} "
        f"last_deltas={[round(d, 6) for d in last_deltas]}"
    )
    return bounded and converged, detail


def report(name: str, result: tuple[bool, str]) -> bool:
    ok, detail = result
    print(f"{name}: {'PASS' if ok else 'FAIL'}  {detail}")
    return ok


def main() -> None:
    print("# AffectState characterization")
    print("Mesure de régulation fonctionnelle, aucun ressenti.")

    results = [
        report("step_response_delayed_recovery", case_step_response()),
        report("hysteresis_loop_relative", case_hysteresis()),
        report("phase_delay_monotone_momentum", case_phase_delay_monotone()),
        report("default_momentum_coherent", case_default_momentum()),
        report("bounds_stability_convergence", case_bounds_stability()),
    ]

    ok = all(results)
    print(f"overall: {'PASS' if ok else 'FAIL'}")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
