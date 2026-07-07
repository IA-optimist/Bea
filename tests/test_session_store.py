from __future__ import annotations

from dataclasses import dataclass

import pytest

from core.session_store import InMemorySessionStore, RedisSessionStore, get_session_store


@dataclass
class _FakeRedis:
    values: dict[str, str]

    def __init__(self) -> None:
        self.values = {}
        self.ops: list[tuple[str, tuple]] = []

    def get(self, key: str):
        self.ops.append(("get", (key,)))
        return self.values.get(key)

    def set(self, key: str, value: str):
        self.ops.append(("set", (key, value)))
        self.values[key] = value

    def setex(self, key: str, ttl: int, value: str):
        self.ops.append(("setex", (key, ttl, value)))
        self.values[key] = value

    def delete(self, key: str):
        self.ops.append(("delete", (key,)))
        self.values.pop(key, None)

    def ping(self):
        self.ops.append(("ping", ()))
        return True


def test_inmemory_session_store_get_set_delete():
    store = InMemorySessionStore()
    store.set("sid-1", {"role": "tester", "count": 1})
    assert store.get("sid-1") == {"role": "tester", "count": 1}

    store.delete("sid-1")
    assert store.get("sid-1") is None


def test_inmemory_session_store_ttl_expires():
    store = InMemorySessionStore()
    store.set("sid-ttl", {"ok": True}, ttl_seconds=0)
    assert store.get("sid-ttl") is None


def test_local_profile_returns_inmemory_store(monkeypatch: pytest.MonkeyPatch):
    # local/dev defaults should not require Redis.
    monkeypatch.delenv("BEA_SESSION_STORE", raising=False)
    monkeypatch.delenv("BEA_REDIS_URL", raising=False)
    store = get_session_store("local")
    assert isinstance(store, InMemorySessionStore)


def test_private_beta_requires_redis(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("BEA_SESSION_STORE", raising=False)
    monkeypatch.delenv("BEA_REDIS_URL", raising=False)
    with pytest.raises(RuntimeError):
        get_session_store("private_beta")


def test_public_beta_requires_redis(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("BEA_SESSION_STORE", raising=False)
    monkeypatch.delenv("BEA_REDIS_URL", raising=False)
    with pytest.raises(RuntimeError):
        get_session_store("public_beta")


def test_redis_store_serializes_deserializes_with_fake_client():
    fake = _FakeRedis()
    store = RedisSessionStore(redis_url="redis://localhost:6379/0", client=fake)

    store.set("sid-2", {"nested": {"n": 1}}, ttl_seconds=60)
    assert fake.ops[0][0] == "setex"
    assert fake.values["bea:session:sid-2"] == '{"nested":{"n":1}}'

    assert store.get("sid-2") == {"nested": {"n": 1}}
    store.delete("sid-2")
    assert store.get("sid-2") is None


def test_beta_profile_with_redis_env_returns_redis_store(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BEA_SESSION_STORE", "redis")
    monkeypatch.setenv("BEA_REDIS_URL", "redis://localhost:6379/0")
    store = get_session_store("private_beta")
    assert isinstance(store, RedisSessionStore)


def test_beta_profile_memory_backend_is_rejected(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BEA_SESSION_STORE", "memory")
    monkeypatch.setenv("BEA_REDIS_URL", "redis://localhost:6379/0")
    with pytest.raises(RuntimeError):
        get_session_store("public_beta")
