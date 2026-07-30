"""Canonical functional wellbeing contract.

These tests deliberately describe a functional, bounded state machine. They do
not model consciousness, subjective feelings, or autonomous self-modification.
"""

from __future__ import annotations

import math
from dataclasses import FrozenInstanceError

import pytest

from core.affect_state import (
    METAPLASTICITY_ENABLED,
    AffectConfig,
    AffectSnapshot,
    AffectState,
)
from core.resource_guard import ResourceSnapshot, SystemStatus
from core.wellbeing import FunctionalWellbeing, Homeostasis, WellbeingSnapshot


VAD_ZERO = (0.0, 0.0, 0.0)


def _assert_vad_bounded(values: tuple[float, float, float]) -> None:
    assert isinstance(values, tuple)
    assert len(values) == 3
    assert all(math.isfinite(value) for value in values)
    assert all(-1.0 <= value <= 1.0 for value in values)


def _assert_velocity_bounded(values: tuple[float, float, float]) -> None:
    assert isinstance(values, tuple)
    assert len(values) == 3
    assert all(math.isfinite(value) for value in values)
    assert all(-2.0 <= value <= 2.0 for value in values)


def _assert_wellbeing_snapshot(snapshot: WellbeingSnapshot) -> None:
    assert isinstance(snapshot, WellbeingSnapshot)
    assert isinstance(snapshot.known, bool)
    assert math.isfinite(snapshot.viability)
    assert 0.0 <= snapshot.viability <= 1.0
    _assert_vad_bounded(snapshot.target_vad)
    assert isinstance(snapshot.affect, AffectSnapshot)
    _assert_vad_bounded(snapshot.affect.state)
    _assert_velocity_bounded(snapshot.affect.velocity)


def test_affect_config_has_exact_canonical_defaults() -> None:
    config = AffectConfig()

    assert config.momentum == 0.6
    assert config.update_rate == 0.5
    assert config.baseline == VAD_ZERO
    assert config.trajectory_limit == 64


@pytest.mark.parametrize(
    "kwargs",
    [
        {"momentum": -0.01},
        {"momentum": 1.0},
        {"momentum": float("nan")},
        {"momentum": float("inf")},
        {"momentum": "slow"},
        {"momentum": True},
        {"update_rate": 0.0},
        {"update_rate": 1.01},
        {"update_rate": float("nan")},
        {"update_rate": float("-inf")},
        {"update_rate": "fast"},
        {"update_rate": False},
        {"baseline": (0.0, 0.0)},
        {"baseline": (0.0, 0.0, 0.0, 0.0)},
        {"baseline": (0.0, float("nan"), 0.0)},
        {"baseline": (0.0, float("inf"), 0.0)},
        {"baseline": (0.0, 1.01, 0.0)},
        {"baseline": (0.0, "neutral", 0.0)},
        {"baseline": (0.0, True, 0.0)},
        {"baseline": [0.0, 0.0, 0.0]},
        {"trajectory_limit": -1},
        {"trajectory_limit": 1.5},
        {"trajectory_limit": True},
        {"trajectory_limit": "64"},
    ],
)
def test_affect_config_rejects_invalid_values(kwargs: dict) -> None:
    with pytest.raises((TypeError, ValueError)):
        AffectConfig(**kwargs)


def test_affect_update_uses_exact_momentum_and_update_rate() -> None:
    affect = AffectState()

    first = affect.update((1.0, -1.0, 0.5))
    assert isinstance(first, AffectSnapshot)
    assert first.velocity == pytest.approx((0.4, -0.4, 0.2))
    assert first.state == pytest.approx((0.2, -0.2, 0.1))
    assert affect.velocity == pytest.approx(first.velocity)
    assert affect.state == pytest.approx(first.state)

    second = affect.update((1.0, -1.0, 0.5))
    assert second.velocity == pytest.approx((0.56, -0.56, 0.28))
    assert second.state == pytest.approx((0.48, -0.48, 0.24))


def test_affect_state_and_velocity_remain_bounded_under_extreme_updates() -> None:
    affect = AffectState(AffectConfig(momentum=0.99, update_rate=1.0))

    for turn in range(500):
        target = (1.0, -1.0, 1.0) if turn % 2 == 0 else (-1.0, 1.0, -1.0)
        snapshot = affect.update(target)
        _assert_vad_bounded(snapshot.state)
        _assert_velocity_bounded(snapshot.velocity)


