"""
JARVIS MAX — Identity Manager
=================================
Manages digital identities across services.

Integrates with Secret Vault for all credential storage.
Provides identity lifecycle: create → link → use → rotate → revoke.

All credentials flow through the Vault — Identity Manager only stores
metadata and references (secret IDs), never raw secrets.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from core.identity.identity_schema import (
    Identity, IdentityType, IdentityStatus, Environment, SessionState, SecretLink,
)
from core.identity.identity_templates import (
    IdentityTemplate, get_template, list_templates, TEMPLATES,
)
from core.identity.identity_policy import (
    IdentityPolicy, IdentityPolicyEngine, check_identity_permission,
)
from core.identity.identity_graph import IdentityGraph, EdgeType
from core.identity.identity_audit import IdentityAuditLog, IdentityAction
_silent_log = __import__("structlog").get_logger(__name__)

logger = logging.getLogger(__name__)


# ── Use Result ──

@dataclass
class IdentityUseResult:
    """Result of using an identity — contains vault UseResults."""
    success: bool
    identity_id: str
    provider: str = ""
    secrets_injected: int = 0
    session_state: str = "none"
    error: str = ""
    vault_results: list[dict] = field(default_factory=list)

    def safe_dict(self) -> dict:
        return {
            "success": self.success, "identity_id": self.identity_id,
            "provider": self.provider, "secrets_injected": self.secrets_injected,
            "session": self.session_state, "error": self.error,
        }


# ── Manager ──

class IdentityManager:
    """
    Core identity lifecycle manager.
    Vault integration: all secrets stored/retrieved via SecretVault.
    """

    def __init__(
        self,
        vault=None,
        data_dir: str | Path = "data/identity",
    ):
        self._vault = vault
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)

        self._identities: dict[str, Identity] = {}
        self._policies: dict[str, IdentityPolicy] = {}
        self._secret_links: dict[str, list[SecretLink]] = {}  # identity_id → links

        self._graph = IdentityGraph()
        self._policy_engine = IdentityPolicyEngine()
        self._audit = IdentityAuditLog(self._data_dir / "identity_audit.jsonl")

        self._load()

    # ── Create ──

    def create_identity(
        self,
        provider: str,
        display_name: str = "",
        secrets: dict[str, str] | None = None,
        fields: dict | None = None,
        environment: str = "prod",
        workspace_id: str = "",
        policy: dict | None = None,
        role: str = "admin",
    ) -> Identity:
        """
        Create a new identity, optionally storing secrets in Vault.

        Args:
            provider: Template provider name (e.g., "github", "stripe")
            display_name: Human-readable name
            secrets: {role: value} — stored encrypted in Vault
            fields: Additional identity fields (email, username, etc.)
            environment: dev/staging/prod
            workspace_id: Associated project
            policy: Custom policy overrides
            role: RBAC role of the requester
        """
        if not check_identity_permission(role, "create"):
            raise PermissionError(f"Role '{role}' cannot create identities")

        template = get_template(provider)
        fields = fields or {}

        # Validate required fields if template exists
        if template:
            valid, missing = template.validate_fields(fields)
            if not valid:
                raise ValueError(f"Missing required fields for {provider}: {missing}")

        # Generate ID
        iid = f"id-{hashlib.md5(f'{provider}{time.time()}'.encode()).hexdigest()[:10]}"

        # Determine risk and approval
        risk_level = template.risk_level if template else "medium"
        identity_type = template.identity_type if template else "api_account"
        requires_approval = template.requires_approval if template else False

        # Policy check
        allowed, reason = self._policy_engine.check_create(risk_level, requires_approval, role)
        if not allowed:
            raise PermissionError(reason)

        # Create identity
        identity = Identity(
            identity_id=iid,
            identity_type=identity_type,
            display_name=display_name or f"{provider}_{environment}",
            provider=provider,
            email=fields.get("email", ""),
            username=fields.get("username", ""),
            environment=environment,
            workspace_id=workspace_id,
            risk_level=risk_level,
            status="pending" if requires_approval else "active",
        )

        # Store secrets in Vault
        if secrets and self._vault:
            for secret_role, secret_value in secrets.items():
                secret_type = self._infer_secret_type(secret_role, template)
                try:
                    meta = self._vault.create_secret(
                        name=f"{provider}_{secret_role}_{iid}",
                        value=secret_value,
                        secret_type=secret_type,
                        description=f"{display_name or provider} — {secret_role}",
                        domain=template.expected_domains[0] if template and template.expected_domains else "",
                        policy={
                            "allowed_agents": template.recommended_agents if template else ["*"],
                            "allowed_domains": template.expected_domains if template else ["*"],
                            "risk_level": risk_level,
                        },
                        role="admin",
                    )
                    identity.linked_secrets.append(meta.secret_id)

                    link = SecretLink(
                        secret_id=meta.secret_id,
                        secret_role=secret_role,
                        identity_id=iid,
                        provider=provider,
                    )
                    self._secret_links.setdefault(iid, []).append(link)

                except Exception as e:
                    logger.error(f"Failed to store secret {secret_role}: {e}")

        # Create policy
        identity_policy = IdentityPolicy.from_dict(policy or {})
        if template and template.requires_approval:
            identity_policy.requires_approval = True
        self._policies[iid] = identity_policy

        # Add to graph
        self._graph.add_node(
            iid, "identity", display_name or provider,
            provider=provider, environment=environment,
        )
        if template:
            for domain in template.expected_domains:
                self._graph.link_identity_to_service(iid, domain)

        # Store
        self._identities[iid] = identity
        self._persist()

        # Audit
        self._audit.record(
            IdentityAction.CREATE, iid, role,
            environment=environment,
            details=f"provider={provider}, risk={risk_level}, secrets={len(secrets or {})}",
        )

        return identity

    # ── Use ──

    def use_identity(
        self,
        identity_id: str,
        agent_name: str,
        target_service: str = "",
        environment: str = "prod",
        purpose: str = "",
        role: str = "operator",
    ) -> IdentityUseResult:
        """
        Use an identity — retrieves credentials from Vault via use_secret.
        """
        identity = self._identities.get(identity_id)
        if not identity:
            return IdentityUseResult(success=False, identity_id=identity_id, error="Identity not found")

        policy = self._policies.get(identity_id, IdentityPolicy())

        # Policy check
        allowed, reason = self._policy_engine.check_use(
            identity_id, identity.status, identity.environment,
            policy, agent_name, environment, role,
        )
        if not allowed:
            self._audit.record(
                IdentityAction.DENIED, identity_id, agent_name,
                target=target_service, environment=environment,
                result="denied", details=reason,
            )
            return IdentityUseResult(
                success=False, identity_id=identity_id,
                provider=identity.provider, error=reason,
            )

        # Use secrets from Vault
        vault_results = []
        injected = 0

        if self._vault:
            for secret_id in identity.linked_secrets:
                domain = target_service or (
                    get_template(identity.provider).expected_domains[0]
                    if get_template(identity.provider) and get_template(identity.provider).expected_domains
                    else identity.provider
                )
                result = self._vault.use_secret(
                    secret_id, agent_name, domain, purpose, role="operator",
                )
                vault_results.append(result.safe_dict())
                if result.success:
                    injected += 1

        # Update state
        identity.mark_used()
        identity.session_state = "active"
        self._persist()

        # Audit
        self._audit.record(
            IdentityAction.USE, identity_id, agent_name,
            target=target_service, environment=environment,
            details=f"secrets_injected={injected}",
        )

        return IdentityUseResult(
            success=True,
            identity_id=identity_id,
            provider=identity.provider,
            secrets_injected=injected,
            session_state="active",
            vault_results=vault_results,
        )

    # ── Link ──

    def link_to_service(
        self,
        identity_id: str,
        service_name: str,
        edge_type: str = "authenticates",
        role: str = "operator",
    ) -> bool:
        """Link an identity to a service in the graph."""
        if not check_identity_permission(role, "link"):
            return False

        identity = self._identities.get(identity_id)
        if not identity:
            return False

        if service_name not in identity.linked_services:
            identity.linked_services.append(service_name)

        self._graph.link_identity_to_service(identity_id, service_name, edge_type)
        self._persist()

        self._audit.record(
            IdentityAction.LINK, identity_id, role,
            target=service_name,
        )
        return True

    def link_to_domain(self, identity_id: str, domain: str, role: str = "operator") -> bool:
        """Link an identity to a domain."""
        if not check_identity_permission(role, "link"):
            return False

        identity = self._identities.get(identity_id)
        if not identity:
            return False

        if domain not in identity.linked_domains:
            identity.linked_domains.append(domain)

        self._graph.link_identity_to_domain(identity_id, domain)
        self._persist()

        self._audit.record(IdentityAction.LINK, identity_id, role, target=domain)
        return True

    # ── Rotate ──

    def rotate_secret(
        self,
        identity_id: str,
        secret_role: str,
        new_value: str,
        role: str = "admin",
    ) -> bool:
        """Rotate a specific secret for an identity."""
        if not check_identity_permission(role, "rotate"):
            return False

        links = self._secret_links.get(identity_id, [])
        for link in links:
            if link.secret_role == secret_role and self._vault:
                ok = self._vault.update_secret(link.secret_id, new_value, role="admin")
                if ok:
                    identity = self._identities.get(identity_id)
                    if identity:
                        identity.last_rotated_at = time.time()
                    self._persist()
                    self._audit.record(
                        IdentityAction.ROTATE, identity_id, role,
                        details=f"rotated {secret_role}",
                    )
                    return True
        return False

    # ── Revoke ──

    def revoke_identity(self, identity_id: str, role: str = "admin") -> bool:
        """Revoke an identity and all its linked secrets."""
        if not check_identity_permission(role, "revoke"):
            return False

        identity = self._identities.get(identity_id)
        if not identity:
            return False

        identity.status = "revoked"
        identity.session_state = "revoked"
        identity.updated_at = time.time()

        # Revoke all linked secrets
        if self._vault:
            for secret_id in identity.linked_secrets:
                try:
                    self._vault.revoke_secret(secret_id, role="admin")
                except Exception:
                    _silent_log.debug("suppressed_exception", src='identity_manager.py')

        self._persist()
        self._audit.record(IdentityAction.REVOKE, identity_id, role)
        return True

    # ── Delete ──

    def delete_identity(self, identity_id: str, role: str = "admin") -> bool:
        """Delete an identity and its vault secrets."""
        if not check_identity_permission(role, "delete"):
            return False

        if identity_id not in self._identities:
            return False

        # Delete vault secrets
        identity = self._identities[identity_id]
        if self._vault:
            for secret_id in identity.linked_secrets:
                try:
                    self._vault.delete_secret(secret_id, role="admin")
                except Exception:
                    _silent_log.debug("suppressed_exception", src='identity_manager.py')

        del self._identities[identity_id]
        self._policies.pop(identity_id, None)
        self._secret_links.pop(identity_id, None)
        self._persist()

        self._audit.record(IdentityAction.DELETE, identity_id, role)
        return True

    # ── Queries ──

    def list_identities(
        self,
        environment: str | None = None,
        provider: str | None = None,
        status: str | None = None,
        role: str = "viewer",
    ) -> list[dict]:
        """List identity metadata (no secrets)."""
        if not check_identity_permission(role, "list"):
            return []

        results = []
        for i in self._identities.values():
            if environment and i.environment != environment:
                continue
            if provider and i.provider != provider:
                continue
            if status and i.status != status:
                continue
            results.append(i.to_dict())
        return results

    def get_identity(self, identity_id: str) -> Identity | None:
        return self._identities.get(identity_id)

    def get_graph(self) -> dict:
        return self._graph.to_dict()

    def get_connections(self, identity_id: str) -> dict:
        return self._graph.get_connections(identity_id)

    def get_rotation_cascade(self, identity_id: str) -> list[str]:
        return self._graph.find_rotation_cascade(identity_id)

    def get_audit_logs(
        self,
        identity_id: str | None = None,
        limit: int = 100,
        role: str = "admin",
    ) -> list[dict]:
        if not check_identity_permission(role, "logs"):
            return []
        return self._audit.query(identity_id=identity_id, limit=limit)

    @property
    def identity_count(self) -> int:
        return len(self._identities)

    # ── Internals ──

    def _infer_secret_type(self, role: str, template: IdentityTemplate | None) -> str:
        """Infer vault secret_type from role name and template."""
        if template:
            for st in template.secret_types:
                if st["role"] == role:
                    return st.get("type", "api_key")

        role_lower = role.lower()
        if "password" in role_lower:
            return "credential"
        if "token" in role_lower:
            return "token"
        if "key" in role_lower and "private" in role_lower:
            return "private_key"
        if "totp" in role_lower:
            return "totp"
        if "cookie" in role_lower:
            return "cookie"
        return "api_key"

    def _persist(self) -> None:
        try:
            data = {}
            for iid, identity in self._identities.items():
                data[iid] = {
                    **identity.to_dict(),
                    "linked_secrets": identity.linked_secrets,
                    "policy": self._policies.get(iid, IdentityPolicy()).to_dict(),
                    "secret_links": [
                        l.to_dict() for l in self._secret_links.get(iid, [])
                    ],
                }
            with open(self._data_dir / "identities.json", "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Identity persist failed: {e}")

    def _load(self) -> None:
        path = self._data_dir / "identities.json"
        if not path.exists():
            return
        try:
            with open(path) as f:
                data = json.load(f)
            for iid, d in data.items():
                self._identities[iid] = Identity(
                    identity_id=iid,
                    identity_type=d.get("type", "api_account"),
                    display_name=d.get("name", ""),
                    provider=d.get("provider", ""),
                    email=d.get("email", ""),
                    username=d.get("username", ""),
                    environment=d.get("environment", "prod"),
                    workspace_id=d.get("workspace", ""),
                    linked_secrets=d.get("linked_secrets", []),
                    linked_domains=d.get("linked_domains", []),
                    linked_services=d.get("linked_services", []),
                    risk_level=d.get("risk_level", "medium"),
                    status=d.get("status", "active"),
                    created_at=d.get("created", 0),
                    last_used_at=d.get("last_used"),
                    last_rotated_at=d.get("last_rotated"),
                )
                if "policy" in d:
                    self._policies[iid] = IdentityPolicy.from_dict(d["policy"])
                for sl in d.get("secret_links", []):
                    self._secret_links.setdefault(iid, []).append(SecretLink(
                        secret_id=sl["secret_id"], secret_role=sl["role"],
                        identity_id=iid, provider=sl.get("provider", ""),
                    ))
                # Add to graph
                self._graph.add_node(
                    iid, "identity", d.get("name", ""),
                    provider=d.get("provider", ""), environment=d.get("environment", ""),
                )
        except Exception as e:
            logger.error(f"Identity load failed: {e}")
