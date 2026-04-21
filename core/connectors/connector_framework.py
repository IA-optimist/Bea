"""
core/connectors/connector_framework.py — Plug-and-play connector framework.

Wraps existing connectors.py with a clean discovery/lifecycle API.
Adds connect(), execute(), validate(), log() protocol.
Groups connectors by domain for the AI OS layer.

Does NOT replace core/connectors.py — extends it with framework interface.
"""
from __future__ import annotations

import time
import structlog
from dataclasses import dataclass
from typing import Optional, Callable
from enum import Enum

log = structlog.get_logger("jarvis.connector_framework")


# ── Connector Domain ─────────────────────────────────────────────────────────

class ConnectorDomain(str, Enum):
    FILESYSTEM = "filesystem"
    NETWORK = "network"
    GITHUB = "github"
    DOCKER = "docker"
    BROWSER = "browser"
    COMMUNICATION = "communication"
    CALENDAR = "calendar"
    API = "api"
    DATA = "data"
    WORKFLOW = "workflow"


# ── Connector Protocol ───────────────────────────────────────────────────────

@dataclass
class ConnectorHealth:
    """Health status of a connector."""
    name: str
    domain: ConnectorDomain
    connected: bool = False
    last_check: float = 0
    error: str = ""
    latency_ms: float = 0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "domain": self.domain.value,
            "connected": self.connected,
            "last_check": self.last_check,
            "error": self.error[:100],
            "latency_ms": round(self.latency_ms, 1),
        }


@dataclass
class ConnectorEntry:
    """A registered connector with its metadata."""
    name: str
    domain: ConnectorDomain
    description: str
    execute_fn: Optional[Callable] = None
    validate_fn: Optional[Callable] = None
    connect_fn: Optional[Callable] = None
    risk_level: str = "low"
    requires_approval: bool = False
    enabled: bool = True
    # Performance tracking
    total_calls: int = 0
    total_success: int = 0
    total_latency_ms: float = 0
    last_error: str = ""

    @property
    def success_rate(self) -> float:
        return self.total_success / self.total_calls if self.total_calls else 1.0

    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms / self.total_calls if self.total_calls else 0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "domain": self.domain.value,
            "description": self.description[:100],
            "risk_level": self.risk_level,
            "requires_approval": self.requires_approval,
            "enabled": self.enabled,
            "total_calls": self.total_calls,
            "success_rate": round(self.success_rate, 3),
            "avg_latency_ms": round(self.avg_latency_ms, 1),
        }


# ── Connector Framework ─────────────────────────────────────────────────────

# Map existing connectors to domains
_CONNECTOR_DOMAINS: dict[str, ConnectorDomain] = {
    "http_request": ConnectorDomain.NETWORK,
    "web_search": ConnectorDomain.BROWSER,
    "web_scrape": ConnectorDomain.BROWSER,
    "json_storage": ConnectorDomain.DATA,
    "document_writer": ConnectorDomain.FILESYSTEM,
    "structured_extractor": ConnectorDomain.DATA,
    "task_list": ConnectorDomain.WORKFLOW,
    "email": ConnectorDomain.COMMUNICATION,
    "messaging": ConnectorDomain.COMMUNICATION,
    "webhook": ConnectorDomain.API,
    "api_connector": ConnectorDomain.API,
    "lead_manager": ConnectorDomain.DATA,
    "content_manager": ConnectorDomain.DATA,
    "budget_tracker": ConnectorDomain.DATA,
    "workflow_trigger": ConnectorDomain.WORKFLOW,
    "scheduler": ConnectorDomain.CALENDAR,
    "file_export": ConnectorDomain.FILESYSTEM,
}


