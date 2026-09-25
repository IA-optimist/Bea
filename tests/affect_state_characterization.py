"""Caractérisation baseline de la couche VAD fonctionnelle.

Ce script mesure une régulation temporelle fonctionnelle (inertie /
hystérésis / récupération). Il ne revendique aucun ressenti.
"""
from __future__ import annotations

from core.affect_state import AffectConfig, AffectState


def probe_estimator(signal: str | None):
    if signal == "positive_signal":
        return (1.0, 1.0, 1.0)
    if signal == "negative_signal":
        return (-1.0, -1.0, -1.0)
    return (0.0, 0.0, 0.0)


def step_response(momentum: float) -> dict[str, float]:
    aff = AffectState(
        estimator=probe_estimator,
        config=AffectConfig(momentum=momentum, rate=0.5, baseline=(0.0, 0.0, 0.0), trajectory_len=0)
    )
    trace = []
    trace.append(aff.update(None))
    trace.append(aff.update("positive_signal"))
    trace.append(aff.update(None))
    for _ in range(8):
        trace.append(aff.update(None))
    vals = [step[0] for step in trace]
    return {
        "peak": max(vals),
        "trough": min(vals),
        "final": vals[-1],
    }


def hysteresis_area(momentum: float) -> float:
    aff = AffectState(
        estimator=probe_estimator,
        config=AffectConfig(momentum=momentum, rate=0.5, baseline=(0.0, 0.0, 0.0), trajectory_len=0)
    )
    forward = []
    for signal in (None, "positive_signal", "positive_signal", "negative_signal", None):
        forward.append(aff.update(signal))

    backward = []
    for signal in (None, "negative_signal", "negative_signal", "positive_signal", None):
        backward.append(aff.update(signal))

    area = 0.0
    for f, b in zip(forward, backward):
        area += abs(f[0] - b[0]) + abs(f[1] - b[1]) + abs(f[2] - b[2])
    return area


def inertia_signature(momentum: float) -> dict[str, int]:
    aff = AffectState(
        estimator=probe_estimator,
        config=AffectConfig(momentum=momentum, rate=0.5, baseline=(0.0, 0.0, 0.0), trajectory_len=0)
    )

    trace = []
    # Warm-up near baseline, then a single positive stimulus, then recovery.
    for signal in (None, None, "positive_signal", None, None, None, None, None, None, None, None, None):
        trace.append(aff.update(signal)[0])

    peak_idx = max(range(len(trace)), key=lambda i: abs(trace[i]))
    recovery_idx = None
    for i in range(peak_idx + 1, len(trace)):
        if abs(trace[i]) < 0.05:
            recovery_idx = i
            break

    if recovery_idx is None:
        recovery_idx = len(trace)

    return {
        "delay": peak_idx,
        "recovery": recovery_idx - peak_idx,
    }


def main() -> None:
    print("# AffectState baseline caractérisation")
    print("Mesure de régulation temporelle fonctionnelle, pas de ressenti.")

    low = step_response(0.8)
    high = step_response(0.95)
    hyst_08 = hysteresis_area(0.8)
    hyst_095 = hysteresis_area(0.95)
    inertia_08 = inertia_signature(0.8)
    inertia_095 = inertia_signature(0.95)

    print(f"step_response(momentum=0.8): {low}")
    print(f"step_response(momentum=0.95): {high}")
    print(f"hysteresis_area(momentum=0.8): {hyst_08:.6f}")
    print(f"hysteresis_area(momentum=0.95): {hyst_095:.6f}")
    print(f"inertia_signature(momentum=0.8): {inertia_08}")
    print(f"inertia_signature(momentum=0.95): {inertia_095}")

    step_success = low["peak"] > 0.0 and low["final"] < low["peak"]
    hyst_success = hyst_08 > 0.0 and hyst_095 > 0.0
    tunable_success = inertia_095["delay"] > inertia_08["delay"]

    verdicts = {
        "step_response": "SUCCES" if step_success else "ECHEC",
        "hysteresis": "SUCCES" if hyst_success else "ECHEC",
        "tunability": "SUCCES" if tunable_success else "ECHEC",
    }
    for name, verdict in verdicts.items():
        print(f"{name}: {verdict}")

    overall = all(v == "SUCCES" for v in verdicts.values())
    print(f"overall: {'SUCCES' if overall else 'ECHEC'}")


if __name__ == "__main__":
    main()
