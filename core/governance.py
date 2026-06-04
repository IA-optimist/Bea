"""
JARVIS — Governance & Multi-Business Operations
===================================================
Safety hardening, multi-business isolation, and operational governance.

This module EXTENDS existing safety_controls and operating_primitives.
It does NOT create parallel orchestration.

Capabilities:
1. Connector execution rate limiting (global + per-connector)
2. Dangerous action classification & blocking
3. Persistence integrity validation
4. Multi-business project domains with isolation
5. Per-domain performance & health signals
6. Mission audit trail (complements connector audit)
7. Operational governance dashboard

Integrates with:
  - safety_controls (kill switches)
  - operating_primitives (objectives, approval)
  - business_pipeline (leads, content, budget)
  - connectors (approval audit)
  - lifecycle_tracker

Zero external dependencies. Fail-open (except for safety blocks).
"""
from __future__ import annotations

import json
import structlog
import os
import time
import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Optional

logger = structlog.get_logger("jarvis.governance")
log = logger  # alias for M3 emitter


# ═══════════════════════════════════════════════════════════════
# 1. CONNECTOR RATE LIMITING
# ═══════════════════════════════════════════════════════════════

_connector_call_log: dict[str, list[float]] = {}
_CONNECTOR_RATE_WINDOW = 60  # seconds
_CONNECTOR_RATE_MAX = int(os.environ.get("JARVIS_CONNECTOR_RATE_MAX", "30"))
_GLOBAL_RATE_MAX = int(os.environ.get("JARVIS_GLOBAL_RATE_MAX", "100"))
_global_call_log: list[float] = []


def check_connector_rate(connector_name: str) -> tuple[bool, str]:
    """
    Check if a connector call is within rate limits.
    Returns (allowed, reason).
    """
    now = time.time()

    # Global rate limit
    global _global_call_log
    _global_call_log = [t for t in _global_call_log if now - t < _CONNECTOR_RATE_WINDOW]
    if len(_global_call_log) >= _GLOBAL_RATE_MAX:
        return False, f"global rate limit ({_GLOBAL_RATE_MAX}/min)"

    # Per-connector rate limit
    if connector_name not in _connector_call_log:
        _connector_call_log[connector_name] = []
    calls = _connector_call_log[connector_name]
    _connector_call_log[connector_name] = [t for t in calls if now - t < _CONNECTOR_RATE_WINDOW]

    if len(_connector_call_log[connector_name]) >= _CONNECTOR_RATE_MAX:
        return False, f"connector rate limit: {connector_name} ({_CONNECTOR_RATE_MAX}/min)"

    # Record call
    _connector_call_log[connector_name].append(now)
    _global_call_log.append(now)
    return True, "ok"


def get_rate_limit_status() -> dict:
    """Get current rate limiting status."""
    now = time.time()
    per_connector = {}
    for name, calls in _connector_call_log.items():
        recent = [t for t in calls if now - t < _CONNECTOR_RATE_WINDOW]
        per_connector[name] = {
            "calls_last_minute": len(recent),
            "limit": _CONNECTOR_RATE_MAX,
            "utilization": round(len(recent) / max(_CONNECTOR_RATE_MAX, 1), 3),
        }

    recent_global = [t for t in _global_call_log if now - t < _CONNECTOR_RATE_WINDOW]
    return {
        "global_calls_last_minute": len(recent_global),
        "global_limit": _GLOBAL_RATE_MAX,
        "global_utilization": round(len(recent_global) / max(_GLOBAL_RATE_MAX, 1), 3),
        "per_connector": per_connector,
    }


# ═══════════════════════════════════════════════════════════════
# 2. DANGEROUS ACTION CLASSIFICATION
# ═══════════════════════════════════════════════════════════════

DANGER_LEVELS = {
    "safe": 0,        # read-only, no side effects
    "low": 1,         # internal writes, reversible
    "medium": 2,      # external reads, connector use
    "high": 3,        # external writes, communication
    "critical": 4,    # financial, destructive, public
}

