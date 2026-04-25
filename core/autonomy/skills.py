"""
core/autonomy/skills.py — Composable autonomy skills.

A *skill* in the autonomy layer is a reusable, parameterized workflow
that the daemon (or a human) can invoke by name. Skills wrap higher-
level operations than raw actions :

    - "audit-security" : run security_review skill on changed files
    - "scan-opportunities" : trigger opportunity_scanner with filters
    - "rotate-secrets-dryrun" : test the rotation script without applying
    - "deploy-mvp" : full pipeline from validated patch to PR

Skills are :

- **Pure data + a callable** : a `Skill` dataclass holds metadata, a
  `run()` callable, and a JSON-schema-style param spec.
- **Discoverable** : the registry indexes by name + tag. The planner
  asks "what skills can fulfill goal X ?" and matches via tag overlap.
- **Composable** : a skill can call other skills via the registry,
  allowing meta-skills like "weekly-audit" that chains audits +
  notifications.
- **Auditable** : every invocation publishes `skill.invoked` /
  `skill.completed` / `skill.failed` events on the bus, with the param
  payload (secret-scrubbed). This gives the operator a clear trail.

Public API :
    @register_skill(name="my-skill", tags=["audit"], description="...")
    def my_skill(ctx: SkillContext) -> SkillResult:
        ...

    registry = get_skill_registry()
    skill = registry.get("my-skill")
    result = skill.run(SkillContext(params={"target": "..."}))
    matches = registry.find_by_tag("audit")
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import structlog

from core.autonomy.event_bus import EventBus, get_event_bus

log = structlog.get_logger(__name__)


@dataclass
class SkillContext:
    """All inputs a skill execution receives."""
    params: Dict[str, Any] = field(default_factory=dict)
    invocation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    invoked_by: str = "unknown"  # "human", "daemon", "skill:<name>"
    started_at: float = field(default_factory=time.time)


@dataclass
class SkillResult:
    """Outcome of a skill run."""
    success: bool
    output: Any = None
    error: str = ""
    metrics: Dict[str, Any] = field(default_factory=dict)


# Skill body is a sync callable — async wrappers can be added later
SkillFn = Callable[[SkillContext], SkillResult]


@dataclass
class Skill:
    """A registered skill : metadata + callable."""
    name: str
    fn: SkillFn
    description: str = ""
    tags: List[str] = field(default_factory=list)
    param_schema: Dict[str, Any] = field(default_factory=dict)
    risk_level: str = "low"  # low | medium | high — informs approval
    requires_approval: bool = False

    def run(self, ctx: Optional[SkillContext] = None, *, bus: Optional[EventBus] = None) -> SkillResult:
        """Execute the skill, emitting bus events around the call.

        On exception the failure is recorded as a SkillResult so
        callers don't have to wrap every call in try/except.
        """
        ctx = ctx or SkillContext()
        bus = bus or get_event_bus()
        bus.publish(
            "skill.invoked",
            {
                "skill": self.name,
                "tags": self.tags,
                "invoked_by": ctx.invoked_by,
                "invocation_id": ctx.invocation_id,
                "params_keys": sorted(ctx.params.keys()),
            },
        )
        try:
            result = self.fn(ctx)
            bus.publish(
                "skill.completed" if result.success else "skill.failed",
                {
                    "skill": self.name,
                    "invocation_id": ctx.invocation_id,
                    "duration_s": round(time.time() - ctx.started_at, 3),
                    "error": result.error,
                },
            )
            return result
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"[:200]
            bus.publish(
                "skill.failed",
                {
                    "skill": self.name,
                    "invocation_id": ctx.invocation_id,
                    "duration_s": round(time.time() - ctx.started_at, 3),
                    "error": err,
                },
            )
            log.warning("skill.exception", skill=self.name, err=err)
            return SkillResult(success=False, error=err)


# ── Registry ─────────────────────────────────────────────────
class SkillRegistry:
    """Process-wide registry. Thread-safe."""

    def __init__(self):
        self._skills: Dict[str, Skill] = {}
        self._lock = threading.RLock()

    def register(self, skill: Skill) -> Skill:
        with self._lock:
            if skill.name in self._skills:
                log.debug("skill.replaced", name=skill.name)
            self._skills[skill.name] = skill
        log.debug("skill.registered", name=skill.name, tags=skill.tags)
        return skill

    def unregister(self, name: str) -> bool:
        with self._lock:
            return self._skills.pop(name, None) is not None

    def get(self, name: str) -> Optional[Skill]:
        with self._lock:
            return self._skills.get(name)

    def all(self) -> List[Skill]:
        with self._lock:
            return list(self._skills.values())

    def find_by_tag(self, tag: str) -> List[Skill]:
        with self._lock:
            return [s for s in self._skills.values() if tag in s.tags]

    def names(self) -> List[str]:
        with self._lock:
            return sorted(self._skills.keys())


# ── Decorator helper ─────────────────────────────────────────
_REGISTRY: Optional[SkillRegistry] = None
_REGISTRY_LOCK = threading.Lock()


def get_skill_registry() -> SkillRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        with _REGISTRY_LOCK:
            if _REGISTRY is None:
                _REGISTRY = SkillRegistry()
    return _REGISTRY


def reset_skill_registry() -> None:
    """Test fixture hook."""
    global _REGISTRY
    with _REGISTRY_LOCK:
        _REGISTRY = None


def register_skill(
    *,
    name: str,
    description: str = "",
    tags: Optional[List[str]] = None,
    param_schema: Optional[Dict[str, Any]] = None,
    risk_level: str = "low",
    requires_approval: bool = False,
) -> Callable[[SkillFn], Skill]:
    """Decorator : register a function as a skill in the global registry."""

    def decorator(fn: SkillFn) -> Skill:
        skill = Skill(
            name=name,
            fn=fn,
            description=description,
            tags=list(tags or []),
            param_schema=dict(param_schema or {}),
            risk_level=risk_level,
            requires_approval=requires_approval,
        )
        get_skill_registry().register(skill)
        return skill

    return decorator
