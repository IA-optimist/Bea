"""
Tests — Secret Vault System (40 tests)

Crypto Layer
  SV1.  derive_master_key produces 32-byte key
  SV2.  derive_master_key same password+salt = same key
  SV3.  derive_master_key different passwords = different keys
  SV4.  encrypt/decrypt roundtrip
  SV5.  decrypt wrong key → DecryptionError
  SV6.  EncryptedPayload serialize/deserialize roundtrip
  SV7.  unique nonce per encryption
  SV8.  empty plaintext → error

Policy Engine
  SV9.  admin has all permissions
  SV10. operator has use+list only
  SV11. viewer has list only
  SV12. agent allowlist enforcement
  SV13. domain allowlist enforcement
  SV14. wildcard allows all agents
  SV15. revoked secret → denied
  SV16. expired secret → denied
  SV17. auto_use disabled → denied for non-admin
  SV18. rate limit enforcement
  SV19. reveal never policy → denied
  SV20. reveal admin_only → operator denied

Audit Log
  SV21. Record creates entry
  SV22. Chain hash populated
  SV23. Query by secret_id
  SV24. Query by action
  SV25. Sensitive keys redacted
  SV26. Persistence to file
  SV27. Verify chain returns valid

TOTP
  SV28. Generate 6-digit code
  SV29. Generate 8-digit code
  SV30. Verify code in window
  SV31. Wrong code rejected
  SV32. Time remaining calculation

Vault Integration
  SV33. Create + use roundtrip
  SV34. Vault locked by default
  SV35. Unlock/lock cycle
  SV36. Wrong password rejected
  SV37. Auto-relock on timeout
  SV38. List shows metadata not values
  SV39. Delete removes secret
  SV40. Update rotates version
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.security.secret_crypto import (
    derive_master_key, encrypt, decrypt,
    EncryptedPayload, CryptoError, DecryptionError,
)
from core.security.secret_policy import (
    SecretMetadata, SecretPolicy, PolicyEngine,
    check_permission,
)
from core.security.secret_audit import (
    SecretAuditLog, AuditAction,
)
from core.security.totp_manager import (
    generate_totp, verify_totp, generate_seed,
    time_remaining,
)
from core.security.secret_vault import SecretVault

import pytest


# ═══════════════════════════════════════════════════════════════
# CRYPTO LAYER
# ═══════════════════════════════════════════════════════════════

class TestCrypto:

    def test_derive_key_length(self):
        """SV1: 32-byte key."""
        key, salt = derive_master_key("test-password")
        assert len(key) == 32
        assert len(salt) == 32

    def test_derive_deterministic(self):
        """SV2: Same password+salt → same key."""
        key1, salt = derive_master_key("mypass")
        key2, _ = derive_master_key("mypass", salt)
        assert key1 == key2

    def test_derive_different_passwords(self):
        """SV3: Different passwords → different keys."""
        key1, salt = derive_master_key("pass1")
        key2, _ = derive_master_key("pass2", salt)
        assert key1 != key2

    def test_encrypt_decrypt_roundtrip(self):
        """SV4: Encrypt then decrypt recovers plaintext."""
        key, salt = derive_master_key("roundtrip-test")
        payload = encrypt("my-secret-api-key", key, salt)
        recovered = decrypt(payload, key)
        assert recovered == "my-secret-api-key"

    def test_decrypt_wrong_key(self):
        """SV5: Wrong key → DecryptionError."""
        key1, salt = derive_master_key("correct")
        key2, _ = derive_master_key("wrong", salt)
        payload = encrypt("secret", key1, salt)
        with pytest.raises(DecryptionError):
            decrypt(payload, key2)

    def test_payload_serialization(self):
        """SV6: Base64 roundtrip."""
        key, salt = derive_master_key("serial-test")
        payload = encrypt("test-value", key, salt)
        b64 = payload.to_b64()
        restored = EncryptedPayload.from_b64(b64)
        recovered = decrypt(restored, key)
        assert recovered == "test-value"

    def test_unique_nonces(self):
        """SV7: Each encrypt gets unique nonce."""
        key, salt = derive_master_key("nonce-test")
        p1 = encrypt("same", key, salt)
        p2 = encrypt("same", key, salt)
        assert p1.nonce != p2.nonce

    def test_empty_plaintext(self):
        """SV8: Empty plaintext → error."""
        key, salt = derive_master_key("empty-test")
        with pytest.raises(CryptoError):
            encrypt("", key, salt)


# ═══════════════════════════════════════════════════════════════
# POLICY ENGINE
# ═══════════════════════════════════════════════════════════════

class TestPolicy:

    def _meta(self, **kwargs) -> SecretMetadata:
        defaults = dict(secret_id="sec-test", name="test", policy=SecretPolicy())
        defaults.update(kwargs)
        return SecretMetadata(**defaults)

    def test_admin_all_perms(self):
        """SV9."""
        for action in ["create", "update", "delete", "use", "reveal", "list", "logs"]:
            assert check_permission("admin", action)

    def test_operator_limited(self):
        """SV10."""
        assert check_permission("operator", "use")
        assert check_permission("operator", "list")
        assert not check_permission("operator", "create")
        assert not check_permission("operator", "reveal")

    def test_viewer_list_only(self):
        """SV11."""
        assert check_permission("viewer", "list")
        assert not check_permission("viewer", "use")
        assert not check_permission("viewer", "reveal")

    def test_agent_allowlist(self):
        """SV12."""
        policy = SecretPolicy(allowed_agents=["coder", "devops"])
        meta = self._meta(policy=policy)
        engine = PolicyEngine()
        ok, _ = engine.check_use(meta, "coder", "example.com")
        assert ok
        ok, _ = engine.check_use(meta, "attacker", "example.com")
        assert not ok

    def test_domain_allowlist(self):
        """SV13."""
        policy = SecretPolicy(allowed_domains=["openai.com", "anthropic.com"])
        meta = self._meta(policy=policy)
        engine = PolicyEngine()
        ok, _ = engine.check_use(meta, "agent", "openai.com")
        assert ok
        ok, _ = engine.check_use(meta, "agent", "evil.com")
        assert not ok

    def test_wildcard_agents(self):
        """SV14."""
        meta = self._meta()  # Default: allowed_agents=["*"]
        engine = PolicyEngine()
        ok, _ = engine.check_use(meta, "any_agent", "any_domain")
        assert ok

    def test_revoked_denied(self):
        """SV15."""
        meta = self._meta(revoked=True)
        engine = PolicyEngine()
        ok, reason = engine.check_use(meta, "agent", "domain")
        assert not ok
        assert "revoked" in reason.lower()

    def test_expired_denied(self):
        """SV16."""
        policy = SecretPolicy(expires_at=time.time() - 100)
        meta = self._meta(policy=policy)
        engine = PolicyEngine()
        ok, reason = engine.check_use(meta, "agent", "domain")
        assert not ok
        assert "expired" in reason.lower()

    def test_auto_use_disabled(self):
        """SV17."""
        policy = SecretPolicy(auto_use_allowed=False)
        meta = self._meta(policy=policy)
        engine = PolicyEngine()
        ok, reason = engine.check_use(meta, "agent", "domain", role="operator")
        assert not ok
        # Admin should still work
        ok, _ = engine.check_use(meta, "agent", "domain", role="admin")
        assert ok

    def test_rate_limit(self):
        """SV18."""
        policy = SecretPolicy(max_uses_per_hour=3)
        meta = self._meta(policy=policy)
        engine = PolicyEngine()
        for _ in range(3):
            ok, _ = engine.check_use(meta, "agent", "domain")
            assert ok
        ok, reason = engine.check_use(meta, "agent", "domain")
        assert not ok
        assert "rate limit" in reason.lower()

    def test_reveal_never(self):
        """SV19."""
        policy = SecretPolicy(reveal_policy="never")
        meta = self._meta(policy=policy)
        engine = PolicyEngine()
        ok, _ = engine.check_reveal(meta, "admin")
        assert not ok

    def test_reveal_admin_only(self):
        """SV20."""
        policy = SecretPolicy(reveal_policy="admin_only")
        meta = self._meta(policy=policy)
        engine = PolicyEngine()
        ok, _ = engine.check_reveal(meta, "admin")
        assert ok
        ok, _ = engine.check_reveal(meta, "operator")
        assert not ok


# ═══════════════════════════════════════════════════════════════
# AUDIT LOG
# ═══════════════════════════════════════════════════════════════

class TestAudit:

    def test_record(self):
        """SV21."""
        audit = SecretAuditLog()
        entry = audit.record(AuditAction.USE, "sec-1", "coder", reason="API call")
        assert entry.action == "use"
        assert audit.entry_count == 1

    def test_chain_hash(self):
        """SV22."""
        audit = SecretAuditLog()
        e1 = audit.record(AuditAction.CREATE, "sec-1", "admin")
        e2 = audit.record(AuditAction.USE, "sec-1", "coder")
        assert e1.chain_hash
        assert e2.chain_hash
        assert e1.chain_hash != e2.chain_hash

    def test_query_by_secret(self):
        """SV23."""
        audit = SecretAuditLog()
        audit.record(AuditAction.USE, "sec-1", "agent")
        audit.record(AuditAction.USE, "sec-2", "agent")
        audit.record(AuditAction.USE, "sec-1", "agent")
        results = audit.query(secret_id="sec-1")
        assert len(results) == 2

    def test_query_by_action(self):
        """SV24."""
        audit = SecretAuditLog()
        audit.record(AuditAction.CREATE, "sec-1", "admin")
        audit.record(AuditAction.USE, "sec-1", "agent")
        results = audit.query(action="create")
        assert len(results) == 1

    def test_sensitive_redacted(self):
        """SV25."""
        audit = SecretAuditLog()
        entry = audit.record(
            AuditAction.CREATE, "sec-1", "admin",
            metadata={"plaintext": "SHOULD_NOT_APPEAR", "type": "api_key"},
        )
        d = entry.to_dict()
        # Plaintext value must NEVER appear in output
        assert "SHOULD_NOT_APPEAR" not in str(d)
        # Sensitive key stripped from to_dict() output entirely
        assert "plaintext" not in d["meta"]
        # Non-sensitive keys preserved
        assert d["meta"]["type"] == "api_key"
        # Internal entry has redacted value
        assert entry.metadata["plaintext"] == "[REDACTED]"

    def test_persistence(self, tmp_path):
        """SV26."""
        log_file = tmp_path / "audit.jsonl"
        audit = SecretAuditLog(log_file)
        audit.record(AuditAction.CREATE, "sec-1", "admin")
        audit.record(AuditAction.USE, "sec-1", "agent")
        assert log_file.exists()
        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 2

    def test_verify_chain(self):
        """SV27."""
        audit = SecretAuditLog()
        audit.record(AuditAction.CREATE, "sec-1", "admin")
        audit.record(AuditAction.USE, "sec-1", "agent")
        valid, count = audit.verify_chain()
        assert valid


# ═══════════════════════════════════════════════════════════════
# TOTP
# ═══════════════════════════════════════════════════════════════

class TestTOTP:

    def test_generate_6_digit(self):
        """SV28."""
        seed_b32, seed_bytes = generate_seed()
        code = generate_totp(seed_bytes, digits=6)
        assert len(code) == 6
        assert code.isdigit()

    def test_generate_8_digit(self):
        """SV29."""
        _, seed_bytes = generate_seed()
        code = generate_totp(seed_bytes, digits=8)
        assert len(code) == 8
        assert code.isdigit()

    def test_verify_in_window(self):
        """SV30."""
        _, seed_bytes = generate_seed()
        code = generate_totp(seed_bytes)
        assert verify_totp(seed_bytes, code)

    def test_wrong_code_rejected(self):
        """SV31."""
        _, seed_bytes = generate_seed()
        assert not verify_totp(seed_bytes, "000000")

    def test_time_remaining(self):
        """SV32."""
        remaining = time_remaining(30)
        assert 0 < remaining <= 30


# ═══════════════════════════════════════════════════════════════
# VAULT INTEGRATION
# ═══════════════════════════════════════════════════════════════

class TestVaultIntegration:

    def _vault(self, tmp_path) -> SecretVault:
        v = SecretVault(vault_dir=tmp_path / "vault", lock_timeout=60)
        v.unlock("test-master-password")
        return v

    def test_create_use_roundtrip(self, tmp_path):
        """SV33."""
        vault = self._vault(tmp_path)
        meta = vault.create_secret("OpenAI Key", "sk-test-123", domain="openai.com")
        result = vault.use_secret(meta.secret_id, "coder", "openai.com", "API call")
        assert result.success
        assert result.inject_value == "sk-test-123"

    def test_locked_by_default(self, tmp_path):
        """SV34."""
        vault = SecretVault(vault_dir=tmp_path / "vault2")
        assert not vault.is_unlocked

    def test_unlock_lock_cycle(self, tmp_path):
        """SV35."""
        vault = SecretVault(vault_dir=tmp_path / "vault3")
        vault.unlock("password")
        assert vault.is_unlocked
        vault.lock()
        assert not vault.is_unlocked

    def test_wrong_password(self, tmp_path):
        """SV36."""
        vault = SecretVault(vault_dir=tmp_path / "vault4")
        vault.unlock("correct")
        vault.create_secret("test", "value")
        vault.lock()
        # Reload
        vault2 = SecretVault(vault_dir=tmp_path / "vault4")
        assert not vault2.unlock("wrong")

    def test_auto_relock(self, tmp_path):
        """SV37."""
        vault = SecretVault(vault_dir=tmp_path / "vault5", lock_timeout=1)
        vault.unlock("password")
        assert vault.is_unlocked
        # Simulate timeout
        vault._unlocked_at = time.time() - 10
        assert not vault.is_unlocked

    def test_list_no_values(self, tmp_path):
        """SV38."""
        vault = self._vault(tmp_path)
        vault.create_secret("Key1", "secret-value-1")
        vault.create_secret("Key2", "secret-value-2")
        listing = vault.list_secrets()
        assert len(listing) == 2
        for item in listing:
            assert "secret-value" not in str(item)
            assert "name" in item

    def test_delete(self, tmp_path):
        """SV39."""
        vault = self._vault(tmp_path)
        meta = vault.create_secret("Temp", "to-delete")
        assert vault.delete_secret(meta.secret_id)
        assert vault.secret_count == 0

    def test_update_version(self, tmp_path):
        """SV40."""
        vault = self._vault(tmp_path)
        meta = vault.create_secret("Rotating", "v1")
        assert meta.version == 1
        vault.update_secret(meta.secret_id, "v2")
        updated = vault.get_metadata(meta.secret_id)
        assert updated.version == 2
        # Verify new value
        result = vault.use_secret(meta.secret_id, "agent", "domain")
        assert result.inject_value == "v2"
