"""
kernel/classifier/mission_classifier.py — Kernel Mission Classifier
====================================================================
Classifies every mission goal before any execution begins.

The classifier is the kernel's first cognitive act on a mission:
it assigns task type, complexity, risk, and execution constraints.
These outputs feed directly into:
  - kernel/policy/     → risk → approval gate
  - kernel/planning/   → complexity → planning depth
  - kernel/routing/    → task_type → capability selection

KERNEL RULE: Zero imports from core/, agents/, api/, tools/.
Registration pattern: core's richer classifier registers itself at boot.
Fallback: kernel-native heuristic classifier (always available).

Registration:
  from kernel.classifier.mission_classifier import register_core_classifier
  from core.orchestration.mission_classifier import classify as core_classify
  register_core_classifier(core_classify)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

try:
    import structlog
    _log = structlog.get_logger("kernel.classifier")
except ImportError:
    import logging
    _log = logging.getLogger("kernel.classifier")


# ── Kernel-level enums (independent of core enums) ──────────────────────────

class KernelTaskType(str, Enum):
    QUERY          = "query"
    ANALYSIS       = "analysis"
    IMPLEMENTATION = "implementation"
    DEBUGGING      = "debugging"
    DEPLOYMENT     = "deployment"
    RESEARCH       = "research"
    SYSTEM_OPS     = "system_ops"
    IMPROVEMENT    = "improvement"
    WORKFLOW       = "workflow"
    BUSINESS       = "business"
    OTHER          = "other"


class KernelComplexity(str, Enum):
    TRIVIAL  = "trivial"    # direct answer, no steps
    SIMPLE   = "simple"     # 1-2 steps
    MODERATE = "moderate"   # 3-5 steps
    COMPLEX  = "complex"    # 5+ steps, dependencies


class KernelRisk(str, Enum):
    LOW      = "low"
    MEDIUM   = "medium"
    HIGH     = "high"
    CRITICAL = "critical"


# ── Kernel classification result ─────────────────────────────────────────────

@dataclass
class KernelClassification:
    """
    The kernel's understanding of a mission goal.

    This is the authoritative classification used by:
      - policy engine (risk + needs_approval)
      - planner (complexity + planning_depth)
      - router (task_type + suggested_capabilities)
      - improvement gate (task_type == IMPROVEMENT)
    """
    task_type:            KernelTaskType  = KernelTaskType.OTHER
    complexity:           KernelComplexity = KernelComplexity.SIMPLE
    risk:                 KernelRisk       = KernelRisk.LOW
    needs_approval:       bool             = False
    needs_planning:       bool             = False
    needs_memory:         bool             = True
    is_improvement_task:  bool             = False
    planning_depth:       int              = 1       # 0=direct, 1=single, 2=multi, 3=decompose
    suggested_capabilities: list[str]      = field(default_factory=list)
    reasoning:            str              = ""
    value_score:          float            = 0.5
    source:               str              = "kernel_heuristic"

    def to_dict(self) -> dict:
        return {
            "task_type":             self.task_type.value,
            "complexity":            self.complexity.value,
            "risk":                  self.risk.value,
            "needs_approval":        self.needs_approval,
            "needs_planning":        self.needs_planning,
            "needs_memory":          self.needs_memory,
            "is_improvement_task":   self.is_improvement_task,
            "planning_depth":        self.planning_depth,
            "suggested_capabilities": self.suggested_capabilities,
            "reasoning":             self.reasoning,
            "value_score":           self.value_score,
            "source":                self.source,
        }


# ── Registration slot ─────────────────────────────────────────────────────────
_core_classifier_fn: Optional[Callable[[str], object]] = None


def register_core_classifier(fn: Callable[[str], object]) -> None:
    """
    Register core.orchestration.mission_classifier.classify.
    Called at boot — kernel never imports core directly.
    """
    global _core_classifier_fn
    _core_classifier_fn = fn
    _log.debug("kernel_classifier_registered")


# ── Kernel heuristic classifier ───────────────────────────────────────────────

_TYPE_KEYWORDS: dict[KernelTaskType, list[str]] = {
    KernelTaskType.QUERY:          ["what is", "who is", "how many", "explain", "define", "tell me"],
    KernelTaskType.ANALYSIS:       ["analyze", "analyse", "review", "audit", "compare", "evaluate", "assess"],
    KernelTaskType.IMPLEMENTATION: ["create", "build", "implement", "write", "add", "develop", "code", "make"],
    KernelTaskType.DEBUGGING:      ["fix", "debug", "repair", "resolve", "error", "crash", "broken", "bug"],
    KernelTaskType.DEPLOYMENT:     ["deploy", "release", "publish", "ci/cd", "docker", "kubernetes", "k8s"],
    KernelTaskType.RESEARCH:       ["research", "investigate", "find", "search", "explore", "discover"],
    KernelTaskType.SYSTEM_OPS:     ["monitor", "scale", "backup", "migrate", "server", "infra", "ops"],
    KernelTaskType.IMPROVEMENT:    ["improve", "optimiz", "refactor", "upgrade", "enhance", "self-improve"],
    KernelTaskType.WORKFLOW:       ["workflow", "pipeline", "orchestrate", "automate", "sequence"],
    KernelTaskType.BUSINESS:       ["saas", "venture", "revenue", "customer", "market", "product", "mvp"],
}

_COMPLEXITY_SIGNALS: dict[KernelComplexity, list[str]] = {
    KernelComplexity.COMPLEX:  ["multi-step", "complex", "architecture", "system", "full", "end-to-end"],
    KernelComplexity.MODERATE: ["integrate", "automate", "migrate", "refactor", "pipeline"],
    KernelComplexity.SIMPLE:   ["create", "write", "fix", "add", "update", "list"],
    KernelComplexity.TRIVIAL:  ["what", "who", "when", "where", "how many"],
}

_HIGH_RISK_KEYWORDS: list[str] = [
    "delete", "drop", "remove", "destroy", "wipe", "production", "deploy",
    "payment", "stripe", "financial", "api key", "secret", "credentials",
]

_MEDIUM_RISK_KEYWORDS: list[str] = [
    "write", "modify", "update", "change", "create", "build", "execute",
    "run", "send", "email", "webhook",
]


def _heuristic_classify(goal: str) -> KernelClassification:
    """
    Pure keyword-based classification. Zero imports, always works.
    Deterministic: same input → same output.
    """
    text = goal.lower()
    words = text.split()
    word_count = len(words)

    # Task type
    task_type = KernelTaskType.OTHER
    for tt, keywords in _TYPE_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            task_type = tt
            break

    # Complexity by word count + keywords
    if word_count > 40 or any(k in text for k in _COMPLEXITY_SIGNALS[KernelComplexity.COMPLEX]):
        complexity = KernelComplexity.COMPLEX
        planning_depth = 3
    elif word_count > 15 or any(k in text for k in _COMPLEXITY_SIGNALS[KernelComplexity.MODERATE]):
        complexity = KernelComplexity.MODERATE
        planning_depth = 2
    elif word_count <= 5 or any(k in text for k in _COMPLEXITY_SIGNALS[KernelComplexity.TRIVIAL]):
        complexity = KernelComplexity.TRIVIAL
        planning_depth = 0
    else:
        complexity = KernelComplexity.SIMPLE
        planning_depth = 1

    # Risk
    if any(k in text for k in _HIGH_RISK_KEYWORDS):
        risk = KernelRisk.HIGH
        needs_approval = True
    elif any(k in text for k in _MEDIUM_RISK_KEYWORDS):
        risk = KernelRisk.MEDIUM
        needs_approval = False
    else:
        risk = KernelRisk.LOW
        needs_approval = False

    # Improvement task detection
    is_improvement = task_type == KernelTaskType.IMPROVEMENT

    # Needs planning?
    needs_planning = complexity in (KernelComplexity.MODERATE, KernelComplexity.COMPLEX)

    # Value score (heuristic — higher for implementation + complex)
    value = 0.5
    if task_type == KernelTaskType.IMPLEMENTATION:
        value = 0.8
    elif task_type == KernelTaskType.ANALYSIS:
        value = 0.7
    elif complexity == KernelComplexity.TRIVIAL:
        value = 0.3

    return KernelClassification(
        task_type=task_type,
        complexity=complexity,
        risk=risk,
        needs_approval=needs_approval,
        needs_planning=needs_planning,
        is_improvement_task=is_improvement,
        planning_depth=planning_depth,
        reasoning=f"heuristic: type={task_type.value} complexity={complexity.value} risk={risk.value}",
        value_score=value,
        source="kernel_heuristic",
    )


def _from_core_result(raw: object) -> KernelClassification:
    """Convert core MissionClassification to KernelClassification."""
    def _safe(obj, attr, default):
        v = getattr(obj, attr, None)
        if v is None and isinstance(obj, dict):
            v = obj.get(attr)
        return v if v is not None else default

    def _enum_val(obj, attr, default):
        v = _safe(obj, attr, default)
        return v.value if hasattr(v, "value") else str(v) if v else default

    task_str = _enum_val(raw, "task_type", "other")
    complexity_str = _enum_val(raw, "complexity", "simple")
    risk_str = _safe(raw, "risk_level", "low")

    try:
        task_type = KernelTaskType(task_str)
    except ValueError:
        task_type = KernelTaskType.OTHER
    try:
        complexity = KernelComplexity(complexity_str)
    except ValueError:
        complexity = KernelComplexity.SIMPLE
    try:
        risk = KernelRisk(risk_str)
    except ValueError:
        risk = KernelRisk.LOW

    return KernelClassification(
        task_type=task_type,
        complexity=complexity,
        risk=risk,
        needs_approval=bool(_safe(raw, "needs_approval", False)),
        needs_planning=bool(_safe(raw, "needs_planning", False)),
        needs_memory=bool(_safe(raw, "needs_memory", True)),
        is_improvement_task=(task_type == KernelTaskType.IMPROVEMENT),
        planning_depth=int(_safe(raw, "planning_depth", 1)),
        suggested_capabilities=list(_safe(raw, "suggested_tools", []) or []),
        reasoning=str(_safe(raw, "reasoning", "core_classifier")),
        value_score=float(_safe(raw, "value_score", 0.5)),
        source="core_classifier",
    )


# ── KernelClassifier ─────────────────────────────────────────────────────────

class KernelClassifier:
    """
    Classifies mission goals. The kernel's first cognitive step.

    Priority:
      1. Registered core classifier (richer patterns, task taxonomy)
      2. Kernel heuristic classifier (always available, deterministic)

    Used by:
      - kernel.policy   → risk → approval decision
      - kernel.planning → complexity → planning depth
      - kernel.routing  → task_type → capability selection
      - kernel.improvement → is_improvement_task → gating
    """

    def classify(self, goal: str) -> KernelClassification:
        """
        Classify a mission goal. Never raises.
        Returns KernelClassification with source='core_classifier' or 'kernel_heuristic'.
        """
        if not goal or not goal.strip():
            return KernelClassification(
                reasoning="empty goal", source="kernel_heuristic",
            )

        # 1 — core classifier (richer, registered at boot)
        if _core_classifier_fn is not None:
            try:
                raw = _core_classifier_fn(goal)
                result = _from_core_result(raw)
                return result
            except Exception as e:
                _log.debug("kernel_classifier_core_failed", err=str(e)[:80])

        # 2 — kernel heuristic (always available)
        return _heuristic_classify(goal)


# ── Module-level singleton ────────────────────────────────────────────────────
_classifier: KernelClassifier | None = None


def get_classifier() -> KernelClassifier:
    """Return singleton KernelClassifier."""
    global _classifier
    if _classifier is None:
        _classifier = KernelClassifier()
    return _classifier
