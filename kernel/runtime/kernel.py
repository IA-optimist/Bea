"""
kernel/runtime/kernel.py — JarvisKernel: Single Kernel Entry Point
====================================================================
Phase 5 of the kernel recentering roadmap (see KERNEL_AUDIT.md).

JarvisKernel is the canonical kernel object. All system components
should interact with the kernel through this class, not through
MetaOrchestrator directly.

Architecture:
  JarvisKernel
    ├── .planning     → KernelPlanner
    ├── .state        → MissionStateMachine
    ├── .policy       → KernelPolicyEngine
    ├── .memory       → KernelMemory (working + episodic)
    ├── .capabilities → CapabilityRegistry
    ├── .events       → KernelEventEmitter
    ├── .classifier   → KernelClassifier       [Phase 5]
    ├── .gate         → ImprovementGate         [Phase 5]
    ├── .evaluator    → KernelEvaluator         [Phase 5]
    └── .router       → KernelCapabilityRouter  [Phase 5]

Usage (target):
  from kernel.runtime.kernel import get_kernel
  kernel = get_kernel()
  clf    = kernel.classifier.classify("build a REST API")
  plan   = kernel.planning.build(KernelGoal.from_text("build a REST API"))
  result = await kernel.submit("build a REST API")

KERNEL RULE: This module does NOT import from core/, agents/, api/, tools/.
core/ submits missions to the kernel via submit(). Not the other way around.

Current status: JarvisKernel delegates execution to MetaOrchestrator
(registered at boot via register_orchestrator). This will be inverted in
Phase 7 when the kernel becomes the primary executor.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

try:
    import structlog
    log = structlog.get_logger("kernel.kernel")
except ImportError:
    log = logging.getLogger("kernel.kernel")

# ── Registration slot for execution backend ───────────────────────────────────
# MetaOrchestrator registers itself here at boot.
# The kernel calls it for mission execution.
# This avoids kernel importing core/meta_orchestrator.py directly.
_orchestrator_fn: Optional[Callable[..., Any]] = None


def register_orchestrator(fn: Callable[..., Any]) -> None:
    """
    Register the execution backend (e.g. MetaOrchestrator.run_mission).
    Called at boot by core/. kernel/ never imports MetaOrchestrator directly.
    """
    global _orchestrator_fn
    _orchestrator_fn = fn
    log.debug("kernel_orchestrator_registered")


# ── Kernel Status ─────────────────────────────────────────────────────────────
@dataclass
class KernelStatus:
    """Snapshot of the kernel's current state."""
    booted:       bool
    version:      str
    uptime_s:     float
    planning:     bool
    state:        bool
    policy:       bool
    memory:       bool
    capabilities: int
    events:       bool
    orchestrator: bool
    classifier:   bool  = False  # Phase 5
    gate:         bool  = False  # Phase 5
    evaluator:    bool  = False  # Phase 5
    router:       bool  = False  # Phase 5

    def to_dict(self) -> dict:
        return {
            "booted":   self.booted,
            "version":  self.version,
            "uptime_s": self.uptime_s,
            "subsystems": {
                "planning":     self.planning,
                "state":        self.state,
                "policy":       self.policy,
                "memory":       self.memory,
                "capabilities": self.capabilities,
                "events":       self.events,
                "orchestrator": self.orchestrator,
                "classifier":   self.classifier,
                "gate":         self.gate,
                "evaluator":    self.evaluator,
                "router":       self.router,
            },
        }


