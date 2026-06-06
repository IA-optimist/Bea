"""
JARVIS MAX — Access Token System
===================================
Token-gated access control for multi-user Jarvis.

Roles:
  - admin: full access, can manage tokens
  - user: can submit missions, view history, approve
  - viewer: read-only access to status and history

Token types:
  - permanent: no expiry (for admin)
  - timed: expires after N days
  - limited: expires after N uses

Storage: JSON file (workspace/access_tokens.json)
No external dependencies.
"""
from __future__ import annotations

import structlog
log = structlog.get_logger(__name__)

import hashlib
import json
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PlanLimits:
    """Usage limits for a plan type."""
    missions_per_day: int = 0       # 0 = unlimited
    concurrent_missions: int = 0    # 0 = unlimited
    model_tier: str = "standard"    # basic, standard, premium
    multimodal_enabled: bool = False
    premium_tools_enabled: bool = False

    def to_dict(self) -> dict:
        return {
            "missions_per_day": self.missions_per_day,
            "concurrent_missions": self.concurrent_missions,
            "model_tier": self.model_tier,
            "multimodal_enabled": self.multimodal_enabled,
            "premium_tools_enabled": self.premium_tools_enabled,
        }


# ── Plan definitions (payment-ready) ──
PLAN_DEFINITIONS: dict[str, PlanLimits] = {
    "admin": PlanLimits(
        missions_per_day=0, concurrent_missions=0,
        model_tier="premium", multimodal_enabled=True, premium_tools_enabled=True,
    ),
    "paid_pro": PlanLimits(
        missions_per_day=100, concurrent_missions=5,
        model_tier="premium", multimodal_enabled=True, premium_tools_enabled=True,
    ),
    "paid_basic": PlanLimits(
        missions_per_day=30, concurrent_missions=2,
        model_tier="standard", multimodal_enabled=False, premium_tools_enabled=False,
    ),
    "free_trial": PlanLimits(
        missions_per_day=10, concurrent_missions=1,
        model_tier="basic", multimodal_enabled=False, premium_tools_enabled=False,
    ),
    "custom": PlanLimits(
        missions_per_day=50, concurrent_missions=3,
        model_tier="standard", multimodal_enabled=False, premium_tools_enabled=False,
    ),
}


@dataclass
class AccessToken:
    """A managed access token."""
    id: str = ""
    name: str = ""             # human-readable label ("Max's phone", "Client A")
    token_hash: str = ""       # SHA-256 hash of the actual token (never store raw)
    role: str = "user"         # admin, user, viewer
    plan_type: str = "custom"  # admin, paid_pro, paid_basic, free_trial, custom
    created_at: float = 0
    expires_at: float = 0      # 0 = no expiry
    max_uses: int = 0          # 0 = unlimited
    use_count: int = 0
    last_used: float = 0
    enabled: bool = True
    created_by: str = "admin"
    metadata: dict = field(default_factory=dict)  # client name, notes, etc.
    # Daily usage tracking
    daily_missions: int = 0
    daily_reset_date: str = ""  # YYYY-MM-DD

    @property
    def expired(self) -> bool:
        if self.expires_at > 0 and time.time() > self.expires_at:
            return True
        if self.max_uses > 0 and self.use_count >= self.max_uses:
            return True
        return False

    @property
    def valid(self) -> bool:
        return self.enabled and not self.expired

    @property
    def status_label(self) -> str:
        """Human-friendly status for UI."""
        if not self.enabled:
            return "disabled"
        if self.expired:
            if self.expires_at > 0 and time.time() > self.expires_at:
                return "expired"
            return "revoked"
        return "active"

    @property
    def plan_limits(self) -> PlanLimits:
        return PLAN_DEFINITIONS.get(self.plan_type, PLAN_DEFINITIONS["custom"])

    def check_daily_limit(self) -> bool:
        """Check if daily mission limit is reached. Resets daily."""
        limits = self.plan_limits
        if limits.missions_per_day <= 0:
            return True  # unlimited
        today = time.strftime("%Y-%m-%d")
        if self.daily_reset_date != today:
            self.daily_missions = 0
            self.daily_reset_date = today
        return self.daily_missions < limits.missions_per_day

    def record_mission(self) -> None:
        """Record a mission usage."""
        today = time.strftime("%Y-%m-%d")
        if self.daily_reset_date != today:
            self.daily_missions = 0
            self.daily_reset_date = today
        self.daily_missions += 1

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "plan_type": self.plan_type,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "max_uses": self.max_uses,
            "use_count": self.use_count,
            "last_used": self.last_used,
            "enabled": self.enabled,
            "valid": self.valid,
            "status": self.status_label,
            "created_by": self.created_by,
            "metadata": self.metadata,
            "plan_limits": self.plan_limits.to_dict(),
            "daily_missions": self.daily_missions,
        }


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