@pytest.mark.parametrize(
    "target",
    [
        None,
        0.5,
        "positive",
        (),
        (0.0,),
        (0.0, 0.0),
        (0.0, 0.0, 0.0, 0.0),
        (0.0, float("nan"), 0.0),
        (0.0, float("inf"), 0.0),
        (0.0, float("-inf"), 0.0),
        (0.0, 1.000001, 0.0),
        (0.0, -1.000001, 0.0),
        (0.0, "calm", 0.0),
        (0.0, True, 0.0),
    ],
)
def test_invalid_affect_target_is_rejected_transactionally(target: object) -> None:
    affect = AffectState(AffectConfig(trajectory_limit=4))
    affect.update((0.5, -0.25, 0.75))
    state_before = affect.state
    velocity_before = affect.velocity
    trajectory_before = affect.trajectory

    with pytest.raises((TypeError, ValueError)):
        affect.update(target)

    assert affect.state == state_before
    assert affect.velocity == velocity_before
    assert affect.trajectory == trajectory_before


def test_numeric_target_sequences_are_normalized_to_tuple_properties() -> None:
    affect = AffectState()

    snapshot = affect.update([1, 0, -1])

    assert isinstance(snapshot.state, tuple)
    assert isinstance(snapshot.velocity, tuple)
    assert isinstance(affect.state, tuple)
    assert isinstance(affect.velocity, tuple)
    assert isinstance(affect.trajectory, tuple)


def test_trajectory_is_bounded_and_contains_the_latest_snapshots() -> None:
    affect = AffectState(AffectConfig(trajectory_limit=2))

    first = affect.update((1.0, 0.0, 0.0))
    second = affect.update((0.0, 1.0, 0.0))
    third = affect.update((0.0, 0.0, 1.0))

    assert isinstance(affect.trajectory, tuple)
    assert affect.trajectory == (second, third)
    assert first not in affect.trajectory


def test_reset_restores_baseline_velocity_and_empty_trajectory() -> None:
    config = AffectConfig(baseline=(0.2, -0.1, 0.3), trajectory_limit=3)
    affect = AffectState(config)
    affect.update((-1.0, 1.0, -1.0))
    affect.update((1.0, -1.0, 1.0))

    affect.reset()

    assert affect.state == config.baseline
    assert affect.velocity == VAD_ZERO
    assert affect.trajectory == ()


def test_affect_configuration_and_snapshots_are_immutable() -> None:
    config = AffectConfig()
    affect = AffectState(config)
    snapshot = affect.update((1.0, 0.0, 0.0))

    with pytest.raises(FrozenInstanceError):
        config.momentum = 0.7
    with pytest.raises(FrozenInstanceError):
        snapshot.state = VAD_ZERO


@pytest.mark.parametrize(
    "state,velocity",
    [
        ((float("nan"), 0.0, 0.0), VAD_ZERO),
        ((1.01, 0.0, 0.0), VAD_ZERO),
        (VAD_ZERO, (float("inf"), 0.0, 0.0)),
        (VAD_ZERO, (2.01, 0.0, 0.0)),
    ],
)
def test_affect_snapshot_constructor_enforces_public_invariants(
    state,
    velocity,
) -> None:
    with pytest.raises(ValueError):
        AffectSnapshot(state=state, velocity=velocity)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"known": "yes"},
        {"viability": float("nan")},
        {"viability": 1.01},
        {"target_vad": (0.0, float("inf"), 0.0)},
        {"target_vad": (0.0, 1.01, 0.0)},
        {"affect": object()},
        {"resource_status": "HEALTHY"},
    ],
)
def test_wellbeing_snapshot_constructor_enforces_public_invariants(
    kwargs,
) -> None:
    values = {
        "known": True,
        "viability": 0.5,
        "target_vad": VAD_ZERO,
        "affect": AffectState().snapshot(),
        "resource_status": SystemStatus.NORMAL.value,
        **kwargs,
    }

    with pytest.raises((TypeError, ValueError)):
        WellbeingSnapshot(**values)