# Connector → danger level mapping
CONNECTOR_DANGER: dict[str, str] = {
    "json_storage": "low",
    "document_writer": "low",
    "structured_extractor": "safe",
    "task_list": "low",
    "file_export": "low",
    "lead_manager": "low",
    "content_manager": "low",
    "budget_tracker": "low",
    "web_search": "medium",
    "web_scrape": "medium",
    "http_request": "medium",
    "api_connector": "medium",
    "email": "high",
    "messaging": "high",
    "webhook": "high",
    "workflow_trigger": "medium",
    "scheduler": "medium",
}

# Action patterns → danger level
ACTION_DANGER_PATTERNS: list[tuple[str, str]] = [
    ("delete", "high"),
    ("remove", "high"),
    ("payment", "critical"),
    ("invoice", "high"),
    ("publish", "high"),
    ("deploy", "high"),
    ("send_email", "high"),
    ("send_message", "high"),
    ("transfer", "critical"),
    ("subscribe", "high"),
    ("unsubscribe", "high"),
]


def classify_danger(connector_name: str = "", action: str = "",
                    goal: str = "") -> dict:
    """
    Classify the danger level of an action.
    Returns {level, score, requires_approval, reason}.
    """
    level = "safe"
    reasons = []

    # Connector-based
    if connector_name:
        cl = CONNECTOR_DANGER.get(connector_name, "medium")
        if DANGER_LEVELS.get(cl, 0) > DANGER_LEVELS.get(level, 0):
            level = cl
            reasons.append(f"connector '{connector_name}' classified as {cl}")

    # Action pattern matching
    action_lower = (action + " " + goal).lower()
    for pattern, danger in ACTION_DANGER_PATTERNS:
        if pattern in action_lower:
            if DANGER_LEVELS.get(danger, 0) > DANGER_LEVELS.get(level, 0):
                level = danger
                reasons.append(f"matched dangerous pattern: '{pattern}'")

    return {
        "level": level,
        "score": DANGER_LEVELS.get(level, 0),
        "requires_approval": DANGER_LEVELS.get(level, 0) >= 3,  # high or critical
        "reason": "; ".join(reasons) if reasons else "no dangerous patterns detected",
    }


# ═══════════════════════════════════════════════════════════════
# 3. PERSISTENCE INTEGRITY
# ═══════════════════════════════════════════════════════════════

