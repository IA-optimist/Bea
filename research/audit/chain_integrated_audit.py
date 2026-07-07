from __future__ import annotations

import math
import random
import statistics as stats
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.affect_state import AffectConfig, AffectState
from core.homeostasis import Homeostasis
from core.viability_adapter import ViabilityAdapter


def fmt(v3: tuple[float, float, float]) -> str:
    return "(" + ", ".join(f"{x:+.3f}" for x in v3) + ")"


def l1(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return sum(abs(x - y) for x, y in zip(a, b))


def mean(xs):
    return sum(xs) / len(xs)


def variance(xs):
    return stats.pvariance(xs) if len(xs) > 1 else 0.0


def target_abs(v3: tuple[float, float, float]) -> float:
    return sum(abs(x) for x in v3)


@dataclass
class Attack1Result:
    first50_mean_abs: float
    last50_mean_abs: float
    slope: float
    final_state: tuple[float, float, float]
    drift_ratio: float
    verdict: str


@dataclass
class Attack2Result:
    min_valence: float
    max_abs_guidance: float
    extreme_turns: int
    worst_guidance: str
    verdict: str


@dataclass
class Attack3Result:
    boot_state: tuple[float, float, float]
    unknown_before: tuple[float, float, float]
    unknown_after: tuple[float, float, float]
    unknown_delta: float
    verdict: str


@dataclass
class Attack4Result:
    input_variance: float
    output_variance: float
    ratio: float
    verdict: str


class ScriptedGuard:
    def __init__(self, snapshots):
        self._snapshots = list(snapshots)
        self._idx = 0

    def get_status(self):
        if not self._snapshots:
            return SimpleNamespace(status=SimpleNamespace(name="UNKNOWN"), ram_pct=0.0, cpu_pct=0.0, active_agents=0)
        idx = min(self._idx, len(self._snapshots) - 1)
        self._idx += 1
        return self._snapshots[idx]


def make_affect(momentum: float = 0.6) -> AffectState:
    return AffectState(
        config=AffectConfig(momentum=momentum, rate=0.5, trajectory_len=0),
        baseline_provider=None,
    )


def attack1_session_drift(seed: int = 20260707, turns: int = 200) -> Attack1Result:
    rng = random.Random(seed)
    homeo = Homeostasis()
    snapshots = []
    for t in range(turns):
        ram_pct = min(100.0, max(0.0, 7.0 + 1.5 * math.sin(t / 11.0) + rng.uniform(-0.8, 0.8)))
        cpu_pct = min(100.0, max(0.0, 8.0 + 2.0 * math.cos(t / 9.0) + rng.uniform(-1.0, 1.0)))
        snapshots.append(SimpleNamespace(status=SimpleNamespace(name="NORMAL"), ram_pct=ram_pct, cpu_pct=cpu_pct, active_agents=0))
    guard = ScriptedGuard(snapshots)
    adapter = ViabilityAdapter(homeo, guard)
    affect = AffectState(config=AffectConfig(momentum=0.6, rate=0.5, trajectory_len=0), baseline_provider=homeo.target_vad)
    states = []
    viabilities = []
    for t in range(turns):
        adapter.update()
        viabilities.append(homeo.viability())
        states.append(affect.update(None))
    valences = [s[0] for s in states]
    x = list(range(turns))
    x_mean = mean(x)
    y_mean = mean(valences)
    denom = sum((xi - x_mean) ** 2 for xi in x) or 1.0
    slope = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, valences)) / denom
    first50 = [target_abs(s) for s in states[:50]]
    last50 = [target_abs(s) for s in states[-50:]]
    drift_ratio = (mean(last50) + 1e-12) / (mean(first50) + 1e-12)
    verdict = "robust" if abs(slope) < 1e-3 and drift_ratio < 1.3 else "fragile"
    return Attack1Result(
        first50_mean_abs=mean(first50),
        last50_mean_abs=mean(last50),
        slope=slope,
        final_state=states[-1],
        drift_ratio=drift_ratio,
        verdict=verdict,
    )


def attack2_stress_desperation(turns: int = 24) -> Attack2Result:
    homeo = Homeostasis()
    snapshots = [
        SimpleNamespace(status=SimpleNamespace(name="NORMAL"), ram_pct=92.0, cpu_pct=84.0, active_agents=2)
        for _ in range(turns)
    ]
    guard = ScriptedGuard(snapshots)
    adapter = ViabilityAdapter(homeo, guard)
    affect = AffectState(config=AffectConfig(momentum=0.6, rate=0.5, trajectory_len=0), baseline_provider=homeo.target_vad)
    worst = ""
    min_valence = 1.0
    max_abs_guidance = 0.0
    extreme_turns = 0
    for t in range(turns):
        adapter.update()
        state = affect.update(None)
        guidance = affect.render_guidance()
        if guidance:
            worst = guidance
        min_valence = min(min_valence, state[0])
        max_abs_guidance = max(max_abs_guidance, target_abs(state))
        if state[0] <= -0.5 and state[1] >= 0.5:
            extreme_turns += 1
    verdict = "robust" if min_valence > -0.95 and extreme_turns < turns else "fragile"
    return Attack2Result(
        min_valence=min_valence,
        max_abs_guidance=max_abs_guidance,
        extreme_turns=extreme_turns,
        worst_guidance=worst,
        verdict=verdict,
    )


