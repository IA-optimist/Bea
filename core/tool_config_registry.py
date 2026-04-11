"""
JARVIS MAX — Tool Config Registry (P8)
==========================================
Makes tool/module dependencies on secrets and configs explicit.

Each module/tool can declare:
  required_secrets: list of vault secret types needed
  required_configs: list of env/config keys needed
  optional_secrets: nice-to-have secrets
  optional_configs: nice-to-have configs

On module install/enable:
  - Validates whether required secrets/configs exist
  - If missing → status becomes "needs_setup"
  - Exposes dependency health via health endpoints

Integrates with:
  - Vault (reference-only, never stores or reads raw secrets)
  - ModuleManager (catalog entries get dependency info)
  - Health endpoints (missing deps surfaced)
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

import structlog

log = structlog.get_logger()


@dataclass
class DependencyDeclaration:
    """What a module/tool needs to function."""
    module_id: str = ""
    module_type: str = ""  # agent, skill, connector, mcp, tool
    required_secrets: List[str] = field(default_factory=list)
    required_configs: List[str] = field(default_factory=list)
    optional_secrets: List[str] = field(default_factory=list)
    optional_configs: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "module_id": self.module_id,
            "module_type": self.module_type,
            "required_secrets": self.required_secrets,
            "required_configs": self.required_configs,
            "optional_secrets": self.optional_secrets,
            "optional_configs": self.optional_configs,
        }


@dataclass
class DependencyStatus:
    """Resolved dependency status for a module."""
    module_id: str = ""
    status: str = "unknown"    # ready | needs_setup | degraded | disabled
    missing_secrets: List[str] = field(default_factory=list)
    missing_configs: List[str] = field(default_factory=list)
    missing_optional_secrets: List[str] = field(default_factory=list)
    missing_optional_configs: List[str] = field(default_factory=list)
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "module_id": self.module_id,
            "status": self.status,
            "missing_secrets": self.missing_secrets,
            "missing_configs": self.missing_configs,
            "missing_optional": self.missing_optional_secrets + self.missing_optional_configs,
            "message": self.message,
        }


class ToolConfigRegistry:
    """
    Central registry of module/tool dependency declarations.
    
    Validates whether required secrets and configs are available.
    Never stores or reads actual secret values — only checks existence.
    """

    def __init__(self, vault=None):
        self._declarations: Dict[str, DependencyDeclaration] = {}
        self._vault = vault  # Optional vault instance for secret checks
        self._lock = threading.RLock()

    def declare(self, decl: DependencyDeclaration) -> None:
        """Register dependency declaration for a module."""
        with self._lock:
            self._declarations[decl.module_id] = decl

    def check(self, module_id: str) -> DependencyStatus:
        """Check if all dependencies for a module are satisfied."""
        decl = self._declarations.get(module_id)
        if not decl:
            return DependencyStatus(module_id=module_id, status="ready",
                                    message="No dependency declarations")

        missing_secrets = []
        missing_configs = []
        missing_opt_secrets = []
        missing_opt_configs = []

        # Check required secrets (via vault reference or env)
        for secret in decl.required_secrets:
            if not self._secret_exists(secret):
                missing_secrets.append(secret)

        # Check required configs (env vars or settings)
        for config in decl.required_configs:
            if not self._config_exists(config):
                missing_configs.append(config)

        # Check optional (non-blocking)
        for secret in decl.optional_secrets:
            if not self._secret_exists(secret):
                missing_opt_secrets.append(secret)

        for config in decl.optional_configs:
            if not self._config_exists(config):
                missing_opt_configs.append(config)

        # Determine status
        if missing_secrets or missing_configs:
            status = "needs_setup"
            parts = []
            if missing_secrets:
                parts.append(f"Missing secrets: {', '.join(missing_secrets)}")
            if missing_configs:
                parts.append(f"Missing configs: {', '.join(missing_configs)}")
            message = ". ".join(parts)
        elif missing_opt_secrets or missing_opt_configs:
            status = "degraded"
            message = "Functional but missing optional dependencies"
        else:
            status = "ready"
            message = "All dependencies satisfied"

        return DependencyStatus(
            module_id=module_id, status=status,
            missing_secrets=missing_secrets, missing_configs=missing_configs,
            missing_optional_secrets=missing_opt_secrets,
            missing_optional_configs=missing_opt_configs,
            message=message,
        )

    def check_all(self) -> Dict[str, Dict[str, Any]]:
        """Check all registered modules."""
        results = {}
        for module_id in self._declarations:
            results[module_id] = self.check(module_id).to_dict()
        return results

    def get_declaration(self, module_id: str) -> Optional[DependencyDeclaration]:
        return self._declarations.get(module_id)

    def should_block_enable(self, module_id: str) -> tuple[bool, str]:
        """Should enabling this module be blocked?"""
        status = self.check(module_id)
        if status.status == "needs_setup":
            return True, status.message
        return False, ""

    def _secret_exists(self, secret_name: str) -> bool:
        """Check if a secret exists (vault or env). Never reads the value."""
        # Check vault first
        if self._vault:
            try:
                # Only check existence, never read value
                if hasattr(self._vault, "has_secret"):
                    return self._vault.has_secret(secret_name)
                if hasattr(self._vault, "list_secrets"):
                    return secret_name in self._vault.list_secrets()
            except Exception:
                _silent_log.debug("suppressed_exception", src='tool_config_registry.py')
        # Fallback: check environment variable
        env_key = secret_name.upper().replace("-", "_").replace(".", "_")
        return bool(os.environ.get(env_key))

    def _config_exists(self, config_name: str) -> bool:
        """Check if a config key exists in environment."""
        env_key = config_name.upper().replace("-", "_").replace(".", "_")
        return bool(os.environ.get(env_key))

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            statuses = {mid: self.check(mid).status for mid in self._declarations}
            return {
                "total_modules": len(self._declarations),
                "ready": sum(1 for s in statuses.values() if s == "ready"),
                "needs_setup": sum(1 for s in statuses.values() if s == "needs_setup"),
                "degraded": sum(1 for s in statuses.values() if s == "degraded"),
            }


# Singleton
_instance: Optional[ToolConfigRegistry] = None
_instance_lock = threading.Lock()


def get_config_registry() -> ToolConfigRegistry:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = ToolConfigRegistry()
    return _instance
