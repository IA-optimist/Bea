"""Bounded functional VAD state.

This module models software telemetry only. It does not represent subjective
experience, consciousness, or felt emotion, and it never modifies its own
configuration.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
import threading
from typing import Sequence


VAD = tuple[float, float, float]
VAD_ZERO: VAD = (0.0, 0.0, 0.0)
METAPLASTICITY_ENABLED = False


def _finite_number(value: object, *, field_name: str) -> float:
    if isinstance(value, bool):
        raise TypeError(f"{field_name} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{field_name} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be finite")
    return number


def _bounded_number(
    value: object,
    *,
    field_name: str,
    lower: float,
    upper: float,
) -> float:
    number = _finite_number(value, field_name=field_name)
    if not lower <= number <= upper:
        raise ValueError(f"{field_name} must be within [{lower}, {upper}]")
    return number


def _validated_vad(
    values: object,
    *,
    field_name: str,
    require_tuple: bool = False,
) -> VAD:
    valid_types = (tuple,) if require_tuple else (tuple, list)
    if not isinstance(values, valid_types) or len(values) != 3:
        expected = "tuple" if require_tuple else "sequence"
        raise TypeError(f"{field_name} must be a three-value {expected}")
    return tuple(
        _bounded_number(
            value,
            field_name=f"{field_name}[{index}]",
            lower=-1.0,
            upper=1.0,
        )
        for index, value in enumerate(values)
    )


def _clip(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


@dataclass(frozen=True)
class AffectConfig:
    """Immutable parameters retained from the recovered July runtime."""

    momentum: float = 0.6
    update_rate: float = 0.5
    baseline: VAD = VAD_ZERO
    trajectory_limit: int = 64

    def __post_init__(self) -> None:
        momentum = _bounded_number(
            self.momentum,
            field_name="momentum",
            lower=0.0,
            upper=1.0,
        )
        if momentum == 1.0:
            raise ValueError("momentum must be lower than 1")
        update_rate = _bounded_number(
            self.update_rate,
            field_name="update_rate",
            lower=0.0,
            upper=1.0,
        )
        if update_rate == 0.0:
            raise ValueError("update_rate must be greater than 0")
        baseline = _validated_vad(
            self.baseline,
            field_name="baseline",
            require_tuple=True,
        )
        if (
            isinstance(self.trajectory_limit, bool)
            or not isinstance(self.trajectory_limit, int)
        ):
            raise TypeError("trajectory_limit must be an integer")
        if self.trajectory_limit < 0:
            raise ValueError("trajectory_limit must be non-negative")

        object.__setattr__(self, "momentum", momentum)
        object.__setattr__(self, "update_rate", update_rate)
        object.__setattr__(self, "baseline", baseline)


@dataclass(frozen=True)
class AffectSnapshot:
    state: VAD
    velocity: VAD


class AffectState:
    """Mission-scoped, transactionally updated VAD state."""

    def __init__(self, config: AffectConfig | None = None):
        self.config = config or AffectConfig()
        self._state: VAD = self.config.baseline
        self._velocity: VAD = VAD_ZERO
        self._trajectory: deque[AffectSnapshot] = deque(
            maxlen=self.config.trajectory_limit
        )
        self._lock = threading.RLock()

    @property
    def state(self) -> VAD:
        with self._lock:
            return self._state

    @property
    def velocity(self) -> VAD:
        with self._lock:
            return self._velocity

    @property
    def trajectory(self) -> tuple[AffectSnapshot, ...]:
        with self._lock:
            return tuple(self._trajectory)

    def snapshot(self) -> AffectSnapshot:
        with self._lock:
            return AffectSnapshot(state=self._state, velocity=self._velocity)

    def update(self, target: Sequence[object]) -> AffectSnapshot:
        """Apply one validated second-order update without partial mutation."""
        target_vad = _validated_vad(target, field_name="target")
        with self._lock:
            new_velocity = tuple(
                _clip(
                    self.config.momentum * velocity
                    + (1.0 - self.config.momentum) * (target_value - state),
                    -2.0,
                    2.0,
                )
                for velocity, target_value, state in zip(
                    self._velocity, target_vad, self._state, strict=True
                )
            )
            new_state = tuple(
                _clip(
                    state + self.config.update_rate * velocity,
                    -1.0,
                    1.0,
                )
                for state, velocity in zip(
                    self._state, new_velocity, strict=True
                )
            )
            if not all(
                math.isfinite(value) for value in (*new_velocity, *new_state)
            ):
                raise ValueError("affect update produced a non-finite value")

            snapshot = AffectSnapshot(
                state=new_state,
                velocity=new_velocity,
            )
            self._state = new_state
            self._velocity = new_velocity
            self._trajectory.append(snapshot)
            return snapshot

    def reset(self) -> None:
        with self._lock:
            self._state = self.config.baseline
            self._velocity = VAD_ZERO
            self._trajectory.clear()