class ConnectorFramework:
    """Plug-and-play connector management with lifecycle protocol."""

    def __init__(self):
        self._connectors: dict[str, ConnectorEntry] = {}
        self._health_cache: dict[str, ConnectorHealth] = {}
        self._init_from_registry()

    def _init_from_registry(self):
        """Bootstrap from existing CONNECTOR_REGISTRY."""
        try:
            from core.connectors import CONNECTOR_REGISTRY
            for name, entry in CONNECTOR_REGISTRY.items():
                spec = entry.get("spec")
                exec_fn = entry.get("execute")
                domain = _CONNECTOR_DOMAINS.get(name, ConnectorDomain.API)
                self._connectors[name] = ConnectorEntry(
                    name=name,
                    domain=domain,
                    description=spec.description if spec else "",
                    execute_fn=exec_fn,
                    risk_level=spec.risk_level if spec else "low",
                    requires_approval=spec.requires_approval if spec else False,
                )
            log.info("connectors_loaded", count=len(self._connectors))
        except Exception as e:
            log.warning("connector_init_failed", err=str(e)[:80])

    # ── Lifecycle Protocol ───────────────────────────────────────

    def connect(self, name: str) -> ConnectorHealth:
        """Test connectivity for a connector."""
        entry = self._connectors.get(name)
        if not entry:
            return ConnectorHealth(name=name, domain=ConnectorDomain.API,
                                   error=f"Unknown connector: {name}")
        start = time.time()
        health = ConnectorHealth(name=name, domain=entry.domain)
        try:
            if entry.connect_fn:
                entry.connect_fn()
            health.connected = True
            health.latency_ms = (time.time() - start) * 1000
        except Exception as e:
            health.error = str(e)[:100]
        health.last_check = time.time()
        self._health_cache[name] = health
        return health

    def execute(self, name: str, params: dict) -> dict:
        """Execute a connector with standard protocol."""
        entry = self._connectors.get(name)
        if not entry:
            return {"ok": False, "error": f"Unknown connector: {name}"}
        if not entry.enabled:
            return {"ok": False, "error": f"Connector disabled: {name}"}
        if not entry.execute_fn:
            return {"ok": False, "error": f"No execute function: {name}"}

        start = time.time()
        try:
            result = entry.execute_fn(params)
            latency = (time.time() - start) * 1000
            entry.total_calls += 1
            entry.total_latency_ms += latency

            # Normalize result
            if hasattr(result, 'to_dict'):
                result_dict = result.to_dict()
            elif isinstance(result, dict):
                result_dict = result
            else:
                result_dict = {"ok": True, "data": str(result)}

            success = result_dict.get("ok", result_dict.get("success", False))
            if success:
                entry.total_success += 1

            result_dict["_connector"] = {
                "name": name,
                "domain": entry.domain.value,
                "latency_ms": round(latency, 1),
            }
            log.debug("connector_executed", name=name, success=success,
                      latency=round(latency, 1))
            return result_dict

        except Exception as e:
            latency = (time.time() - start) * 1000
            entry.total_calls += 1
            entry.total_latency_ms += latency
            entry.last_error = str(e)[:200]
            log.warning("connector_execute_failed", name=name, err=str(e)[:60])
            return {"ok": False, "error": str(e)[:200],
                    "_connector": {"name": name, "domain": entry.domain.value}}

    def validate(self, name: str, params: dict) -> tuple[bool, str]:
        """Validate parameters before execution."""
        entry = self._connectors.get(name)
        if not entry:
            return False, f"Unknown connector: {name}"
        if not entry.enabled:
            return False, f"Connector disabled: {name}"
        if entry.validate_fn:
            try:
                return entry.validate_fn(params)
            except Exception as e:
                return False, str(e)[:100]
        return True, "OK"

    # ── Registry Operations ──────────────────────────────────────

    def register(self, name: str, domain: ConnectorDomain,
                 description: str = "",
                 execute_fn: Callable | None = None,
                 validate_fn: Callable | None = None,
                 connect_fn: Callable | None = None,
                 risk_level: str = "low",
                 requires_approval: bool = False) -> None:
        """Register a new connector."""
        self._connectors[name] = ConnectorEntry(
            name=name, domain=domain, description=description,
            execute_fn=execute_fn, validate_fn=validate_fn,
            connect_fn=connect_fn, risk_level=risk_level,
            requires_approval=requires_approval,
        )
        log.info("connector_registered", name=name, domain=domain.value)

    def disable(self, name: str) -> bool:
        entry = self._connectors.get(name)
        if entry:
            entry.enabled = False
            return True
        return False

    def enable(self, name: str) -> bool:
        entry = self._connectors.get(name)
        if entry:
            entry.enabled = True
            return True
        return False

    def list_connectors(self, domain: str = "", enabled_only: bool = False) -> list[dict]:
        entries = list(self._connectors.values())
        if domain:
            entries = [e for e in entries if e.domain.value == domain]
        if enabled_only:
            entries = [e for e in entries if e.enabled]
        return [e.to_dict() for e in entries]

    def get_health(self) -> list[dict]:
        return [h.to_dict() for h in self._health_cache.values()]

    def by_domain(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for e in self._connectors.values():
            d = e.domain.value
            if d not in result:
                result[d] = []
            result[d].append(e.name)
        return result

    def stats(self) -> dict:
        entries = list(self._connectors.values())
        total_calls = sum(e.total_calls for e in entries)
        total_success = sum(e.total_success for e in entries)
        return {
            "total_connectors": len(entries),
            "enabled": sum(1 for e in entries if e.enabled),
            "domains": self.by_domain(),
            "total_calls": total_calls,
            "overall_success_rate": round(total_success / total_calls, 3) if total_calls else 1.0,
        }


# ── Singleton ────────────────────────────────────────────────────────────────

_framework: ConnectorFramework | None = None

def get_connector_framework() -> ConnectorFramework:
    global _framework
    if _framework is None:
        _framework = ConnectorFramework()
    return _framework
