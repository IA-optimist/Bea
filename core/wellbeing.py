"""Mission-scoped functional wellbeing telemetry.

The state describes bounded software regulation signals. It is not a claim of
consciousness or subjective experience, and it is never persisted by default.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import threading

from core.affect_state import (
    METAPLASTICITY_ENABLED,
    VAD,
    AffectConfig,
    AffectSnapshot,
    AffectState,
)
from core.resource_guard import ResourceSnapshot, SystemStatus


def _unit(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError(f"{field_name} must be finite and within [0, 1]")
    return number


def _percentage(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 100.0:
        raise ValueError(f"{field_name} must be finite and within [0, 100]")
    return number


def _vad(values: object, *, field_name: str) -> VAD:
    if not isinstance(values, tuple) or len(values) != 3:
        raise TypeError(f"{field_name} must be a three-value tuple")
    result: list[float] = []
    for index, value in enumerate(values):
        if isinstance(value, bool):
            raise TypeError(f"{field_name}[{index}] must be numeric")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise TypeError(f"{field_name}[{index}] must be numeric") from exc
        if not math.isfinite(number) or not -1.0 <= number <= 1.0:
            raise ValueError(
                f"{field_name}[{index}] must be finite and within [-1, 1]"
            )
        result.append(number)
    return (result[0], result[1], result[2])


def _clip(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


@dataclass(frozen=True)
class Homeostasis:
    resources: float
    load: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "resources", _unit(self.resources, field_name="resources")
        )
        object.__setattr__(self, "load", _unit(self.load, field_name="load"))

    @property
    def viability(self) -> float:
        return _clip(self.resources - self.load, 0.0, 1.0)

    def target_vad(
        self,
        *,
        gain: float = 0.6,
        baseline: VAD = (0.0, 0.0, 0.0),
    ) -> VAD:
        gain_value = _unit(gain, field_name="gain")
        baseline_vad = _vad(baseline, field_name="baseline")
        deficit = 1.0 - self.viability
        delta = gain_value * deficit
        return (
            _clip(baseline_vad[0] - delta, -1.0, 1.0),
            _clip(baseline_vad[1] + delta, -1.0, 1.0),
            _clip(baseline_vad[2] - delta, -1.0, 1.0),
        )


@dataclass(frozen=True)
class WellbeingSnapshot:
    known: bool
    viability: float
    target_vad: VAD
    affect: AffectSnapshot
    resource_status: str = SystemStatus.UNKNOWN.value

    def to_dict(self) -> dict[str, object]:
        return {
            "known": self.known,
            "viability": round(self.viability, 4),
            "target_vad": list(self.target_vad),
            "vad": list(self.affect.state),
            "velocity": list(self.affect.velocity),
            "resource_status": self.resource_status,
            "metaplasticity_enabled": METAPLASTICITY_ENABLED,
            "persisted": False,
        }


class FunctionalWellbeing:
    """Ephemeral functional state owned by one mission evaluation."""

    def __init__(self, affect_config: AffectConfig | None = None):
        self._affect = AffectState(affect_config)
        self._lock = threading.RLock()
        baseline = self._affect.snapshot()
        self._last = WellbeingSnapshot(
            known=False,
            viability=0.0,
            target_vad=self._affect.config.baseline,
            affect=baseline,
        )

    def observe(self, *, resources: object, load: object) -> WellbeingSnapshot:
        """Validate an observation, update VAD, and publish one snapshot."""
        homeostasis = Homeostasis(
            resources=_unit(resources, field_name="resources"),
            load=_unit(load, field_name="load"),
        )
        target = homeostasis.target_vad(baseline=self._affect.config.baseline)
        with self._lock:
            affect = self._affect.update(target)
            self._last = WellbeingSnapshot(
                known=True,
                viability=homeostasis.viability,
                target_vad=target,
                affect=affect,
            )
            return self._last

    def observe_resource_snapshot(
        self, snapshot: ResourceSnapshot
    ) -> WellbeingSnapshot:
        """Translate ResourceGuard metrics without treating UNKNOWN as healthy."""
        try:
            status = (
                snapshot.status
                if isinstance(snapshot.status, SystemStatus)
                else SystemStatus(str(snapshot.status))
            )
        except (TypeError, ValueError):
            return self._unknown("INVALID")
        if status is SystemStatus.UNKNOWN:
            return self._unknown(status.value)

        try:
            ram_pct = _percentage(snapshot.ram_pct, field_name="ram_pct")
            cpu_pct = _percentage(snapshot.cpu_pct, field_name="cpu_pct")
            active_agents = snapshot.active_agents
            if (
                isinstance(active_agents, bool)
                or not isinstance(active_agents, int)
                or active_agents < 0
            ):
                raise ValueError("active_agents must be a non-negative integer")
        except (TypeError, ValueError):
            return self._unknown(status.value)

        resources = 1.0 - ram_pct / 100.0
        load = max(ram_pct, cpu_pct) / 100.0
        with self._lock:
            observed = self.observe(resources=resources, load=load)
            self._last = WellbeingSnapshot(
                known=True,
                viability=observed.viability,
                target_vad=observed.target_vad,
                affect=observed.affect,
                resource_status=status.value,
            )
            return self._last

    def _unknown(self, status: str) -> WellbeingSnapshot:
        with self._lock:
            return WellbeingSnapshot(
                known=False,
                viability=self._last.viability,
                target_vad=self._last.target_vad,
                affect=self._last.affect,
                resource_status=status,
            )