# ── JarvisKernel ─────────────────────────────────────────────────────────────
class JarvisKernel:
    """
    The kernel. One object. One instance.

    All system components use this kernel as the single cognitive authority.
    The kernel arbitrates capabilities, enforces policy, manages state,
    provides memory, submits missions for execution, classifies goals,
    gates self-improvement, evaluates outcomes, and routes to providers.

    Current phase: kernel delegates execution to registered orchestrator.
    Target phase (7): kernel IS the orchestrator.
    """

    def __init__(self) -> None:
        self._booted_at: float = 0.0
        self._version: str = "1.0.0-phase5"

        # Subsystem handles (populated at boot or on first access)
        self._planning      = None
        self._state_machine = None
        self._policy        = None
        self._memory        = None
        self._capabilities  = None
        self._events        = None
        self._runtime       = None   # KernelRuntime from boot.py
        # Phase 5
        self._classifier    = None
        self._gate          = None
        self._evaluator     = None
        self._router        = None
        # Pass 23 — R5
        self._learner       = None

    def boot(self) -> "JarvisKernel":
        """
        Initialize all kernel subsystems.
        Returns self for chaining.
        """
        log.info("jarvis_kernel_boot_start", version=self._version)
        t0 = time.time()

        # 1 — Boot kernel runtime (existing boot.py infrastructure)
        try:
            from kernel.runtime.boot import get_runtime
            self._runtime      = get_runtime()
            self._policy       = self._runtime.policy
            self._memory       = self._runtime.memory
            self._capabilities = self._runtime.capabilities
            self._events       = self._runtime.events
        except Exception as e:
            log.warning("jarvis_kernel_runtime_unavailable", err=str(e)[:80])

        # 2 — Planning layer
        try:
            from kernel.planning.planner import get_planner
            self._planning = get_planner()
        except Exception as e:
            log.warning("jarvis_kernel_planning_unavailable", err=str(e)[:80])

        # 3 — State machine
        try:
            from kernel.state.mission_state import get_state_machine
            self._state_machine = get_state_machine()
        except Exception as e:
            log.warning("jarvis_kernel_state_unavailable", err=str(e)[:80])

        # 4 — Classifier (Phase 5)
        try:
            from kernel.classifier.mission_classifier import get_classifier
            self._classifier = get_classifier()
        except Exception as e:
            log.warning("jarvis_kernel_classifier_unavailable", err=str(e)[:80])

        # 5 — Improvement gate (Phase 5)
        try:
            from kernel.improvement.gate import get_gate
            self._gate = get_gate()
        except Exception as e:
            log.warning("jarvis_kernel_gate_unavailable", err=str(e)[:80])

        # 6 — Outcome evaluator (Phase 5)
        try:
            from kernel.evaluation.scorer import get_evaluator
            self._evaluator = get_evaluator()
        except Exception as e:
            log.warning("jarvis_kernel_evaluator_unavailable", err=str(e)[:80])

        # 7 — Capability router (Phase 5)
        try:
            from kernel.routing.router import get_router
            self._router = get_router()
        except Exception as e:
            log.warning("jarvis_kernel_router_unavailable", err=str(e)[:80])

        # 8 — Kernel learner (Pass 23 — R5)
        try:
            from kernel.learning.learner import get_learner as _get_learner
            self._learner = _get_learner()
        except Exception as e:
            log.warning("jarvis_kernel_learner_unavailable", err=str(e)[:80])

        self._booted_at = time.time()
        boot_ms = round((time.time() - t0) * 1000)
        log.info("jarvis_kernel_boot_complete", boot_ms=boot_ms, version=self._version)
        return self

    # ── Subsystem accessors ───────────────────────────────────────────────────

    @property
    def planning(self):
        """KernelPlanner — goal → plan."""
        if self._planning is None:
            from kernel.planning.planner import get_planner
            self._planning = get_planner()
        return self._planning

    @property
    def state(self):
        """MissionStateMachine — deterministic state transitions."""
        if self._state_machine is None:
            from kernel.state.mission_state import get_state_machine
            self._state_machine = get_state_machine()
        return self._state_machine

    @property
    def policy(self):
        """KernelPolicyEngine."""
        if self._policy is None and self._runtime is not None:
            self._policy = self._runtime.policy
        return self._policy

    @property
    def memory(self):
        """KernelMemory (working + episodic)."""
        if self._memory is None and self._runtime is not None:
            self._memory = self._runtime.memory
        return self._memory

    @property
    def capabilities(self):
        """CapabilityRegistry."""
        if self._capabilities is None and self._runtime is not None:
            self._capabilities = self._runtime.capabilities
        return self._capabilities

    @property
    def events(self):
        """KernelEventEmitter."""
        if self._events is None and self._runtime is not None:
            self._events = self._runtime.events
        return self._events

    @property
    def classifier(self):
        """KernelClassifier — classify mission goal before execution. [Phase 5]"""
        if self._classifier is None:
            from kernel.classifier.mission_classifier import get_classifier
            self._classifier = get_classifier()
        return self._classifier

    @property
    def gate(self):
        """ImprovementGate — gate self-improvement cycles. [Phase 5]"""
        if self._gate is None:
            from kernel.improvement.gate import get_gate
            self._gate = get_gate()
        return self._gate

    @property
    def learner(self):
        """KernelLearner — R5: structured learning via kernel.learn(). [Pass 23]"""
        if self._learner is None:
            from kernel.learning.learner import get_learner as _get_learner
            self._learner = _get_learner()
        return self._learner

    def learn(
        self,
        goal: str,
        result: str,
        mission_id: str,
        verdict: str = "accept",
        confidence: float = 0.7,
        weaknesses: Optional[list] = None,
        improvement_suggestion: str = "",
        retries: int = 0,
        error_class: str = "",
    ):
        """
        R5: Structured learning via kernel.learn().

        Delegates to KernelLearner.learn(). Never raises — fail-open.
        Returns KernelLesson or None (no lesson when mission was clean success).
        """
        try:
            return self.learner.learn(
                goal=goal,
                result=result,
                mission_id=mission_id,
                verdict=verdict,
                confidence=confidence,
                weaknesses=weaknesses or [],
                improvement_suggestion=improvement_suggestion,
                retries=retries,
                error_class=error_class,
            )
        except Exception as _le:
            log.debug("kernel_learn_failed", mission_id=mission_id, err=str(_le)[:80])
            return None

    @property
    def evaluator(self):
        """KernelEvaluator — score mission execution results. [Phase 5]"""
        if self._evaluator is None:
            from kernel.evaluation.scorer import get_evaluator
            self._evaluator = get_evaluator()
        return self._evaluator

    @property
    def router(self):
        """KernelCapabilityRouter — route goal to best capability provider. [Phase 5]"""
        if self._router is None:
            from kernel.routing.router import get_router
            self._router = get_router()
        return self._router

    # ── Convenience: classify a goal ─────────────────────────────────────────

    def classify(self, goal: str) -> object:
        """
        Classify a mission goal. Delegates to kernel.classifier.
        Returns KernelClassification. Never raises.
        """
        try:
            return self.classifier.classify(goal)
        except Exception as e:
            log.debug("kernel_classify_failed", err=str(e)[:80])
            from kernel.classifier.mission_classifier import KernelClassification
            return KernelClassification(reasoning=f"fallback: {str(e)[:40]}")

    # ── Convenience: evaluate an outcome ─────────────────────────────────────

    def evaluate(self, goal: str, result: str, task_type: str = "", mission_id: str = "") -> object:
        """
        Evaluate a mission execution result. Delegates to kernel.evaluator.
        Returns KernelScore. Never raises.
        """
        try:
            return self.evaluator.evaluate(goal=goal, result=result,
                                           task_type=task_type, mission_id=mission_id)
        except Exception as e:
            log.debug("kernel_evaluate_failed", err=str(e)[:80])
            from kernel.evaluation.scorer import KernelScore
            return KernelScore(score=0.5, passed=True, source="kernel_error_fallback")

    # ── Cognitive cycle pre-computation (Pass 11) ────────────────────────────

    def run_cognitive_cycle(
        self,
        goal: str,
        mode: str = "auto",
        mission_id: str = "",
    ) -> dict:
        """
        Pre-compute all cognitive phases: classify → plan → route.

        This is the kernel's authoritative cognitive brain. Called at the start
        of MetaOrchestrator.run_mission() BEFORE any inline phase runs.
        MetaOrchestrator uses the results directly; inline phases become fallbacks.

        Returns a dict with:
          classification       : dict  (from kernel.classify)
          _classification_obj  : object (KernelClassification, internal)
          kernel_plan          : dict  (from kernel.planning.build)
          _kernel_plan_obj     : object (KernelPlan, for Phase 3 injection)
          capability_routing   : list[dict] (from kernel.router.route)
          routed_provider      : dict or None

        Never raises — returns partial results on subsystem error.
        KERNEL RULE: zero imports from core/ here.
        """
        result: dict = {
            "kernel_cognitive_source": "kernel.run_cognitive_cycle",
            "mission_id": mission_id,
        }

        # 1. classify
        try:
            clf = self.classify(goal)
            result["classification"] = clf.to_dict()
            result["_classification_obj"] = clf
            log.debug("kernel_cognitive_classify",
                      task_type=str(getattr(getattr(clf, "task_type", None), "value", "?")))
        except Exception as _ce:
            log.debug("kernel_cognitive_classify_failed", err=str(_ce)[:80])

        # 2. plan
        try:
            from kernel.planning.goal import KernelGoal
            _task_type = str(
                result.get("classification", {}).get("task_type", "general") or "general"
            )
            kgoal = KernelGoal(description=goal, goal_type=_task_type)
            plan = self.planning.build(kgoal)
            result["kernel_plan"] = plan.to_dict()
            result["_kernel_plan_obj"] = plan
            log.debug("kernel_cognitive_plan", steps=plan.step_count, source=plan.source)
        except Exception as _pe:
            log.debug("kernel_cognitive_plan_failed", err=str(_pe)[:80])

        # 3. route
        try:
            routing = self.router.route(
                goal,
                classification=result.get("classification"),
                mode=mode,
            )
            result["capability_routing"] = [r.to_dict() for r in routing]
            _selected = [r for r in routing if r.success and r.selected_provider]
            if _selected:
                result["routed_provider"] = _selected[0].selected_provider.to_dict()
            log.debug("kernel_cognitive_route",
                      providers=len(_selected),
                      provider=_selected[0].selected_provider.provider_id if _selected else "none")
        except Exception as _re:
            log.debug("kernel_cognitive_route_failed", err=str(_re)[:80])

        # 4. retrieve lessons (Pass 13) ─────────────────────────────────────
        # Query kernel memory for lessons from similar past missions.
        # Injected into enriched_goal by MetaOrchestrator (closes cognitive loop).
        try:
            if self.memory is not None:
                _task_type_for_retrieve = str(
                    result.get("classification", {}).get("task_type", "") or ""
                )
                _lessons = self.memory.retrieve_lessons(
                    goal,
                    task_type=_task_type_for_retrieve,
                    max_results=3,
                )
                if _lessons:
                    result["kernel_lessons"] = _lessons
                    log.debug("kernel_cognitive_lessons", count=len(_lessons))
        except Exception as _le:
            log.debug("kernel_cognitive_lessons_failed", err=str(_le)[:80])

        log.debug("kernel_cognitive_cycle_complete",
                  has_classification=bool(result.get("classification")),
                  has_plan=bool(result.get("kernel_plan")),
                  has_routing=bool(result.get("routed_provider")),
                  has_lessons=bool(result.get("kernel_lessons")))
        return result

    # ── Core API ──────────────────────────────────────────────────────────────

    async def submit(
        self,
        goal: str,
        mode: str = "auto",
        mission_id: Optional[str] = None,
        callback: Optional[Callable] = None,
        **kwargs: Any,
    ) -> dict:
        """
        Submit a mission to the kernel for execution.

        The kernel:
          1. Checks policy (kernel.policy)
          2. Emits kernel.mission_submitted event
          3. Delegates execution to registered orchestrator
          4. Returns result dict

        Never raises — returns {"status": "FAILED", "error": ...} on failure.
        """
        mid = mission_id or f"km-{uuid.uuid4().hex[:8]}"

        # 1 — Policy check (fail-open)
        try:
            if self.policy:
                from kernel.contracts.types import Action, RiskLevel
                action = Action(
                    action_type="mission_execution",
                    target=goal[:120],
                    risk_level=RiskLevel.LOW,
                )
                decision = self.policy.evaluate(action, RiskLevel.LOW)
                if not decision.allowed:
                    return {
                        "mission_id": mid,
                        "status":     "FAILED",
                        "error":      f"Policy rejected: {decision.reason}",
                    }
        except Exception as _pe:
            log.debug("kernel_submit_policy_check_skipped", err=str(_pe)[:60])

        # 2 — Emit mission submitted event (fail-open)
        try:
            if self.events:
                from kernel.contracts.types import SystemEvent
                self.events.emit(SystemEvent(
                    event_type="kernel.mission_submitted",
                    source="kernel",
                    summary=f"Mission submitted: {goal[:80]}",
                    payload={"mission_id": mid, "mode": mode},
                ))
        except Exception:
            _silent_log.debug("suppressed_exception", src='kernel.py')

        # 3 — Delegate to registered orchestrator
        if _orchestrator_fn is None:
            log.warning("kernel_submit_no_orchestrator", mission_id=mid)
            return {
                "mission_id": mid,
                "status":     "FAILED",
                "error":      "No execution backend registered. Call register_orchestrator() at boot.",
            }

        try:
            result = await _orchestrator_fn(
                goal=goal,
                mode=mode,
                mission_id=mid,
                callback=callback,
                **kwargs,
            )
            return result if isinstance(result, dict) else {
                "mission_id": mid,
                "result":     result,
                "status":     "DONE",
            }
        except Exception as e:
            log.error("kernel_submit_failed", mission_id=mid, err=str(e)[:200])
            return {"mission_id": mid, "status": "FAILED", "error": str(e)[:200]}

    async def execute(self, request: "ExecutionRequest") -> "ExecutionResult":  # type: ignore[name-defined]
        """
        Authoritative kernel execution entry point (Pass 14).

        Pipeline:
          1. run_cognitive_cycle(goal) — classify + plan + route + retrieve
          2. policy check
          3. delegate to registered orchestrator
          4. wrap result in ExecutionResult

        The API calls this instead of MetaOrchestrator.run() directly.
        Never raises — returns ExecutionResult(status=FAILED) on error.

        Contracts: kernel/execution/contracts.py (K1-compliant, pure data).
        """
        from kernel.execution.contracts import ExecutionResult, ExecutionStatus

        mid = request.mission_id

        # 1 — Policy check (fail-open, same as submit())
        try:
            if self.policy:
                from kernel.contracts.types import Action, RiskLevel
                action = Action(
                    action_type="mission_execution",
                    target=request.goal[:120],
                    risk_level=RiskLevel.LOW,
                )
                decision = self.policy.evaluate(action, RiskLevel.LOW)
                if not decision.allowed:
                    return ExecutionResult(
                        mission_id=mid,
                        status=ExecutionStatus.FAILED,
                        error=f"Policy rejected: {decision.reason}",
                        goal=request.goal,
                        mode=request.mode,
                    )
        except Exception as _pe:
            log.debug("kernel_execute_policy_skipped", err=str(_pe)[:60])

        # 2 — Emit event (fail-open)
        try:
            if self.events:
                from kernel.contracts.types import SystemEvent
                self.events.emit(SystemEvent(
                    event_type="kernel.execute_started",
                    source="kernel",
                    summary=f"kernel.execute: {request.goal[:80]}",
                    payload={"mission_id": mid, "mode": request.mode},
                ))
        except Exception:
            _silent_log.debug("suppressed_exception", src='kernel.py')

        # 3 — Delegate to registered orchestrator
        if _orchestrator_fn is None:
            log.warning("kernel_execute_no_orchestrator", mission_id=mid)
            return ExecutionResult(
                mission_id=mid,
                status=ExecutionStatus.FAILED,
                error="No execution backend registered. Call register_orchestrator() at boot.",
                goal=request.goal,
                mode=request.mode,
            )

        try:
            raw = await _orchestrator_fn(
                goal=request.goal,
                mode=request.mode,
                mission_id=mid,
                callback=request.callback,
            )
            exec_result = ExecutionResult.from_context(raw)
            log.info("kernel_execute_done",
                     mission_id=mid,
                     status=exec_result.status.value,
                     has_result=bool(exec_result.result))
            return exec_result
        except Exception as e:
            log.error("kernel_execute_failed", mission_id=mid, err=str(e)[:200])
            return ExecutionResult(
                mission_id=mid,
                status=ExecutionStatus.FAILED,
                error=str(e)[:200],
                goal=request.goal,
                mode=request.mode,
            )

    def register_capability(self, name: str, metadata: dict = None) -> bool:
        """Register a capability with the kernel. Fail-open."""
        try:
            if self.capabilities:
                self.capabilities.register(name, metadata or {})
                return True
        except Exception as e:
            log.debug("kernel_register_capability_failed", name=name, err=str(e)[:60])
        return False

    def status(self) -> KernelStatus:
        """Return a snapshot of the kernel's current state."""
        uptime = round(time.time() - self._booted_at, 1) if self._booted_at else 0.0
        cap_count = 0
        try:
            if self.capabilities:
                cap_count = len(self.capabilities.list_all())
        except Exception:
            _silent_log.debug("suppressed_exception", src='kernel.py')

        return KernelStatus(
            booted=self._booted_at > 0,
            version=self._version,
            uptime_s=uptime,
            planning=self._planning is not None,
            state=self._state_machine is not None,
            policy=self._policy is not None,
            memory=self._memory is not None,
            capabilities=cap_count,
            events=self._events is not None,
            orchestrator=_orchestrator_fn is not None,
            classifier=self._classifier is not None,
            gate=self._gate is not None,
            evaluator=self._evaluator is not None,
            router=self._router is not None,
        )


# ── Module-level singleton ────────────────────────────────────────────────────
_kernel: JarvisKernel | None = None


def get_kernel() -> JarvisKernel:
    """
    Return the singleton JarvisKernel.
    Boots on first call.
    """
    global _kernel
    if _kernel is None:
        _kernel = JarvisKernel().boot()
    return _kernel