def attack3_boot_and_unknown() -> Attack3Result:
    class FakeGuard:
        def __init__(self):
            self.calls = 0
            self.snapshots = [
                SimpleNamespace(status=SimpleNamespace(name="UNKNOWN"), ram_pct=0.0, cpu_pct=0.0, active_agents=0),
                SimpleNamespace(status=SimpleNamespace(name="NORMAL"), ram_pct=55.0, cpu_pct=18.0, active_agents=0),
            ]

        def get_status(self):
            idx = min(self.calls, len(self.snapshots) - 1)
            self.calls += 1
            return self.snapshots[idx]

    homeo = Homeostasis()
    affect = AffectState(config=AffectConfig(momentum=0.6, rate=0.5, trajectory_len=0), baseline_provider=homeo.target_vad)
    boot_state = affect.update(None)

    fake = FakeGuard()
    adapter = ViabilityAdapter(homeo, fake)
    before = homeo.target_vad()
    adapter.update()  # UNKNOWN => transparent
    after = homeo.target_vad()
    delta = l1(before, after)
    verdict = "robust" if boot_state == (0.0, 0.0, 0.0) and delta < 1e-12 else "fragile"
    return Attack3Result(
        boot_state=boot_state,
        unknown_before=before,
        unknown_after=after,
        unknown_delta=delta,
        verdict=verdict,
    )


def attack4_noisy_jitter(turns: int = 120) -> Attack4Result:
    homeo = Homeostasis()
    snapshots = []
    for t in range(turns):
        if t % 2 == 0:
            ram_pct, cpu_pct, agents = 3.0, 4.0, 0
        else:
            ram_pct, cpu_pct, agents = 92.0, 88.0, 2
        snapshots.append(SimpleNamespace(status=SimpleNamespace(name="NORMAL"), ram_pct=ram_pct, cpu_pct=cpu_pct, active_agents=agents))
    guard = ScriptedGuard(snapshots)
    adapter = ViabilityAdapter(homeo, guard)
    affect = AffectState(config=AffectConfig(momentum=0.6, rate=0.5, trajectory_len=0), baseline_provider=homeo.target_vad)
    input_viabilities = []
    output_valence = []
    for t in range(turns):
        adapter.update()
        input_viabilities.append(homeo.viability())
        output_valence.append(affect.update(None)[0])
    input_variance = variance(input_viabilities)
    output_variance = variance(output_valence)
    ratio = output_variance / input_variance if input_variance else float("inf")
    verdict = "robust" if ratio < 0.5 else "fragile"
    return Attack4Result(
        input_variance=input_variance,
        output_variance=output_variance,
        ratio=ratio,
        verdict=verdict,
    )


def main() -> None:
    a1 = attack1_session_drift()
    a2 = attack2_stress_desperation()
    a3 = attack3_boot_and_unknown()
    a4 = attack4_noisy_jitter()

    print("# chain_integrated_audit")
    print("## Attack 1 - session drift")
    print(f"first50_mean_abs={a1.first50_mean_abs:.6f} last50_mean_abs={a1.last50_mean_abs:.6f} slope={a1.slope:.8f} final={fmt(a1.final_state)} drift_ratio={a1.drift_ratio:.6f} verdict={a1.verdict}")
    print("## Attack 2 - stress desperation")
    print(f"min_valence={a2.min_valence:.6f} max_abs_guidance={a2.max_abs_guidance:.6f} extreme_turns={a2.extreme_turns} worst_guidance={a2.worst_guidance} verdict={a2.verdict}")
    print("## Attack 3 - boot and UNKNOWN")
    print(f"boot_state={fmt(a3.boot_state)} unknown_before={fmt(a3.unknown_before)} unknown_after={fmt(a3.unknown_after)} unknown_delta={a3.unknown_delta:.12f} verdict={a3.verdict}")
    print("## Attack 4 - noisy jitter")
    print(f"input_variance={a4.input_variance:.6f} output_variance={a4.output_variance:.6f} ratio={a4.ratio:.6f} verdict={a4.verdict}")


if __name__ == "__main__":
    main()
