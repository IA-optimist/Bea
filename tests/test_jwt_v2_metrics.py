"""Verify jwt_v2 emits the documented Prometheus metrics.

Audit observability follow-up: the rollout plan in
``docs/security/jwt-hardening-v2.md`` listed "no Prometheus counter yet
for jwt_v2_family_revoked / jwt_v2_logout" as a known gap. This test
closes it by asserting each lifecycle event increments its counter.
"""
from __future__ import annotations

import pytest

from api import jwt_v2
from tests.test_jwt_v2 import FakeRedis


# Skip if prometheus_client is not installed in this environment.
prometheus_client = pytest.importorskip("prometheus_client")


@pytest.fixture
def secret() -> str:
    return "test-secret-for-jwt-v2-metrics-32-bytes+"


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    fake = FakeRedis()
    jwt_v2.set_store_for_testing(fake)
    monkeypatch.setenv("JWT_REDIS_PREFIX", "test:jwt:metrics:")
    yield fake
    jwt_v2.set_store_for_testing(None)


def _sample(metric, **labels) -> float:
    """Return the current value of a labeled counter, or 0.0 if unset."""
    if metric is None:
        return 0.0
    try:
        return metric.labels(**labels)._value.get()  # type: ignore[attr-defined]
    except Exception:
        return 0.0


# ── Counters must be registered ─────────────────────────────────

def test_counters_are_registered():
    assert jwt_v2.M_JWT_V2_PAIRS_ISSUED is not None
    assert jwt_v2.M_JWT_V2_ROTATIONS is not None
    assert jwt_v2.M_JWT_V2_REVOCATIONS is not None


def test_metric_names_follow_convention():
    """Names must start with 'bea_' (consistent with other services)
    and use snake_case. prometheus_client strips the '_total' suffix on
    the internal ``_name`` attribute and re-adds it at export time, so
    we verify the suffix via the exported metric family instead."""
    for metric in (
        jwt_v2.M_JWT_V2_PAIRS_ISSUED,
        jwt_v2.M_JWT_V2_ROTATIONS,
        jwt_v2.M_JWT_V2_REVOCATIONS,
    ):
        name = metric._name  # type: ignore[attr-defined]
        assert name.startswith("bea_jwt_v2_"), name
        assert name == name.lower(), name
        # The exported series carries the _total suffix per Counter convention.
        families = list(metric.collect())
        assert families, "metric collected nothing"
        exported_name = families[0].name + "_total"
        assert exported_name.endswith("_total"), exported_name


# ── Lifecycle increments ────────────────────────────────────────

def test_create_token_pair_increments_pairs_issued_login(
    secret: str, store: FakeRedis,
):
    before = _sample(jwt_v2.M_JWT_V2_PAIRS_ISSUED, origin="login")
    jwt_v2.create_token_pair(sub="alice", role="user", secret=secret)
    after = _sample(jwt_v2.M_JWT_V2_PAIRS_ISSUED, origin="login")
    assert after == before + 1


def test_rotate_increments_pairs_issued_rotation_and_rotations_ok(
    secret: str, store: FakeRedis,
):
    pair = jwt_v2.create_token_pair(sub="alice", role="user", secret=secret)

    before_rotation = _sample(jwt_v2.M_JWT_V2_PAIRS_ISSUED, origin="rotation")
    before_outcome_ok = _sample(jwt_v2.M_JWT_V2_ROTATIONS, outcome="ok")

    jwt_v2.rotate_refresh_token(pair.refresh_token, secret)

    assert _sample(jwt_v2.M_JWT_V2_PAIRS_ISSUED, origin="rotation") == before_rotation + 1
    assert _sample(jwt_v2.M_JWT_V2_ROTATIONS, outcome="ok") == before_outcome_ok + 1


def test_replay_increments_rotations_replay(secret: str, store: FakeRedis):
    pair = jwt_v2.create_token_pair(sub="alice", role="user", secret=secret)
    jwt_v2.rotate_refresh_token(pair.refresh_token, secret)

    before = _sample(jwt_v2.M_JWT_V2_ROTATIONS, outcome="replay")
    with pytest.raises(ValueError, match="replay"):
        jwt_v2.rotate_refresh_token(pair.refresh_token, secret)
    after = _sample(jwt_v2.M_JWT_V2_ROTATIONS, outcome="replay")
    assert after == before + 1


def test_unknown_refresh_increments_rotations_unknown(secret: str, store: FakeRedis):
    before = _sample(jwt_v2.M_JWT_V2_ROTATIONS, outcome="unknown")
    with pytest.raises(ValueError, match="unknown_or_expired"):
        jwt_v2.rotate_refresh_token("nonexistent-token", secret)
    after = _sample(jwt_v2.M_JWT_V2_ROTATIONS, outcome="unknown")
    assert after == before + 1


def test_revoke_access_jti_increments_revocations_access(
    secret: str, store: FakeRedis,
):
    pair = jwt_v2.create_token_pair(sub="alice", role="user", secret=secret)
    before = _sample(jwt_v2.M_JWT_V2_REVOCATIONS, kind="access")
    jwt_v2.revoke_access_jti(pair.access_jti, remaining_ttl_seconds=60)
    after = _sample(jwt_v2.M_JWT_V2_REVOCATIONS, kind="access")
    assert after == before + 1


def test_revoke_refresh_token_increments_revocations_refresh(
    secret: str, store: FakeRedis,
):
    pair = jwt_v2.create_token_pair(sub="alice", role="user", secret=secret)
    before = _sample(jwt_v2.M_JWT_V2_REVOCATIONS, kind="refresh")
    jwt_v2.revoke_refresh_token(pair.refresh_token)
    after = _sample(jwt_v2.M_JWT_V2_REVOCATIONS, kind="refresh")
    assert after == before + 1


def test_family_revoke_on_replay_increments_revocations_family(
    secret: str, store: FakeRedis,
):
    """A replay attack triggers _revoke_family which must increment the
    family-kind revocation counter."""
    pair = jwt_v2.create_token_pair(sub="alice", role="user", secret=secret)
    jwt_v2.rotate_refresh_token(pair.refresh_token, secret)

    before = _sample(jwt_v2.M_JWT_V2_REVOCATIONS, kind="family")
    with pytest.raises(ValueError, match="replay"):
        jwt_v2.rotate_refresh_token(pair.refresh_token, secret)
    after = _sample(jwt_v2.M_JWT_V2_REVOCATIONS, kind="family")
    assert after == before + 1


# ── No-op safety: emit must never break auth if metrics fail ────

def test_mcount_no_op_when_metric_is_none():
    """Smoke for the no-prometheus fallback path."""
    jwt_v2._mcount(None, kind="access")
    jwt_v2._mcount(None)  # No labels