class TokenManager:
    """
    Manages access tokens for Jarvis.

    Tokens are stored as hashes — the raw token is only returned
    once at creation time and never stored.
    """

    def __init__(self, persist_path: Path | None = None):
        self._path = persist_path or Path("workspace/access_tokens.json")
        self._tokens: dict[str, AccessToken] = {}
        self._hash_index: dict[str, str] = {}  # token_hash → token_id
        self._load()

    def create_token(self, name: str, role: str = "user",
                     plan_type: str = "custom",
                     expires_days: int = 0, max_uses: int = 0,
                     created_by: str = "admin",
                     metadata: dict | None = None) -> tuple[str, AccessToken]:
        """
        Create a new access token.

        Returns (raw_token, AccessToken).
        The raw_token is returned ONCE and never stored.
        """
        if role not in ("admin", "user", "viewer"):
            raise ValueError(f"Invalid role: {role}. Must be admin, user, or viewer.")
        if plan_type not in PLAN_DEFINITIONS:
            raise ValueError(f"Invalid plan_type: {plan_type}. Must be one of: {list(PLAN_DEFINITIONS.keys())}")

        raw_token = f"jv-{secrets.token_urlsafe(32)}"
        token_hash = _hash_token(raw_token)
        token_id = f"tok-{secrets.token_hex(6)}"

        expires_at = 0
        if expires_days > 0:
            expires_at = time.time() + (expires_days * 86400)

        token = AccessToken(
            id=token_id,
            name=name,
            token_hash=token_hash,
            role=role,
            plan_type=plan_type,
            created_at=time.time(),
            expires_at=expires_at,
            max_uses=max_uses,
            created_by=created_by,
            metadata=metadata or {},
        )

        self._tokens[token_id] = token
        self._hash_index[token_hash] = token_id
        self._save()

        return raw_token, token

    def validate_token(self, raw_token: str) -> AccessToken | None:
        """
        Validate a raw token string.

        Returns the AccessToken if valid, None if invalid/expired/disabled.
        Increments use_count on successful validation.
        """
        if not raw_token:
            return None

        token_hash = _hash_token(raw_token)
        token_id = self._hash_index.get(token_hash)
        if not token_id:
            return None

        token = self._tokens.get(token_id)
        if not token or not token.valid:
            return None

        # Record usage
        token.use_count += 1
        token.last_used = time.time()
        self._save()

        return token

    def revoke_token(self, token_id: str) -> bool:
        """Disable a token by ID."""
        token = self._tokens.get(token_id)
        if token:
            token.enabled = False
            self._save()
            return True
        return False

    def enable_token(self, token_id: str) -> bool:
        """Re-enable a revoked token."""
        token = self._tokens.get(token_id)
        if token:
            token.enabled = True
            self._save()
            return True
        return False

    def delete_token(self, token_id: str) -> bool:
        """Permanently delete a token."""
        token = self._tokens.pop(token_id, None)
        if token:
            self._hash_index.pop(token.token_hash, None)
            self._save()
            return True
        return False

    def list_tokens(self, include_expired: bool = False) -> list[dict]:
        """List all tokens (never includes the raw token or hash)."""
        result = []
        for t in self._tokens.values():
            if not include_expired and t.expired:
                continue
            result.append(t.to_dict())
        return result

    def get_token_by_id(self, token_id: str) -> AccessToken | None:
        return self._tokens.get(token_id)

    def get_stats(self) -> dict:
        """Token system stats."""
        all_tokens = list(self._tokens.values())
        return {
            "total": len(all_tokens),
            "active": sum(1 for t in all_tokens if t.valid),
            "expired": sum(1 for t in all_tokens if t.expired),
            "disabled": sum(1 for t in all_tokens if not t.enabled),
            "by_role": {
                "admin": sum(1 for t in all_tokens if t.role == "admin" and t.valid),
                "user": sum(1 for t in all_tokens if t.role == "user" and t.valid),
                "viewer": sum(1 for t in all_tokens if t.role == "viewer" and t.valid),
            },
        }

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = {}
            for tid, t in self._tokens.items():
                data[tid] = {
                    **t.to_dict(),
                    "token_hash": t.token_hash,
                }
            self._path.write_text(
                json.dumps(data, indent=2, default=str), encoding="utf-8")
        except Exception as _exc:
            log.warning("swallowed_exception", action="access_tokens_1", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            for tid, td in data.items():
                token = AccessToken(
                    id=td.get("id", tid),
                    name=td.get("name", ""),
                    token_hash=td.get("token_hash", ""),
                    role=td.get("role", "user"),
                    plan_type=td.get("plan_type", "custom"),
                    created_at=td.get("created_at", 0),
                    expires_at=td.get("expires_at", 0),
                    max_uses=td.get("max_uses", 0),
                    use_count=td.get("use_count", 0),
                    last_used=td.get("last_used", 0),
                    enabled=td.get("enabled", True),
                    created_by=td.get("created_by", "admin"),
                    metadata=td.get("metadata", {}),
                    daily_missions=td.get("daily_missions", 0),
                    daily_reset_date=td.get("daily_reset_date", ""),
                )
                self._tokens[tid] = token
                if token.token_hash:
                    self._hash_index[token.token_hash] = tid
        except Exception as _exc:
            log.warning("swallowed_exception", action="access_tokens_2", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])


# ── Singleton ──
_manager: TokenManager | None = None


def get_token_manager(persist_path: Path | None = None) -> TokenManager:
    global _manager
    if _manager is None:
        _manager = TokenManager(persist_path)
    return _manager


def reset_token_manager() -> None:
    """Reset singleton (for tests)."""
    global _manager
    _manager = None