def test_metaplasticity_is_disabled_and_updates_do_not_modify_configuration() -> None:
    config = AffectConfig(momentum=0.7, update_rate=0.4)
    affect = AffectState(config)

    for _ in range(20):
        affect.update((1.0, -1.0, 0.5))

    assert METAPLASTICITY_ENABLED is False
    assert affect.config is config
    assert affect.config == AffectConfig(momentum=0.7, update_rate=0.4)


def test_homeostasis_viability_and_target_vad_are_exact_and_bounded() -> None:
    homeostasis = Homeostasis(resources=0.8, load=0.3)

    assert homeostasis.viability == pytest.approx(0.5)
    assert homeostasis.target_vad() == pytest.approx((-0.3, 0.3, -0.3))

    stressed = Homeostasis(resources=0.0, load=1.0)
    assert stressed.viability == 0.0
    assert stressed.target_vad(
        gain=0.6,
        baseline=(-0.8, 0.8, -0.8),
    ) == pytest.approx((-1.0, 1.0, -1.0))


@pytest.mark.parametrize(
    "resources,load",
    [
        (-0.01, 0.0),
        (1.01, 0.0),
        (0.0, -0.01),
        (0.0, 1.01),
        (float("nan"), 0.0),
        (float("inf"), 0.0),
        (0.0, float("-inf")),
        ("full", 0.0),
        (0.0, "idle"),
        (True, 0.0),
        (0.0, False),
    ],
)
def test_homeostasis_rejects_invalid_resources_and_load(
    resources: object,
    load: object,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        Homeostasis(resources=resources, load=load)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"gain": -0.01},
        {"gain": 1.01},
        {"gain": float("nan")},
        {"gain": float("inf")},
        {"gain": "high"},
        {"gain": True},
        {"baseline": (0.0, 0.0)},
        {"baseline": (0.0, 0.0, 0.0, 0.0)},
        {"baseline": (0.0, float("nan"), 0.0)},
        {"baseline": (0.0, 1.01, 0.0)},
        {"baseline": [0.0, 0.0, 0.0]},
    ],
)
def test_homeostasis_target_vad_rejects_invalid_configuration(kwargs: dict) -> None:
    homeostasis = Homeostasis(resources=1.0, load=0.0)

    with pytest.raises((TypeError, ValueError)):
        homeostasis.target_vad(**kwargs)


def test_homeostasis_is_immutable() -> None:
    homeostasis = Homeostasis(resources=1.0, load=0.0)

    with pytest.raises(FrozenInstanceError):
        homeostasis.resources = 0.5


def test_functional_wellbeing_observe_returns_exact_bounded_snapshot() -> None:
    wellbeing = FunctionalWellbeing()

    snapshot = wellbeing.observe(resources=0.2, load=0.7)

    _assert_wellbeing_snapshot(snapshot)
    assert snapshot.known is True
    assert snapshot.viability == 0.0
    assert snapshot.target_vad == pytest.approx((-0.6, 0.6, -0.6))
    assert snapshot.affect.velocity == pytest.approx((-0.24, 0.24, -0.24))
    assert snapshot.affect.state == pytest.approx((-0.12, 0.12, -0.12))


@pytest.mark.parametrize(
    "resources,load",
    [
        (float("nan"), 0.0),
        (0.0, float("inf")),
        (-0.1, 0.0),
        (0.0, 1.1),
        ("full", 0.0),
        (0.0, True),
    ],
)
def test_invalid_direct_observation_is_transactional(
    resources: object,
    load: object,
) -> None:
    wellbeing = FunctionalWellbeing()
    before = wellbeing.observe(resources=0.8, load=0.1)

    with pytest.raises((TypeError, ValueError)):
        wellbeing.observe(resources=resources, load=load)

    after = wellbeing.observe_resource_snapshot(
        ResourceSnapshot(status=SystemStatus.UNKNOWN)
    )
    assert after.known is False
    assert after.viability == before.viability
    assert after.target_vad == before.target_vad
    assert after.affect == before.affect


