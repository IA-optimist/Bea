"""Tests pour memory.user_model — persistance JSON réelle, sans mock."""
from __future__ import annotations

from memory.user_model import UserModel


def test_set_get_persist(tmp_path):
    p = str(tmp_path / "user.json")
    um = UserModel(p)
    um.set_trait("langue", "fr", source="explicit")
    um.set_trait("stack_pref", "python+docker")
    assert um.get("langue") == "fr"
    # rechargé depuis le disque
    um2 = UserModel(p)
    assert um2.get("stack_pref") == "python+docker"
    assert um2.get("inconnu", "défaut") == "défaut"


def test_forget(tmp_path):
    um = UserModel(str(tmp_path / "u.json"))
    um.set_trait("temp", 1)
    assert um.forget("temp") is True
    assert um.forget("temp") is False
    assert um.get("temp") is None


def test_empty_key_ignored(tmp_path):
    um = UserModel(str(tmp_path / "u.json"))
    um.set_trait("  ", "x")
    assert um.as_dict() == {}


def test_summary_and_as_dict(tmp_path):
    um = UserModel(str(tmp_path / "u.json"))
    um.set_trait("ville", "Paris")
    assert um.as_dict() == {"ville": "Paris"}
    assert "Paris" in um.summary()


def test_corrupt_file_fails_open(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{ not valid json", encoding="utf-8")
    um = UserModel(str(p))  # ne doit pas lever
    assert um.as_dict() == {}
    um.set_trait("ok", 1)
    assert um.get("ok") == 1
