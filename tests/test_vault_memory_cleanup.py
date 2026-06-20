from __future__ import annotations

from datetime import datetime, timedelta

from memory.vault_memory import VaultEntry, VaultMemory


import pytest


@pytest.mark.stale
@pytest.mark.xfail(reason="VaultMemory.cleanup_expired not implemented yet", strict=False)
def test_cleanup_expired_removes_expires_at_entries(tmp_path):
    vm = VaultMemory(vault_path=str(tmp_path / "vault.json"))
    now = datetime(2026, 1, 1, 12, 0, 0)

    assert vm.store(VaultEntry(
        key="expired",
        content="old",
        metadata={"expires_at": (now - timedelta(seconds=1)).isoformat()},
    ))
    assert vm.store(VaultEntry(
        key="kept",
        content="new",
        metadata={"expires_at": (now + timedelta(days=1)).isoformat()},
    ))

    assert vm.cleanup_expired(now=now) == 1
    assert "expired" not in vm._entries
    assert "kept" in vm._entries


@pytest.mark.stale
@pytest.mark.xfail(reason="VaultMemory.cleanup_expired not implemented yet", strict=False)
def test_cleanup_expired_supports_ttl_seconds(tmp_path):
    vm = VaultMemory(vault_path=str(tmp_path / "vault.json"))
    now = datetime(2026, 1, 1, 12, 0, 0)
    base = (now - timedelta(seconds=30)).isoformat()

    assert vm.store(VaultEntry(
        key="ttl-expired",
        content="old",
        metadata={"ttl_seconds": 10},
        created_at=base,
        updated_at=base,
    ))
    vm._entries["ttl-expired"].created_at = base
    vm._entries["ttl-expired"].updated_at = base

    assert vm.cleanup_expired(now=now) == 1
    assert vm._entries == {}