@pytest.mark.parametrize(
    "status",
    [SystemStatus.NORMAL, SystemStatus.SOFT_WARN],
)
def test_permitted_resource_snapshot_produces_known_bounded_state(
    status,
) -> None:
    wellbeing = FunctionalWellbeing()
    resource = ResourceSnapshot(
        ram_total_mb=16_384,
        ram_used_mb=6_144,
        ram_avail_mb=10_240,
        ram_pct=37.5,
        cpu_pct=25.0,
        active_agents=1,
        status=status,
    )

    snapshot = wellbeing.observe_resource_snapshot(resource)

    _assert_wellbeing_snapshot(snapshot)
    assert snapshot.known is True


def test_unknown_resource_snapshot_is_not_treated_as_healthy_and_does_not_mutate() -> None:
    wellbeing = FunctionalWellbeing()
    before = wellbeing.observe(resources=0.25, load=0.5)

    unknown = wellbeing.observe_resource_snapshot(
        ResourceSnapshot(
            ram_pct=0.0,
            cpu_pct=0.0,
            active_agents=0,
            status=SystemStatus.UNKNOWN,
        )
    )

    assert unknown.known is False
    assert unknown.viability == before.viability
    assert unknown.target_vad == before.target_vad
    assert unknown.affect == before.affect


@pytest.mark.parametrize("status", [SystemStatus.SAFE, SystemStatus.BLOCKED])
def test_restricted_resource_status_is_never_reported_as_known_healthy(
    status,
) -> None:
    wellbeing = FunctionalWellbeing()

    snapshot = wellbeing.observe_resource_snapshot(
        ResourceSnapshot(
            ram_total_mb=16_384,
            ram_used_mb=0,
            ram_avail_mb=16_384,
            ram_pct=0.0,
            cpu_pct=0.0,
            active_agents=0,
            status=status,
        )
    )

    assert snapshot.known is False
    assert snapshot.viability == 0.0
    assert snapshot.resource_status == status.value
    assert snapshot.affect == AffectState().snapshot()


@pytest.mark.parametrize(
    "field,value",
    [
        ("ram_pct", -0.1),
        ("ram_pct", 100.1),
        ("ram_pct", float("nan")),
        ("ram_pct", float("inf")),
        ("ram_pct", "high"),
        ("ram_pct", True),
        ("cpu_pct", -0.1),
        ("cpu_pct", 100.1),
        ("cpu_pct", float("nan")),
        ("cpu_pct", float("-inf")),
        ("cpu_pct", "busy"),
        ("cpu_pct", False),
        ("active_agents", -1),
        ("active_agents", 1.5),
        ("active_agents", "one"),
        ("active_agents", True),
    ],
)
def test_invalid_resource_metrics_return_unknown_without_mutation(
    field: str,
    value: object,
) -> None:
    wellbeing = FunctionalWellbeing()
    before = wellbeing.observe(resources=0.7, load=0.2)
    kwargs = {
        "ram_pct": 40.0,
        "cpu_pct": 20.0,
        "active_agents": 1,
        "status": SystemStatus.NORMAL,
        field: value,
    }

    invalid = wellbeing.observe_resource_snapshot(ResourceSnapshot(**kwargs))

    assert invalid.known is False
    assert invalid.viability == before.viability
    assert invalid.target_vad == before.target_vad
    assert invalid.affect == before.affect


def test_functional_wellbeing_instances_do_not_share_state() -> None:
    first = FunctionalWellbeing()
    second = FunctionalWellbeing()

    first_snapshot = first.observe(resources=0.0, load=1.0)
    second_snapshot = second.observe_resource_snapshot(
        ResourceSnapshot(status=SystemStatus.UNKNOWN)
    )

    assert first_snapshot.affect.state != VAD_ZERO
    assert second_snapshot.known is False
    assert second_snapshot.affect.state == VAD_ZERO
    assert second_snapshot.affect.velocity == VAD_ZERO


def test_functional_wellbeing_never_creates_persistent_state_files(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    affect = AffectState()
    wellbeing = FunctionalWellbeing()

    affect.update((1.0, 0.0, -1.0))
    wellbeing.observe(resources=0.4, load=0.3)
    wellbeing.observe_resource_snapshot(
        ResourceSnapshot(
            ram_pct=45.0,
            cpu_pct=30.0,
            active_agents=0,
            status=SystemStatus.NORMAL,
        )
    )

    assert list(tmp_path.rglob("*")) == []
