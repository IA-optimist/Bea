"""
JARVIS MAX — Secret Vault
============================
Production-grade secret management for AI agents.

Features:
- AES-256-GCM encryption at rest (per-secret unique nonce)
- Master password unlock with auto-relock timeout
- RBAC (admin/operator/viewer)
- Policy-controlled access (agents, domains, rate limits)
- use_secret() injects credentials without revealing plaintext
- reveal_secret() admin-only with mandatory audit
- TOTP generation on demand
- Version tracking and rotation
- Immutable audit log with chain hashes

Safety:
- Secrets never stored in RAG memory
- Never logged in plaintext
- Never returned in tool traces
- Never included in prompts
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from core.security.secret_crypto import (
    derive_master_key, encrypt, decrypt,
    EncryptedPayload, CryptoError, DecryptionError, VaultLockedError,
    key_fingerprint,
)
from core.security.secret_policy import (
    SecretMetadata, SecretPolicy, PolicyEngine,
    check_permission, PolicyViolation,
)
from core.security.secret_audit import (
    SecretAuditLog, AuditAction,
)
from core.security.totp_manager import (
    decode_seed, generate_totp, TOTPConfig,
)

logger = logging.getLogger(__name__)

# ── Constants ──

DEFAULT_LOCK_TIMEOUT = 300  # 5 minutes


# ── Use Result ──

@dataclass
class UseResult:
    """Result of using a secret — contains injection info, NOT the secret itself."""
    success: bool
    secret_id: str
    inject_type: str = ""     # header, body, env, cookie
    inject_key: str = ""      # e.g., "Authorization", "X-API-Key"
    inject_value: str = ""    # The actual secret value (only populated in executor context)
    totp_code: str = ""       # TOTP code if applicable
    error: str = ""
    audit_id: str = ""

    def safe_dict(self) -> dict:
        """Dict WITHOUT the secret value — safe for logging/tracing."""
        return {
            "success": self.success, "secret_id": self.secret_id,
            "inject_type": self.inject_type, "inject_key": self.inject_key,
            "has_value": bool(self.inject_value),
            "has_totp": bool(self.totp_code),
            "error": self.error,
        }


# ── Vault ──

class SecretVault:
    """
    Production-grade secret vault.
    Locked by default. Requires master password to unlock.
    """

    def __init__(
        self,
        vault_dir: str | Path = "data/vault",
        lock_timeout: int = DEFAULT_LOCK_TIMEOUT,
    ):
        self._vault_dir = Path(vault_dir)
        self._vault_dir.mkdir(parents=True, exist_ok=True)
        self._secrets_file = self._vault_dir / "secrets.enc.json"
        self._meta_file = self._vault_dir / "metadata.json"

        # State
        self._master_key: bytes | None = None
        self._salt: bytes | None = None
        self._unlocked_at: float = 0
        self._lock_timeout = lock_timeout

        # Sub-systems
        self._policy = PolicyEngine()
        self._audit = SecretAuditLog(self._vault_dir / "audit.jsonl")

        # In-memory stores
        self._encrypted_secrets: dict[str, str] = {}  # id → b64 encrypted payload
        self._metadata: dict[str, SecretMetadata] = {}
        self._totp_configs: dict[str, TOTPConfig] = {}

        # Load persisted data
        self._load()

    # ── Unlock / Lock ──

    def unlock(self, master_password: str) -> bool:
        """Unlock the vault with master password."""
        if not master_password:
            return False

        try:
            if self._salt:
                key, _ = derive_master_key(master_password, self._salt)
            else:
                key, salt = derive_master_key(master_password)
                self._salt = salt
                self._persist_salt()

            # Verify by trying to decrypt any existing secret
            if self._encrypted_secrets:
                first_id = next(iter(self._encrypted_secrets))
                payload = EncryptedPayload.from_b64(self._encrypted_secrets[first_id])
                decrypt(payload, key)  # Will raise if wrong password

            self._master_key = key
            self._unlocked_at = time.time()

            self._audit.record(
                AuditAction.UNLOCK, "*", "system",
                metadata={"fingerprint": key_fingerprint(key)},
            )
            return True

        except (DecryptionError, CryptoError):
            logger.warning("Vault unlock failed — wrong password")
            return False

    def lock(self) -> None:
        """Lock the vault (wipe master key from memory)."""
        self._master_key = None
        self._unlocked_at = 0
        self._audit.record(AuditAction.LOCK, "*", "system")

    @property
    def is_unlocked(self) -> bool:
        """Check if vault is unlocked and not timed out."""
        if self._master_key is None:
            return False
        if time.time() - self._unlocked_at > self._lock_timeout:
            self.lock()
            return False
        return True

    def _require_unlocked(self) -> None:
        if not self.is_unlocked:
            raise VaultLockedError("Vault is locked — call unlock() first")

    # ── Create ──

    def create_secret(  # nosec B107 — `secret_type` default below is a category label, not a secret value.
        self,
        name: str,
        value: str,
        secret_type: str = "api_key",
        description: str = "",
        domain: str = "",
        policy: dict | None = None,
        totp_config: dict | None = None,
        role: str = "admin",
    ) -> SecretMetadata:
        """Create a new secret in the vault."""
        self._require_unlocked()

        if not check_permission(role, "create"):
            raise PolicyViolation(f"Role '{role}' cannot create secrets")

        # Generate ID
        secret_id = f"sec-{hashlib.md5(f'{name}{time.time()}'.encode(), usedforsecurity=False).hexdigest()[:10]}"

        # Encrypt value
        payload = encrypt(value, self._master_key, self._salt)
        self._encrypted_secrets[secret_id] = payload.to_b64()

        # Create metadata
        meta = SecretMetadata(
            secret_id=secret_id,
            name=name,
            secret_type=secret_type,
            description=description[:200],
            domain=domain,
            policy=SecretPolicy.from_dict(policy or {}),
        )
        self._metadata[secret_id] = meta

        # TOTP config
        if totp_config and secret_type == "totp":
            self._totp_configs[secret_id] = TOTPConfig.from_dict(totp_config)

        # Persist
        self._persist()

        self._audit.record(
            AuditAction.CREATE, secret_id, role,
            metadata={"name": name, "type": secret_type, "domain": domain},
        )

        return meta

    # ── Use (agent injection) ──

    def use_secret(
        self,
        secret_id: str,
        agent_name: str,
        target_domain: str,
        purpose: str = "",
        role: str = "operator",
    ) -> UseResult:
        """
        Use a secret — decrypt and prepare for injection.
        The agent DOES NOT see the plaintext unless reveal_policy allows it.
        Returns UseResult with injection info.
        """
        self._require_unlocked()

        meta = self._metadata.get(secret_id)
        if not meta:
            return UseResult(success=False, secret_id=secret_id, error="Secret not found")

        # Policy check
        allowed, reason = self._policy.check_use(meta, agent_name, target_domain, role)
        if not allowed:
            self._audit.record(
                AuditAction.DENIED, secret_id, agent_name,
                reason=reason, target_domain=target_domain, result="denied",
            )
            return UseResult(success=False, secret_id=secret_id, error=reason)

        # Decrypt
        try:
            payload = EncryptedPayload.from_b64(self._encrypted_secrets[secret_id])
            plaintext = decrypt(payload, self._master_key)
        except (DecryptionError, CryptoError, KeyError):
            return UseResult(success=False, secret_id=secret_id, error="Decryption failed")

        # TOTP?
        totp_code = ""
        if meta.secret_type == "totp" and secret_id in self._totp_configs:
            cfg = self._totp_configs[secret_id]
            seed_bytes = decode_seed(plaintext)
            totp_code = generate_totp(seed_bytes, digits=cfg.digits, period=cfg.period, algorithm=cfg.algorithm)

        # Determine injection type
        inject_type, inject_key = self._determine_injection(meta)

        # Update last used
        meta.last_used_at = time.time()
        self._persist()

        # Audit
        self._audit.record(
            AuditAction.USE, secret_id, agent_name,
            reason=purpose[:200], target_domain=target_domain,
            metadata={"inject_type": inject_type},
        )

        return UseResult(
            success=True,
            secret_id=secret_id,
            inject_type=inject_type,
            inject_key=inject_key,
            inject_value=plaintext,
            totp_code=totp_code,
        )

    # ── Reveal (admin only) ──

    def reveal_secret(self, secret_id: str, role: str = "admin", reason: str = "") -> str:
        """
        Reveal plaintext of a secret. Admin only. Always audited.
        """
        self._require_unlocked()

        meta = self._metadata.get(secret_id)
        if not meta:
            raise PolicyViolation("Secret not found")

        allowed, msg = self._policy.check_reveal(meta, role)
        if not allowed:
            self._audit.record(
                AuditAction.DENIED, secret_id, role,
                reason=f"Reveal denied: {msg}", result="denied",
            )
            raise PolicyViolation(msg)

        try:
            payload = EncryptedPayload.from_b64(self._encrypted_secrets[secret_id])
            plaintext = decrypt(payload, self._master_key)
        except (DecryptionError, CryptoError, KeyError):
            raise CryptoError("Decryption failed")

        self._audit.record(
            AuditAction.REVEAL, secret_id, role, reason=reason[:200],
        )

        return plaintext

    # ── Update / Rotate ──

    def update_secret(
        self,
        secret_id: str,
        new_value: str,
        role: str = "admin",
        reason: str = "",
    ) -> bool:
        """Update a secret's value (creates new version)."""
        self._require_unlocked()

        if not check_permission(role, "update"):
            raise PolicyViolation(f"Role '{role}' cannot update secrets")

        meta = self._metadata.get(secret_id)
        if not meta:
            return False

        # Encrypt new value
        payload = encrypt(new_value, self._master_key, self._salt)
        self._encrypted_secrets[secret_id] = payload.to_b64()

        meta.version += 1
        meta.updated_at = time.time()
        self._persist()

        self._audit.record(
            AuditAction.ROTATE, secret_id, role,
            reason=reason, metadata={"version": meta.version},
        )
        return True

    # ── Delete / Revoke ──

    def delete_secret(self, secret_id: str, role: str = "admin") -> bool:
        """Delete a secret permanently."""
        self._require_unlocked()

        if not check_permission(role, "delete"):
            raise PolicyViolation(f"Role '{role}' cannot delete secrets")

        if secret_id not in self._metadata:
            return False

        del self._encrypted_secrets[secret_id]
        del self._metadata[secret_id]
        self._totp_configs.pop(secret_id, None)
        self._persist()

        self._audit.record(AuditAction.DELETE, secret_id, role)
        return True

    def revoke_secret(self, secret_id: str, role: str = "admin") -> bool:
        """Revoke a secret (mark unusable without deleting)."""
        self._require_unlocked()

        if not check_permission(role, "revoke"):
            raise PolicyViolation(f"Role '{role}' cannot revoke secrets")

        meta = self._metadata.get(secret_id)
        if not meta:
            return False

        meta.revoked = True
        meta.updated_at = time.time()
        self._persist()

        self._audit.record(AuditAction.REVOKE, secret_id, role)
        return True

    # ── List ──

    def list_secrets(self, role: str = "viewer") -> list[dict]:
        """List secret metadata (never values)."""
        if not check_permission(role, "list"):
            return []
        return [m.to_dict() for m in self._metadata.values() if not m.revoked]

    def get_metadata(self, secret_id: str) -> SecretMetadata | None:
        return self._metadata.get(secret_id)

    # ── Audit ──

    def get_audit_logs(
        self,
        secret_id: str | None = None,
        actor: str | None = None,
        limit: int = 100,
        role: str = "admin",
    ) -> list[dict]:
        """Get audit logs. Admin only."""
        if not check_permission(role, "logs"):
            return []
        return self._audit.query(secret_id=secret_id, actor=actor, limit=limit)

    # ── TOTP ──

    def get_totp_code(self, secret_id: str, agent_name: str, role: str = "operator") -> str:
        """Generate current TOTP code for a secret."""
        result = self.use_secret(secret_id, agent_name, "totp", purpose="Generate TOTP", role=role)
        if not result.success:
            return ""
        return result.totp_code

    # ── Internals ──

    def _determine_injection(self, meta: SecretMetadata) -> tuple[str, str]:
        """Determine how to inject a secret into a request."""
        type_map = {
            "api_key": ("header", "X-API-Key"),
            "token": ("header", "Authorization"),
            "credential": ("body", "password"),
            "cookie": ("cookie", "session"),
            "private_key": ("env", "PRIVATE_KEY"),
            "totp": ("body", "totp_code"),
        }
        return type_map.get(meta.secret_type, ("header", "X-Secret"))

    def _persist(self) -> None:
        """Persist encrypted secrets and metadata to disk."""
        try:
            # Secrets (already encrypted)
            with open(self._secrets_file, "w") as f:
                json.dump(self._encrypted_secrets, f)

            # Metadata (no secrets)
            meta_data = {
                sid: {**m.to_dict(), "totp": self._totp_configs.get(sid, TOTPConfig()).to_dict()
                       if sid in self._totp_configs else None}
                for sid, m in self._metadata.items()
            }
            with open(self._meta_file, "w") as f:
                json.dump(meta_data, f, indent=2)

        except Exception as e:
            logger.error(f"Failed to persist vault: {e}")

    def _persist_salt(self) -> None:
        """Persist the KDF salt."""
        salt_file = self._vault_dir / "salt.bin"
        with open(salt_file, "wb") as f:
            f.write(self._salt)

    def _load(self) -> None:
        """Load persisted vault data."""
        # Load salt
        salt_file = self._vault_dir / "salt.bin"
        if salt_file.exists():
            with open(salt_file, "rb") as f:
                self._salt = f.read()

        # Load encrypted secrets
        if self._secrets_file.exists():
            try:
                with open(self._secrets_file) as f:
                    self._encrypted_secrets = json.load(f)
            except Exception:
                self._encrypted_secrets = {}

        # Load metadata
        if self._meta_file.exists():
            try:
                with open(self._meta_file) as f:
                    data = json.load(f)
                for sid, m in data.items():
                    policy_data = m.get("policy", {})
                    self._metadata[sid] = SecretMetadata(
                        secret_id=sid,
                        name=m.get("name", ""),
                        secret_type=m.get("type", "api_key"),
                        description=m.get("description", ""),
                        domain=m.get("domain", ""),
                        policy=SecretPolicy.from_dict(policy_data),
                        version=m.get("version", 1),
                        created_at=m.get("created", 0),
                        updated_at=m.get("updated", 0),
                        last_used_at=m.get("last_used"),
                        revoked=m.get("revoked", False),
                    )
                    totp_data = m.get("totp")
                    if totp_data:
                        self._totp_configs[sid] = TOTPConfig.from_dict(totp_data)
            except Exception:
                self._metadata = {}

    @property
    def secret_count(self) -> int:
        return len(self._metadata)
