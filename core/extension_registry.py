"""
JARVIS MAX — Extension Registry
==================================
Production-grade extensibility layer for user-managed Agents, MCP Connectors,
Skills, and Tools.

Architecture:
  - Core items: read-only, protected, loaded from code
  - User extensions: stored in JSON, schema-validated, admin-managed
  - Runtime merge: core + enabled user extensions
  - Fail-open isolation: bad extension never crashes system

Security:
  - Schema validation on every write
  - Secrets masked after creation (stored hashed)
  - Audit trail for all mutations
  - Admin-only write access (enforced at API layer)
  - Core items cannot be overwritten by user extensions
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any
_silent_log = __import__("structlog").get_logger(__name__)

try:
    import structlog
    log = structlog.get_logger(__name__)
except ImportError:
    import logging
    log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# PART 1 — DATA MODELS
# ═══════════════════════════════════════════════════════════════

class ExtensionSource(str, Enum):
    CORE = "core"
    USER = "user"


class HealthStatus(str, Enum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    UNTESTED = "untested"


# --- Validation helpers ---

_ID_RE = re.compile(r'^[a-z0-9][a-z0-9_-]{1,62}[a-z0-9]$')
_DANGEROUS_PATTERNS = [
    "rm -rf", "sudo", "eval(", "exec(", "__import__",
    "os.system", "subprocess.call", "subprocess.Popen",
    "shutil.rmtree", "; rm ", "| rm ", "&& rm ",
]


def _validate_id(ext_id: str) -> str | None:
    if not _ID_RE.match(ext_id):
        return "ID must be 3-64 chars, lowercase alphanumeric with hyphens/underscores"
    return None


def _check_dangerous(text: str) -> str | None:
    lower = text.lower()
    for pattern in _DANGEROUS_PATTERNS:
        if pattern.lower() in lower:
            return f"Dangerous pattern detected: '{pattern}'"
    return None


def _mask_secret(secret: str) -> str:
    if not secret or len(secret) < 8:
        return "***"
    return secret[:4] + "***" + secret[-2:]


def _hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


# --- Base Extension ---

@dataclass
class BaseExtension:
    id: str = ""
    name: str = ""
    description: str = ""
    enabled: bool = False
    source: str = ExtensionSource.USER
    health_status: str = HealthStatus.UNTESTED
    created_at: float = 0.0
    updated_at: float = 0.0
    created_by: str = ""

    def to_dict(self) -> dict:
        d = {}
        for k, v in self.__dict__.items():
            if not k.startswith("_"):
                d[k] = v
        return d

    def to_safe_dict(self) -> dict:
        """Dict with secrets masked."""
        return self.to_dict()


# --- A. CustomAgent ---

@dataclass
class CustomAgent(BaseExtension):
    role: str = ""
    model_id: str = ""
    system_prompt: str = ""
    capabilities: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    allowed_skills: list[str] = field(default_factory=list)
    risk_level: str = "low"  # low, medium, high

    def validate(self) -> list[str]:
        errors = []
        id_err = _validate_id(self.id) if self.id else None
        if id_err:
            errors.append(id_err)
        if not self.name or len(self.name) < 2:
            errors.append("Name required (min 2 chars)")
        if not self.role:
            errors.append("Role required")
        if self.risk_level not in ("low", "medium", "high"):
            errors.append("Risk level must be low, medium, or high")
        if self.system_prompt:
            danger = _check_dangerous(self.system_prompt)
            if danger:
                errors.append(danger)
        return errors


# --- B. CustomMCPConnector ---

@dataclass
class CustomMCPConnector(BaseExtension):
    connector_type: str = ""  # stdio, http, streamable-http
    endpoint: str = ""
    command: str = ""
    auth_type: str = "none"  # none, bearer, api_key, basic
    secret_ref: str = ""        # stored hashed
    _raw_secret: str = ""       # transient, never persisted
    timeout_s: int = 30
    permissions: list[str] = field(default_factory=list)
    last_test_at: float = 0.0

    def validate(self) -> list[str]:
        errors = []
        id_err = _validate_id(self.id) if self.id else None
        if id_err:
            errors.append(id_err)
        if not self.name or len(self.name) < 2:
            errors.append("Name required (min 2 chars)")
        if not self.connector_type:
            errors.append("Connector type required")
        if self.connector_type == "stdio" and not self.command:
            errors.append("Command required for stdio connector")
        if self.connector_type in ("http", "streamable-http") and not self.endpoint:
            errors.append("Endpoint required for HTTP connector")
        if self.endpoint and not self.endpoint.startswith(("http://", "https://")):
            errors.append("Endpoint must start with http:// or https://")
        if self.command:
            danger = _check_dangerous(self.command)
            if danger:
                errors.append(danger)
        if self.timeout_s < 1 or self.timeout_s > 300:
            errors.append("Timeout must be 1-300 seconds")
        return errors

    def to_safe_dict(self) -> dict:
        d = self.to_dict()
        if d.get("secret_ref"):
            d["secret_ref"] = _mask_secret(d["secret_ref"][:10]) if len(d["secret_ref"]) < 64 else "***hashed***"
        d.pop("_raw_secret", None)
        return d


# --- C. CustomSkill ---

@dataclass
class CustomSkill(BaseExtension):
    category: str = ""
    input_schema: dict = field(default_factory=dict)
    output_schema: dict = field(default_factory=dict)
    execution_type: str = "prompt"  # prompt, function, chain
    prompt_template: str = ""
    config: dict = field(default_factory=dict)
    test_status: str = "untested"

    def validate(self) -> list[str]:
        errors = []
        id_err = _validate_id(self.id) if self.id else None
        if id_err:
            errors.append(id_err)
        if not self.name or len(self.name) < 2:
            errors.append("Name required (min 2 chars)")
        if self.execution_type not in ("prompt", "function", "chain"):
            errors.append("Execution type must be prompt, function, or chain")
        if self.prompt_template:
            danger = _check_dangerous(self.prompt_template)
            if danger:
                errors.append(danger)
        return errors


# --- D. CustomToolConfig ---

@dataclass
class CustomToolConfig(BaseExtension):
    tool_type: str = ""  # mcp, internal, wrapper
    config: dict = field(default_factory=dict)
    validation_status: str = "unvalidated"

    def validate(self) -> list[str]:
        errors = []
        id_err = _validate_id(self.id) if self.id else None
        if id_err:
            errors.append(id_err)
        if not self.name or len(self.name) < 2:
            errors.append("Name required (min 2 chars)")
        if not self.tool_type:
            errors.append("Tool type required")
        if self.tool_type not in ("mcp", "internal", "wrapper"):
            errors.append("Tool type must be mcp, internal, or wrapper")
        # Check config for dangerous values
        config_str = json.dumps(self.config)
        danger = _check_dangerous(config_str)
        if danger:
            errors.append(danger)
        return errors


# ═══════════════════════════════════════════════════════════════
# PART 2 — REGISTRY / STORAGE LAYER
# ═══════════════════════════════════════════════════════════════

@dataclass
class AuditEntry:
    action: str           # create, update, enable, disable, delete, test
    extension_type: str   # agent, mcp, skill, tool
    extension_id: str
    actor: str
    details: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "action": self.action, "type": self.extension_type,
            "id": self.extension_id, "actor": self.actor,
            "details": self.details[:200], "timestamp": self.timestamp,
        }


# Type map for deserialization
_TYPE_MAP = {
    "agent": CustomAgent,
    "mcp": CustomMCPConnector,
    "skill": CustomSkill,
    "tool": CustomToolConfig,
}


class ExtensionRegistry:
    """
    Manages user-added extensions with schema validation, audit trail,
    and safe runtime merging with core items.

    Storage: JSON file per extension type in workspace/extensions/
    Core items: loaded from code, read-only, protected
    """

    def __init__(self, storage_dir: Path | None = None):
        self._dir = storage_dir or Path("workspace/extensions")
        self._dir.mkdir(parents=True, exist_ok=True)

        # Separate stores per type
        self._stores: dict[str, dict[str, BaseExtension]] = {
            "agent": {}, "mcp": {}, "skill": {}, "tool": {},
        }
        # Core IDs (protected, cannot be overwritten)
        self._core_ids: dict[str, set[str]] = {
            "agent": set(), "mcp": set(), "skill": set(), "tool": set(),
        }
        # Audit log
        self._audit: list[AuditEntry] = []

        self._load_all()

    # --- Core registration (called at startup) ---

    def register_core_id(self, ext_type: str, ext_id: str) -> None:
        """Mark an ID as core-protected."""
        if ext_type in self._core_ids:
            self._core_ids[ext_type].add(ext_id)

    def is_core(self, ext_type: str, ext_id: str) -> bool:
        return ext_id in self._core_ids.get(ext_type, set())

    # --- CRUD ---

    def create(self, ext_type: str, data: dict, actor: str = "admin") -> dict:
        """Create a new extension. Returns result dict."""
        cls = _TYPE_MAP.get(ext_type)
        if not cls:
            return {"ok": False, "error": f"Unknown type: {ext_type}"}

        # Build object
        now = time.time()
        ext_id = data.get("id") or f"{ext_type}-{uuid.uuid4().hex[:8]}"
        data["id"] = ext_id
        data["source"] = ExtensionSource.USER
        data["created_at"] = now
        data["updated_at"] = now
        data["created_by"] = actor

        # Handle MCP secrets
        raw_secret = ""
        if ext_type == "mcp" and data.get("_raw_secret"):
            raw_secret = data.pop("_raw_secret")
            data["secret_ref"] = _hash_secret(raw_secret)

        # Instantiate
        try:
            # Filter to only known fields
            valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
            filtered = {k: v for k, v in data.items() if k in valid_fields}
            ext = cls(**filtered)
        except Exception as e:
            return {"ok": False, "error": f"Invalid data: {e}"}

        # Validate
        errors = ext.validate()
        if errors:
            return {"ok": False, "errors": errors}

        # Check duplicates
        if ext_id in self._stores[ext_type]:
            return {"ok": False, "error": f"ID '{ext_id}' already exists"}

        # Check core protection
        if self.is_core(ext_type, ext_id):
            return {"ok": False, "error": f"ID '{ext_id}' is a protected core item"}

        # Store
        self._stores[ext_type][ext_id] = ext
        self._audit_log("create", ext_type, ext_id, actor)
        self._save(ext_type)

        return {"ok": True, "id": ext_id, "extension": ext.to_safe_dict()}

    def update(self, ext_type: str, ext_id: str, data: dict, actor: str = "admin") -> dict:
        """Update an existing extension."""
        if ext_type not in self._stores:
            return {"ok": False, "error": f"Unknown type: {ext_type}"}

        ext = self._stores[ext_type].get(ext_id)
        if not ext:
            return {"ok": False, "error": f"Not found: {ext_id}"}

        if ext.source == ExtensionSource.CORE:
            return {"ok": False, "error": "Cannot modify core extension"}

        # Apply updates (skip protected fields)
        protected = {"id", "source", "created_at", "created_by"}
        for key, val in data.items():
            if key in protected or key.startswith("_"):
                continue
            if hasattr(ext, key):
                setattr(ext, key, val)

        ext.updated_at = time.time()

        # Handle MCP secret update
        if ext_type == "mcp" and data.get("_raw_secret"):
            ext.secret_ref = _hash_secret(data["_raw_secret"])

        # Re-validate
        errors = ext.validate()
        if errors:
            return {"ok": False, "errors": errors}

        self._audit_log("update", ext_type, ext_id, actor, str(list(data.keys())))
        self._save(ext_type)
        return {"ok": True, "extension": ext.to_safe_dict()}

    def delete(self, ext_type: str, ext_id: str, actor: str = "admin") -> dict:
        """Delete a user extension."""
        if ext_type not in self._stores:
            return {"ok": False, "error": f"Unknown type: {ext_type}"}

        ext = self._stores[ext_type].get(ext_id)
        if not ext:
            return {"ok": False, "error": f"Not found: {ext_id}"}

        if ext.source == ExtensionSource.CORE:
            return {"ok": False, "error": "Cannot delete core extension"}

        del self._stores[ext_type][ext_id]
        self._audit_log("delete", ext_type, ext_id, actor)
        self._save(ext_type)
        return {"ok": True, "deleted": ext_id}

    def enable(self, ext_type: str, ext_id: str, actor: str = "admin") -> dict:
        """Enable an extension (only if valid)."""
        ext = self._stores.get(ext_type, {}).get(ext_id)
        if not ext:
            return {"ok": False, "error": f"Not found: {ext_id}"}

        errors = ext.validate()
        if errors:
            return {"ok": False, "error": "Cannot enable invalid extension", "errors": errors}

        ext.enabled = True
        ext.updated_at = time.time()
        self._audit_log("enable", ext_type, ext_id, actor)
        self._save(ext_type)
        return {"ok": True, "enabled": True}

    def disable(self, ext_type: str, ext_id: str, actor: str = "admin") -> dict:
        """Disable an extension instantly."""
        ext = self._stores.get(ext_type, {}).get(ext_id)
        if not ext:
            return {"ok": False, "error": f"Not found: {ext_id}"}

        ext.enabled = False
        ext.updated_at = time.time()
        self._audit_log("disable", ext_type, ext_id, actor)
        self._save(ext_type)
        return {"ok": True, "enabled": False}

    def test(self, ext_type: str, ext_id: str, actor: str = "admin") -> dict:
        """Test an extension safely."""
        ext = self._stores.get(ext_type, {}).get(ext_id)
        if not ext:
            return {"ok": False, "error": f"Not found: {ext_id}"}

        # Validate schema first
        errors = ext.validate()
        if errors:
            ext.health_status = HealthStatus.FAILED
            self._save(ext_type)
            return {"ok": False, "status": "failed", "errors": errors}

        # Type-specific tests
        test_result = self._run_test(ext_type, ext)

        ext.health_status = HealthStatus.HEALTHY if test_result["passed"] else HealthStatus.FAILED
        if ext_type == "mcp":
            ext.last_test_at = time.time()
        if ext_type == "skill":
            ext.test_status = "passed" if test_result["passed"] else "failed"
        if ext_type == "tool":
            ext.validation_status = "valid" if test_result["passed"] else "invalid"

        ext.updated_at = time.time()
        self._audit_log("test", ext_type, ext_id, actor, test_result.get("detail", ""))
        self._save(ext_type)
        return {"ok": True, **test_result}

    def _run_test(self, ext_type: str, ext: BaseExtension) -> dict:
        """Run type-specific validation test."""
        try:
            if ext_type == "agent":
                # Validate agent can be instantiated
                agent = ext  # type: CustomAgent
                if not agent.role or not agent.name:
                    return {"passed": False, "detail": "Missing role or name"}
                return {"passed": True, "detail": "Schema valid, agent config OK"}

            elif ext_type == "mcp":
                conn = ext  # type: CustomMCPConnector
                if conn.connector_type in ("http", "streamable-http"):
                    # Validate URL format
                    if not conn.endpoint.startswith("https://"):
                        return {"passed": True, "detail": "Warning: non-HTTPS endpoint",
                                "warnings": ["Non-HTTPS endpoint"]}
                    return {"passed": True, "detail": "Endpoint format valid"}
                elif conn.connector_type == "stdio":
                    return {"passed": True, "detail": "Command config valid"}
                return {"passed": False, "detail": f"Unknown connector type: {conn.connector_type}"}

            elif ext_type == "skill":
                skill = ext  # type: CustomSkill
                if skill.execution_type == "prompt" and not skill.prompt_template:
                    return {"passed": False, "detail": "Prompt template required for prompt-type skill"}
                return {"passed": True, "detail": "Skill config valid"}

            elif ext_type == "tool":
                tool = ext  # type: CustomToolConfig
                if tool.tool_type == "mcp" and not tool.config.get("server"):
                    return {"passed": False, "detail": "MCP tool needs 'server' in config"}
                return {"passed": True, "detail": "Tool config valid"}

            return {"passed": False, "detail": "Unknown extension type"}
        except Exception as e:
            return {"passed": False, "detail": f"Test error: {str(e)[:100]}"}

    # --- Query ---

    def list_all(self, ext_type: str, include_core: bool = False) -> list[dict]:
        """List all extensions of a type."""
        items = []
        for ext in self._stores.get(ext_type, {}).values():
            if not include_core and ext.source == ExtensionSource.CORE:
                continue
            items.append(ext.to_safe_dict())
        return items

    def get(self, ext_type: str, ext_id: str) -> dict | None:
        ext = self._stores.get(ext_type, {}).get(ext_id)
        return ext.to_safe_dict() if ext else None

    def get_enabled(self, ext_type: str) -> list[dict]:
        """Get only enabled extensions (for runtime consumption)."""
        return [ext.to_safe_dict() for ext in self._stores.get(ext_type, {}).values()
                if ext.enabled]

    def get_audit(self, limit: int = 50) -> list[dict]:
        return [a.to_dict() for a in self._audit[-limit:]]

    def health_summary(self) -> dict:
        summary = {}
        for ext_type, store in self._stores.items():
            total = len([e for e in store.values() if e.source == ExtensionSource.USER])
            enabled = len([e for e in store.values() if e.source == ExtensionSource.USER and e.enabled])
            healthy = len([e for e in store.values() if e.health_status == HealthStatus.HEALTHY])
            failed = len([e for e in store.values() if e.health_status == HealthStatus.FAILED])
            summary[ext_type] = {
                "total": total, "enabled": enabled,
                "healthy": healthy, "failed": failed,
            }
        return summary

    # --- Audit ---

    def _audit_log(self, action: str, ext_type: str, ext_id: str,
                   actor: str, details: str = "") -> None:
        entry = AuditEntry(
            action=action, extension_type=ext_type,
            extension_id=ext_id, actor=actor, details=details,
        )
        self._audit.append(entry)
        if len(self._audit) > 2000:
            self._audit = self._audit[-1000:]
        # Persist audit
        self._save_audit()

    # --- Persistence ---

    def _save(self, ext_type: str) -> None:
        try:
            path = self._dir / f"{ext_type}s.json"
            items = []
            for ext in self._stores[ext_type].values():
                if ext.source == ExtensionSource.USER:
                    d = ext.to_dict()
                    d.pop("_raw_secret", None)
                    items.append(d)
            path.write_text(json.dumps(items, indent=2, default=str), encoding="utf-8")
        except Exception as e:
            log.debug("extension_save_failed", type=ext_type, err=str(e)[:80])

    def _save_audit(self) -> None:
        try:
            path = self._dir / "audit.json"
            path.write_text(
                json.dumps([a.to_dict() for a in self._audit[-500:]], indent=2, default=str),
                encoding="utf-8")
        except Exception:
            _silent_log.debug("suppressed_exception", src='extension_registry.py')

    def _load_all(self) -> None:
        for ext_type, cls in _TYPE_MAP.items():
            path = self._dir / f"{ext_type}s.json"
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    for item in data:
                        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
                        filtered = {k: v for k, v in item.items()
                                    if k in valid_fields and not k.startswith("_")}
                        ext = cls(**filtered)
                        self._stores[ext_type][ext.id] = ext
                except Exception as e:
                    log.debug("extension_load_failed", type=ext_type, err=str(e)[:80])

        # Load audit
        audit_path = self._dir / "audit.json"
        if audit_path.exists():
            try:
                data = json.loads(audit_path.read_text(encoding="utf-8"))
                for d in data:
                    self._audit.append(AuditEntry(**d))
            except Exception:
                _silent_log.debug("suppressed_exception", src='extension_registry.py')


# ═══════════════════════════════════════════════════════════════
# PART 7 — RUNTIME INTEGRATION
# ═══════════════════════════════════════════════════════════════

class RuntimeExtensionLoader:
    """
    Loads enabled user extensions into the runtime safely.
    Bad extensions fail isolated — never crash the system.
    """

    def __init__(self, registry: ExtensionRegistry):
        self._registry = registry
        self._loaded: dict[str, list[str]] = {
            "agent": [], "mcp": [], "skill": [], "tool": [],
        }

    def load_all(self) -> dict:
        """Load all enabled extensions into runtime. Returns summary."""
        results = {}
        for ext_type in ("agent", "mcp", "skill", "tool"):
            loaded, failed = self._load_type(ext_type)
            results[ext_type] = {"loaded": loaded, "failed": failed}
            self._loaded[ext_type] = loaded
        return results

    def _load_type(self, ext_type: str) -> tuple[list[str], list[str]]:
        loaded = []
        failed = []
        for ext_dict in self._registry.get_enabled(ext_type):
            ext_id = ext_dict.get("id", "unknown")
            try:
                self._activate(ext_type, ext_dict)
                loaded.append(ext_id)
            except Exception as e:
                failed.append(ext_id)
                log.debug("extension_load_failed", type=ext_type, id=ext_id, err=str(e)[:80])
        return loaded, failed

    def _activate(self, ext_type: str, ext_dict: dict) -> None:
        """Activate an extension in the runtime. Type-specific logic."""
        if ext_type == "agent":
            # Register in agent routing
            try:
                from agents.registry import get_registry
                reg = get_registry()
                if hasattr(reg, "register_external"):
                    reg.register_external(ext_dict)
            except Exception:
                pass  # Agent registry not available

        elif ext_type == "mcp":
            # Register MCP connector
            try:
                from core.connectors import get_connector_registry
                creg = get_connector_registry()
                if hasattr(creg, "register_external"):
                    creg.register_external(ext_dict)
            except Exception:
                _silent_log.debug("suppressed_exception", src='extension_registry.py')

        elif ext_type == "skill":
            # Register skill
            try:
                from core.skills import get_skill_registry
                sreg = get_skill_registry()
                if hasattr(sreg, "register_external"):
                    sreg.register_external(ext_dict)
            except Exception:
                _silent_log.debug("suppressed_exception", src='extension_registry.py')

        elif ext_type == "tool":
            # Register tool config
            try:
                from core.tools import get_tool_registry
                treg = get_tool_registry()
                if hasattr(treg, "register_external"):
                    treg.register_external(ext_dict)
            except Exception:
                _silent_log.debug("suppressed_exception", src='extension_registry.py')

    def get_loaded(self) -> dict:
        return dict(self._loaded)


# Singleton
_registry: ExtensionRegistry | None = None


def get_extension_registry(storage_dir: Path | None = None) -> ExtensionRegistry:
    global _registry
    if _registry is None:
        _registry = ExtensionRegistry(storage_dir)
    return _registry


def reset_registry() -> None:
    """For testing only."""
    global _registry
    _registry = None