def validate_persistence_file(path: str) -> dict:
    """
    Validate a persistence file's integrity.
    Returns {valid, format, entries, size_bytes, issues}.
    """
    result = {
        "path": path,
        "valid": False,
        "format": "unknown",
        "entries": 0,
        "size_bytes": 0,
        "issues": [],
    }

    if not os.path.exists(path):
        result["issues"].append("file does not exist")
        return result

    try:
        result["size_bytes"] = os.path.getsize(path)
    except Exception:
        result["issues"].append("cannot read file size")
        return result

    if result["size_bytes"] == 0:
        result["issues"].append("file is empty")
        return result

    # Try JSON
    try:
        with open(path) as f:
            data = json.load(f)
        result["format"] = "json"
        if isinstance(data, dict):
            result["entries"] = len(data)
        elif isinstance(data, list):
            result["entries"] = len(data)
        result["valid"] = True
        return result
    except json.JSONDecodeError as _exc:
        log.warning("swallowed_exception", action="governance_1", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    # Try JSONL
    try:
        entries = 0
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    json.loads(line)
                    entries += 1
        result["format"] = "jsonl"
        result["entries"] = entries
        result["valid"] = True
        return result
    except (json.JSONDecodeError, Exception) as e:
        result["issues"].append(f"parse error: {str(e)[:100]}")

    return result


PERSISTENCE_FILES = [
    "workspace/tool_performance.jsonl",
    "workspace/mission_performance.jsonl",
    "workspace/mission_memory.json",
    "workspace/improvement_proposals.json",
    "workspace/objectives.json",
    "workspace/workflow_templates.json",
    "workspace/scheduled_tasks.json",
    "workspace/workflow_executions.json",
    "workspace/leads.json",
    "workspace/content_pipeline.json",
    "workspace/budget.jsonl",
]


def validate_all_persistence() -> dict:
    """Validate all persistence files."""
    results = {}
    for path in PERSISTENCE_FILES:
        results[path] = validate_persistence_file(path)

    valid = sum(1 for r in results.values() if r["valid"])
    exists = sum(1 for r in results.values() if os.path.exists(r["path"]))
    total_size = sum(r["size_bytes"] for r in results.values())

    return {
        "total_files": len(PERSISTENCE_FILES),
        "existing": exists,
        "valid": valid,
        "total_size_bytes": total_size,
        "files": results,
    }


# ═══════════════════════════════════════════════════════════════
# 4. MULTI-BUSINESS PROJECT DOMAINS
# ═══════════════════════════════════════════════════════════════

MAX_DOMAINS = 20


@dataclass
class BusinessDomain:
    """A business project / domain for multi-business isolation."""
    domain_id: str = ""
    name: str = ""
    description: str = ""
    status: str = "active"       # active | paused | archived
    created_at: float = 0.0
    updated_at: float = 0.0
    objective_ids: list = field(default_factory=list)
    lead_tags: list = field(default_factory=list)  # tags to filter leads
    total_missions: int = 0
    successful_missions: int = 0
    total_revenue: float = 0.0
    total_cost: float = 0.0
    health_score: float = 0.5
    slot_allocation: float = 0.2  # fraction of capacity allocated (0-1)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def success_rate(self) -> float:
        if self.total_missions == 0:
            return 0.0
        return round(self.successful_missions / self.total_missions, 3)

    @property
    def net(self) -> float:
        return round(self.total_revenue - self.total_cost, 2)

    @property
    def roi(self) -> float:
        if self.total_cost <= 0:
            return 0.0
        return round(self.total_revenue / self.total_cost, 2)


class DomainManager:
    """Manages multiple business domains with isolation and performance tracking."""
    PERSIST_FILE = "workspace/domains.json"

    def __init__(self, persist_path: Optional[str] = None):
        self._domains: dict[str, BusinessDomain] = {}
        self._persist_path = persist_path or self.PERSIST_FILE
        self._loaded = False

    def _ensure_loaded(self):
        if not self._loaded:
            self.load()
            self._loaded = True

    def create_domain(self, name: str, description: str = "",
                      lead_tags: list = None,
                      slot_allocation: float = 0.2) -> BusinessDomain:
        """Create a new business domain."""
        self._ensure_loaded()
        if len(self._domains) >= MAX_DOMAINS:
            archived = [d for d in self._domains.values() if d.status == "archived"]
            if archived:
                oldest = min(archived, key=lambda d: d.updated_at)
                del self._domains[oldest.domain_id]
            else:
                raise ValueError(f"Max domains reached ({MAX_DOMAINS})")

        domain = BusinessDomain(
            domain_id=str(uuid.uuid4())[:8],
            name=name[:200],
            description=description[:500],
            lead_tags=(lead_tags or [])[:10],
            slot_allocation=min(max(slot_allocation, 0.05), 1.0),
            created_at=time.time(),
            updated_at=time.time(),
        )
        self._domains[domain.domain_id] = domain
        self.save()
        return domain

    def record_mission(self, domain_id: str, success: bool,
                       cost: float = 0.0, revenue: float = 0.0) -> None:
        """Record a mission outcome for a domain."""
        self._ensure_loaded()
        d = self._domains.get(domain_id)
        if not d:
            return
        d.total_missions += 1
        if success:
            d.successful_missions += 1
        d.total_cost += abs(cost)
        d.total_revenue += max(revenue, 0)
        d.updated_at = time.time()

        # Recompute health
        success_weight = d.success_rate * 0.4
        roi_weight = min(d.roi / 5.0, 0.3) if d.total_cost > 0 else 0.15
        activity_weight = min(d.total_missions / 10.0, 0.3)
        d.health_score = round(min(success_weight + roi_weight + activity_weight, 1.0), 3)
        self.save()

    def link_objective(self, domain_id: str, objective_id: str) -> bool:
        self._ensure_loaded()
        d = self._domains.get(domain_id)
        if not d:
            return False
        if objective_id not in d.objective_ids:
            d.objective_ids.append(objective_id)
            if len(d.objective_ids) > 50:
                d.objective_ids = d.objective_ids[-50:]
        d.updated_at = time.time()
        self.save()
        return True

    def get_domain(self, domain_id: str) -> Optional[BusinessDomain]:
        self._ensure_loaded()
        return self._domains.get(domain_id)

    def list_domains(self, status: str = "") -> list[dict]:
        self._ensure_loaded()
        domains = list(self._domains.values())
        if status:
            domains = [d for d in domains if d.status == status]
        return [d.to_dict() for d in sorted(domains, key=lambda d: d.health_score, reverse=True)]

    def recommend_slot_allocation(self) -> list[dict]:
        """
        Recommend how to allocate capacity across domains.
        Based on health, ROI, and activity.
        """
        self._ensure_loaded()
        active = [d for d in self._domains.values() if d.status == "active"]
        if not active:
            return []

        # Score each domain
        scored = []
        for d in active:
            score = d.health_score * 0.4 + min(d.roi / 5.0, 0.3) + (0.3 if d.total_missions < 3 else 0)
            scored.append((score, d))

        scored.sort(key=lambda x: x[0], reverse=True)
        total_score = sum(s for s, _ in scored)
        if total_score <= 0:
            total_score = len(scored)

        recommendations = []
        for score, domain in scored:
            allocation = round(score / total_score, 3)
            action = "continue"
            if domain.total_missions >= 5 and domain.success_rate < 0.2:
                action = "stop"
            elif domain.total_missions >= 10 and domain.roi < 0.5:
                action = "reduce"
            elif domain.total_missions < 3:
                action = "invest"
            elif domain.roi > 3.0:
                action = "scale"

            recommendations.append({
                "domain_id": domain.domain_id,
                "name": domain.name,
                "recommended_allocation": allocation,
                "current_allocation": domain.slot_allocation,
                "action": action,
                "health_score": domain.health_score,
                "roi": domain.roi,
                "success_rate": domain.success_rate,
            })

        return recommendations

    def get_portfolio_dashboard(self) -> dict:
        """Full multi-business portfolio dashboard."""
        self._ensure_loaded()
        active = [d for d in self._domains.values() if d.status == "active"]
        total_revenue = sum(d.total_revenue for d in self._domains.values())
        total_cost = sum(d.total_cost for d in self._domains.values())

        return {
            "total_domains": len(self._domains),
            "active": len(active),
            "total_revenue": round(total_revenue, 2),
            "total_cost": round(total_cost, 2),
            "net": round(total_revenue - total_cost, 2),
            "portfolio_roi": round(total_revenue / max(total_cost, 0.01), 2),
            "domains": self.list_domains(),
            "slot_recommendations": self.recommend_slot_allocation(),
            "top_performers": [d.to_dict() for d in sorted(
                active, key=lambda d: d.health_score, reverse=True
            )[:5]],
            "needs_attention": [d.to_dict() for d in active
                               if d.health_score < 0.3 and d.total_missions >= 3],
        }

    def save(self):
        try:
            os.makedirs(os.path.dirname(self._persist_path) or ".", exist_ok=True)
            with open(self._persist_path, "w") as f:
                json.dump({k: v.to_dict() for k, v in self._domains.items()}, f, indent=2)
        except Exception as e:
            logger.warning("domains_save_failed: %s", str(e)[:80])

    def load(self):
        if not os.path.exists(self._persist_path):
            return
        try:
            with open(self._persist_path) as f:
                data = json.load(f)
            for did, d in data.items():
                self._domains[did] = BusinessDomain(
                    **{k: v for k, v in d.items() if k in BusinessDomain.__dataclass_fields__}
                )
        except Exception as e:
            logger.warning("domains_load_failed: %s", str(e)[:80])


# ═══════════════════════════════════════════════════════════════
# 5. MISSION AUDIT TRAIL
# ═══════════════════════════════════════════════════════════════

_mission_audit: list[dict] = []
_MAX_MISSION_AUDIT = 500


def log_mission_event(mission_id: str, event: str, detail: str = "",
                      danger_level: str = "safe", domain_id: str = "") -> None:
    """Record a mission event for audit."""
    global _mission_audit
    _mission_audit.append({
        "mission_id": mission_id,
        "event": event,
        "detail": detail[:200],
        "danger_level": danger_level,
        "domain_id": domain_id,
        "timestamp": time.time(),
    })
    if len(_mission_audit) > _MAX_MISSION_AUDIT:
        _mission_audit = _mission_audit[-_MAX_MISSION_AUDIT:]


def get_mission_audit(limit: int = 50) -> dict:
    """Get mission audit trail."""
    recent = _mission_audit[-limit:]
    total = len(_mission_audit)
    by_level = defaultdict(int)
    for e in _mission_audit:
        by_level[e["danger_level"]] += 1

    return {
        "total_events": total,
        "by_danger_level": dict(by_level),
        "recent": recent,
    }


# ═══════════════════════════════════════════════════════════════
# 6. GOVERNANCE DASHBOARD
# ═══════════════════════════════════════════════════════════════

def get_governance_dashboard() -> dict:
    """
    Complete governance and safety dashboard.
    Single endpoint for all governance signals.
    """
    # Safety state
    try:
        from core.safety_controls import get_safety_state
        safety = get_safety_state().to_dict()
    except Exception:
        safety = {}

    # Rate limiting
    rate_limits = get_rate_limit_status()

    # Persistence integrity
    persistence = validate_all_persistence()

    # Approval audit
    try:
        from core.connectors import get_approval_audit
        approval_audit = get_approval_audit()
    except Exception:
        approval_audit = {}

    # Mission audit
    mission_audit = get_mission_audit(20)

    # Autonomy boundaries
    try:
        from core.workflow_runtime import get_autonomy_limits
        autonomy = get_autonomy_limits()
    except Exception:
        autonomy = {}

    # Canonical mission status distribution (P4 enrichment)
    canonical_status: dict = {}
    try:
        from core.mission_system import get_mission_system
        from core.canonical_types import map_legacy_mission_status
        ms = get_mission_system()
        for m in ms.list_missions(limit=200):
            raw = m.status.value if hasattr(m.status, 'value') else str(m.status)
            cs = map_legacy_mission_status(raw, "mission_system").value
            canonical_status[cs] = canonical_status.get(cs, 0) + 1
    except Exception as _exc:
        log.warning("swallowed_exception", action="governance_2", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    # Memory facade health
    memory_health: dict = {}
    try:
        from core.memory_facade import get_memory_facade
        memory_health = get_memory_facade().health()
    except Exception as _exc:
        log.warning("swallowed_exception", action="governance_3", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    # Kill switch status
    kill_switch_active = os.environ.get(
        "JARVIS_EXECUTION_DISABLED", ""
    ).lower() in ("1", "true", "yes")

    return {
        "safety_state": safety,
        "kill_switch_active": kill_switch_active,
        "rate_limits": rate_limits,
        "persistence": {
            "total_files": persistence["total_files"],
            "valid": persistence["valid"],
            "existing": persistence["existing"],
            "total_size_bytes": persistence["total_size_bytes"],
        },
        "approval_audit": approval_audit,
        "mission_audit": {
            "total_events": mission_audit["total_events"],
            "by_danger_level": mission_audit["by_danger_level"],
        },
        "canonical_status_distribution": canonical_status,
        "memory_health": memory_health,
        "autonomy_boundaries": autonomy,
        "danger_classification": {
            "levels": list(DANGER_LEVELS.keys()),
            "connector_classifications": CONNECTOR_DANGER,
        },
    }


# ═══════════════════════════════════════════════════════════════
# UNIFIED SAFETY CHECKPOINT
# ═══════════════════════════════════════════════════════════════

def safety_checkpoint(
    action: str = "",
    connector: str = "",
    risk_level: str = "low",
    mission_id: str = "",
) -> dict:
    """
    Unified pre-execution safety checkpoint.

    Checks ALL safety gates in one call:
    1. Kill switch
    2. Rate limiting
    3. Danger classification
    4. Resource guard
    5. Circuit breaker state

    Returns:
        {"allowed": True/False, "reason": str, "checks": dict}

    Usage:
        check = safety_checkpoint(action="write_file", risk_level="medium")
        if not check["allowed"]:
            return error(check["reason"])
    """
    checks: dict[str, bool] = {}

    # 1. Kill switch
    kill_switch = os.environ.get(
        "JARVIS_EXECUTION_DISABLED", ""
    ).lower() in ("1", "true", "yes")
    checks["kill_switch"] = not kill_switch
    if kill_switch:
        return {"allowed": False, "reason": "execution_disabled", "checks": checks}

    # 2. Rate limiting
    if connector:
        try:
            allowed, rate_reason = check_connector_rate(connector)
            checks["rate_limit"] = allowed
            if not allowed:
                return {"allowed": False, "reason": f"rate_limited: {rate_reason}", "checks": checks}
        except Exception:
            checks["rate_limit"] = True  # fail-open

    # 3. Danger classification
    if action or connector:
        try:
            danger = classify_danger(connector_name=connector, action=action)
            checks["danger_level"] = danger.get("level", "unknown")
            if danger.get("level") == "critical" and danger.get("requires_approval"):
                checks["danger_approved"] = False
                return {
                    "allowed": False,
                    "reason": f"critical_danger: {danger.get('reason', action)}",
                    "checks": checks,
                }
            checks["danger_approved"] = True
        except Exception:
            checks["danger_level"] = "unknown"

    # 4. Resource guard
    try:
        from core.resource_guard import get_resource_guard
        rg = get_resource_guard()
        status = rg.get_status()
        checks["resource_status"] = status.get("status", "unknown")
        if status.get("status") == "BLOCKED":
            return {"allowed": False, "reason": "resources_exhausted", "checks": checks}
    except Exception:
        checks["resource_status"] = "unknown"  # fail-open

    # 5. Circuit breaker (for connectors)
    if connector:
        try:
            from core.circuit_breaker import get_breaker
            cb = get_breaker(connector)
            checks["circuit_breaker"] = cb.state.value if hasattr(cb, 'state') else "unknown"
            if hasattr(cb, 'state') and cb.state.value == "OPEN":
                return {"allowed": False, "reason": f"circuit_open: {connector}", "checks": checks}
        except Exception:
            checks["circuit_breaker"] = "unknown"  # fail-open

    # Audit checkpoint (fail-open)
    if mission_id:
        try:
            log_mission_event(mission_id, "safety_checkpoint", str(checks)[:300])
        except Exception as _exc:
            log.warning("swallowed_exception", action="governance_4", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    return {"allowed": True, "reason": "", "checks": checks}


# ═══════════════════════════════════════════════════════════════
# SINGLETONS
# ═══════════════════════════════════════════════════════════════

_domain_manager: Optional[DomainManager] = None


def get_domain_manager() -> DomainManager:
    global _domain_manager
    if _domain_manager is None:
        _domain_manager = DomainManager()
    return _domain_manager
