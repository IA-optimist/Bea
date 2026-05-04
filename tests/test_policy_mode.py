"""Tests for core/policy_mode.py — PolicyMode store."""


def test_import():
    pass


def test_default_is_balanced():
    from core.policy_mode import PolicyModeStore, PolicyMode
    store = PolicyModeStore()
    assert store.get() == PolicyMode.BALANCED


def test_set_valid_modes():
    from core.policy_mode import PolicyModeStore, PolicyMode
    store = PolicyModeStore()
    assert store.set("SAFE")
    assert store.get() == PolicyMode.SAFE
    assert store.set("UNCENSORED")
    assert store.get() == PolicyMode.UNCENSORED
    assert store.set("BALANCED")
    assert store.get() == PolicyMode.BALANCED


def test_set_case_insensitive():
    from core.policy_mode import PolicyModeStore, PolicyMode
    store = PolicyModeStore()
    assert store.set("safe")
    assert store.get() == PolicyMode.SAFE
    assert store.set("uncensored")
    assert store.get() == PolicyMode.UNCENSORED


def test_set_invalid_mode():
    from core.policy_mode import PolicyModeStore
    store = PolicyModeStore()
    original = store.get()
    assert not store.set("INVALID_MODE")
    assert store.get() == original  # unchanged


def test_uncensored_activation_counter():
    from core.policy_mode import PolicyModeStore
    store = PolicyModeStore()
    store.set("UNCENSORED")
    store.set("BALANCED")
    store.set("UNCENSORED")
    stats = store.get_uncensored_stats()
    assert stats["uncensored_activations"] == 2
    assert stats["is_uncensored"] is True


def test_to_dict():
    from core.policy_mode import PolicyModeStore
    store = PolicyModeStore()
    d = store.to_dict()
    assert d["current"] == "BALANCED"
    assert "description" in d
    assert "available" in d
    assert len(d["available"]) == 3


def test_singleton():
    from core.policy_mode import get_policy_mode_store
    s1 = get_policy_mode_store()
    s2 = get_policy_mode_store()
    assert s1 is s2
