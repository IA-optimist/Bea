"""
BEA MAX — Orchestration Bridge
====================================
Safe migration layer that routes mission operations through MetaOrchestrator
as the canonical authority, while preserving MissionSystem as a facade.

Design:
    - MissionSystem remains importable and callable (no breaking changes).
    - This bridge wraps MissionSystem calls and maps them to canonical types.
    - MetaOrchestrator is the lifecycle owner.
    - WorkflowGraph is available as an optional execution strategy.
    - Feature flag controls bridge activation.

Usage:
    from core.orchestration_bridge import (
        get_orchestration_bridge,
        submit_mission,
        get_mission_canonical,
        approve_mission,
        reject_mission,
    )

    # Submit through bridge (routes to canonical authority)
    result = submit_mission("Fix the auth module")

    # Get canonical view of any mission
    canonical = get_mission_canonical(mission_id)

Feature Flags:
    BEA_USE_CANONICAL_ORCHESTRATOR=true  → bridge active, MetaOrchestrator owns lifecycle
    BEA_USE_CANONICAL_ORCHESTRATOR=false → bridge passthrough, MissionSystem unchanged

No modifications to MissionSystem, MetaOrchestrator, or WorkflowGraph source code.
"""
from __future__ import annotations

import structlog
log = structlog.get_logger(__name__)

import os
import time
from typing import Any, Optional

try:
    import structlog
    log = structlog.get_logger(__name__)
except ImportError:
    log = structlog.get_logger(__name__)

from core.canonical_types import (
    CanonicalMissionStatus,
    CanonicalMissionContext,
    map_legacy_mission_status,
    map_legacy_risk_level,
    TransitionError,
)


# ═══════════════════════════════════════════════════════════════
# FEATURE FLAG
# ═══════════════════════════════════════════════════════════════

def _bridge_enabled() -> bool:
    """Check if canonical orchestration bridge is active.

    Default TRUE — matches convergence._use_canonical() default.
    Opt-out via BEA_USE_CANONICAL_ORCHESTRATOR=0|false|no.
    """
    val = os.environ.get("BEA_USE_CANONICAL_ORCHESTRATOR", "1").lower()
    return val not in ("0", "false", "no")


# ═══════════════════════════════════════════════════════════════
# BRIDGE CORE
# ═══════════════════════════════════════════════════════════════

class OrchestrationBridge:
    """
    Bridge that unifies MissionSystem and MetaOrchestrator under canonical types.

    When bridge is enabled:
        - submit_mission() creates missions in both systems, MetaOrchestrator owns lifecycle
        - get_mission_canonical() returns CanonicalMissionContext from any source
        - Status queries return canonical status mapped from whichever system has the mission

    When bridge is disabled (default):
        - All operations pass through to MissionSystem unchanged
        - Canonical mapping is still available for read operations
    """

    def __init__(self):
        self._canonical_missions: dict[str, CanonicalMissionContext] = {}
        # SQLite persistence — graceful degradation if unavailable
        try:
            from core.canonical_mission_store import CanonicalMissionStore
            self._store: Any = CanonicalMissionStore()
            # Warm in-memory cache from persisted state (restart safety)
            _stale_approval: list = []
            for ctx in self._store.load_all():
                self._canonical_missions[ctx.mission_id] = ctx
                if ctx.status == CanonicalMissionStatus.WAITING_APPROVAL:
                    _stale_approval.append(ctx)

            # KL-008: WAITING_APPROVAL missions cannot auto-resume after restart
            # because the MetaOrchestrator coroutine is lost. Transition them to
            # FAILED so the operator gets a clean, honest terminal state instead
            # of an orphaned WAITING_APPROVAL that will never resolve.
            for ctx in _stale_approval:
                try:
                    ctx.error = "server_restart_during_approval"
                    ctx.transition(CanonicalMissionStatus.FAILED)
                    self._store.save(ctx)
                    log.warning(
                        "bridge.stale_approval_failed",
                        mission_id=ctx.mission_id,
                        reason="server_restart_during_approval",
                    )
                except Exception as _kl008_err:
                    log.debug("bridge.stale_approval_fail_skip", err=str(_kl008_err)[:80])

            log.info(
                "bridge.store_loaded",
                missions_restored=len(self._canonical_missions),
                stale_approvals_failed=len(_stale_approval),
            )
        except Exception as exc:
            log.warning("bridge.store_unavailable", err=str(exc)[:120])
            self._store = None

    def _update_cache(self, ctx: CanonicalMissionContext) -> None:
        """Update in-memory cache, persist to SQLite, and record performance evidence."""
        _TERMINAL = {"COMPLETED", "FAILED", "CANCELLED"}
        prev = self._canonical_missions.get(ctx.mission_id)
        prev_terminal = prev is not None and prev.status.value in _TERMINAL
        new_terminal = ctx.status.value in _TERMINAL

        self._canonical_missions[ctx.mission_id] = ctx
        if self._store is not None:
            self._store.save(ctx)

        # Record performance evidence on first terminal transition only.
        # Fail-open: a recording error must never affect mission lifecycle.
        if new_terminal and not prev_terminal:
            try:
                self._record_performance_evidence(ctx)
            except Exception as _exc:
                log.warning("bridge.perf_record_error", err=str(_exc)[:80])

    def _record_performance_evidence(self, ctx: CanonicalMissionContext) -> None:
        """
        Write mission outcome to ModelPerformanceMemory.

        The model credited is the first entry in ctx.agents_selected (if available),
        falling back to the current MODEL_STRATEGY setting.
        Duration is estimated from created_at if available, otherwise 0.

        This record feeds the model selector's quality scoring loop.
        Evidence accumulates over real use — no synthetic data.
        """
        from core.model_intelligence.selector import get_model_performance
        import os as _os

        success = ctx.status.value == "COMPLETED"
        # Derive task_class from mission type or agent composition when available
        task_class = getattr(ctx, "mission_type", None) or "general"
        if task_class not in ("coding_task", "research_task", "planning_task",
                              "evaluation_task", "general"):
            task_class = "general"

        # Determine model credited.
        # NOTE: ctx.agents_selected stores AGENT names ("scout-research"), not LLM model IDs.
        # We derive model_id from the active LLM env vars instead, which is the correct entity.
        strategy = _os.environ.get("MODEL_STRATEGY", "anthropic")
        if strategy == "anthropic":
            model_id = _os.environ.get("ANTHROPIC_MODEL", "unknown")
        elif strategy == "openrouter":
            model_id = _os.environ.get("OPENROUTER_MODEL", "unknown")
        else:
            model_id = (
                _os.environ.get("ANTHROPIC_MODEL")
                or _os.environ.get("OPENROUTER_MODEL")
                or _os.environ.get("OPENAI_MODEL")
                or "unknown"
            )

        # Estimate duration from context metadata if available
        duration_ms: float = 0.0
        if hasattr(ctx, "created_at") and ctx.created_at:
            import time as _t
            try:
                duration_ms = (_t.time() - float(ctx.created_at)) * 1000
            except Exception as _exc:
                log.warning("swallowed_exception", action="compute_mission_duration_ms", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

        # quality: 1.0 on success, 0.0 on failure — populates avg_quality for A/B detection
        quality_score = 1.0 if success else 0.0

        get_model_performance().record(
            model_id=model_id,
            task_class=task_class,
            success=success,
            duration_ms=duration_ms,
            quality=quality_score,
        )
        log.info(
            "bridge.perf_recorded",
            mission_id=ctx.mission_id,
            model_id=model_id,
            success=success,
            quality=quality_score,
            duration_ms=int(duration_ms),
        )

        # ── A/B test auto-activation ──────────────────────────────────────────
        # After each evidence record, check if any task classes have ≥3 samples
        # per model with close quality scores → automatically start A/B tests.
        try:
            from core.model_intelligence.auto_update import get_model_auto_update
            updater = get_model_auto_update()
            candidates = updater.detect_ab_candidates()
            for cand in candidates:
                tc = cand["task_class"]
                if not updater.get_active_test(tc):
                    updater.start_ab_test(tc, cand["model_a"], cand["model_b"])
                    log.info(
                        "ab_test_auto_started",
                        mission_id=ctx.mission_id,
                        task_class=tc,
                        model_a=cand["model_a"],
                        model_b=cand["model_b"],
                        quality_diff=cand.get("quality_diff"),
                        samples_a=cand.get("samples_a"),
                        samples_b=cand.get("samples_b"),
                    )
        except Exception as _ab_exc:
            log.debug("ab_test_auto_skip", err=str(_ab_exc)[:80])

    # ── Mission Submission ────────────────────────────────────────────────────

    def submit_mission(self, user_input: str) -> dict:
        """
        Submit a mission through the bridge.

        When bridge enabled:
            1. MissionSystem.submit() for planning/advisory (it's good at that)
            2. Map result to CanonicalMissionContext
            3. Track canonical lifecycle

        When bridge disabled:
            Passthrough to MissionSystem.submit()

        Returns dict with canonical mission context. Never raises.
        """
        try:
            from core.mission_system import get_mission_system
            ms = get_mission_system()
            result = ms.submit(user_input)

            # Always create canonical view (even when bridge disabled)
            canonical = self._ms_result_to_canonical(result)
            self._update_cache(canonical)

            if _bridge_enabled():
                log.info(
                    "bridge.submit_canonical",
                    mission_id=canonical.mission_id,
                    status=canonical.status.value,
                    risk=canonical.risk_level.value,
                )

            return {
                "ok": True,
                "mission_id": canonical.mission_id,
                "canonical_status": canonical.status.value,
                "canonical_risk": canonical.risk_level.value,
                "legacy_status": result.status if hasattr(result, "status") else "UNKNOWN",
                "bridge_active": _bridge_enabled(),
                "context": canonical.to_dict(),
            }

        except Exception as e:
            log.debug("bridge.submit_failed", err=str(e)[:100])
            return {
                "ok": False,
                "error": str(e)[:200],
                "bridge_active": _bridge_enabled(),
            }

    def get_mission_canonical(self, mission_id: str) -> Optional[CanonicalMissionContext]:
        """
        Get canonical view of a mission from any source system.

        Checks:
            1. Bridge's canonical cache
            2. MissionSystem
            3. MetaOrchestrator

        Returns CanonicalMissionContext or None. Never raises.
        """
        # Status ordering: READY is the initial bridge state — always check MetaOrchestrator
        # for a live update so that execution state (RUNNING, DONE, FAILED) propagates back.
        # NOTE: MetaOrchestrator "DONE" maps to CanonicalMissionStatus.COMPLETED (.value="COMPLETED")
        # Include both "DONE" and "COMPLETED" to handle both legacy and canonical status strings.
        _TERMINAL_STATUSES = {"DONE", "COMPLETED", "FAILED", "CANCELLED", "REJECTED"}
        _LIVE_STATUSES = {"RUNNING", "REVIEW", "PLANNED", "DONE", "COMPLETED", "FAILED", "CANCELLED", "REJECTED"}

        cached = self._canonical_missions.get(mission_id)

        # Always try MetaOrchestrator first if the cached status is still early-stage
        if cached is None or cached.status.value not in _TERMINAL_STATUSES:
            try:
                from core.meta_orchestrator import get_meta_orchestrator
                mo = get_meta_orchestrator()
                ctx = mo.get_mission(mission_id)
                if ctx:
                    mo_canonical = self._mo_context_to_canonical(ctx)
                    # Promote cache if MetaOrchestrator has a more advanced status
                    if mo_canonical.status.value in _LIVE_STATUSES:
                        self._update_cache(mo_canonical)
                        return mo_canonical
            except Exception as _exc:
                log.warning("swallowed_exception", action="meta_orchestrator_canonical_fetch", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

        # 1. Return cache if available
        if cached is not None:
            return cached

        # 2. Check MissionSystem
        try:
            from core.mission_system import get_mission_system
            ms = get_mission_system()
            result = ms.get_mission(mission_id)
            if result:
                canonical = self._ms_result_to_canonical(result)
                self._update_cache(canonical)
                return canonical
        except Exception as _exc:
            log.warning("swallowed_exception", action="mission_system_canonical_fetch", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

        return None

    def approve_mission(self, mission_id: str, note: str = "") -> dict:
        """
        Approve a mission through the bridge.

        Three-step sequence (all fail-open):
        1. Legacy MissionSystem.approve()        — legacy status
        2. MetaOrchestrator.resolve_approval()   — resumes real execution
        3. Canonical status WAITING_APPROVAL → READY + persist to SQLite
        """
        try:
            # 1. Legacy system
            from core.mission_system import get_mission_system
            ms = get_mission_system()
            result = ms.approve(mission_id, note=note)

            # 2. MetaOrchestrator — resumes actual execution for missions in AWAITING_APPROVAL
            try:
                from core.meta_orchestrator import get_meta_orchestrator
                _orch = get_meta_orchestrator()
                import asyncio
                _coro = _orch.resolve_approval(mission_id, granted=True, reason=note or "Approved via bridge")
                # Schedule the coroutine on the running event loop (non-blocking)
                try:
                    _loop = asyncio.get_running_loop()
                    _loop.create_task(_coro)
                except RuntimeError:
                    # No running loop — create one in a thread
                    import threading
                    def _run():
                        _l = asyncio.new_event_loop()
                        try:
                            _l.run_until_complete(_coro)
                        finally:
                            _l.close()
                    threading.Thread(target=_run, daemon=True).start()
                log.info("bridge.approve_meta_resolved", mission_id=mission_id)
            except Exception as _me:
                log.debug("bridge.approve_meta_skip", err=str(_me)[:80])

            # 3. Canonical state + persist
            canonical = self._canonical_missions.get(mission_id)
            if canonical and canonical.status == CanonicalMissionStatus.WAITING_APPROVAL:
                try:
                    canonical.transition(CanonicalMissionStatus.READY)
                    self._update_cache(canonical)
                except TransitionError as _exc:
                    log.warning("swallowed_exception", action="approve_canonical_transition",
                                exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

            log.info("bridge.approve_ok", mission_id=mission_id, note=note[:80])
            return {
                "ok": True,
                "mission_id": mission_id,
                "canonical_status": canonical.status.value if canonical else "UNKNOWN",
                "legacy_status": result.status if result and hasattr(result, "status") else "UNKNOWN",
            }
        except Exception as e:
            log.debug("bridge.approve_failed", err=str(e)[:100])
            return {"ok": False, "error": str(e)[:200]}

    def reject_mission(self, mission_id: str, note: str = "") -> dict:
        """
        Reject a mission through the bridge.

        Three-step sequence (all fail-open):
        1. Legacy MissionSystem.reject()
        2. MetaOrchestrator.resolve_approval(granted=False)
        3. Canonical status → CANCELLED + persist to SQLite
        """
        try:
            # 1. Legacy system
            from core.mission_system import get_mission_system
            ms = get_mission_system()
            ms.reject(mission_id, note=note)

            # 2. MetaOrchestrator — closes the approval gate
            try:
                from core.meta_orchestrator import get_meta_orchestrator
                _orch = get_meta_orchestrator()
                import asyncio
                _coro = _orch.resolve_approval(mission_id, granted=False,
                                       reason=note or "Rejected via bridge")
                try:
                    _loop = asyncio.get_running_loop()
                    _loop.create_task(_coro)
                except RuntimeError:
                    import threading
                    def _run():
                        _l = asyncio.new_event_loop()
                        try:
                            _l.run_until_complete(_coro)
                        finally:
                            _l.close()
                    threading.Thread(target=_run, daemon=True).start()
                log.info("bridge.reject_meta_resolved", mission_id=mission_id)
            except Exception as _me:
                log.debug("bridge.reject_meta_skip", err=str(_me)[:80])

            # 3. Canonical state + persist
            canonical = self._canonical_missions.get(mission_id)
            if canonical and not canonical.status.is_terminal:
                try:
                    canonical.transition(CanonicalMissionStatus.CANCELLED)
                    self._update_cache(canonical)
                except TransitionError as _exc:
                    log.warning("swallowed_exception", action="reject_canonical_transition",
                                exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

            log.info("bridge.reject_ok", mission_id=mission_id, note=note[:80])
            return {
                "ok": True,
                "mission_id": mission_id,
                "canonical_status": canonical.status.value if canonical else "UNKNOWN",
            }
        except Exception as e:
            log.debug("bridge.reject_failed", err=str(e)[:100])
            return {"ok": False, "error": str(e)[:200]}

    def list_missions(self, status_filter: str | None = None, limit: int = 20) -> list[dict]:
        """Alias for list_missions_canonical — used by API routes."""
        # When filtering by status, fetch a large pool first so the status filter
        # is applied to all missions, not just the most-recent `limit` ones.
        fetch_limit = limit if not status_filter else max(limit * 20, 500)
        missions = self.list_missions_canonical(limit=fetch_limit)
        if status_filter:
            missions = [m for m in missions if m.get("status") == status_filter.upper()]
        return missions[:limit]

    def list_missions_canonical(self, limit: int = 20) -> list[dict]:
        """
        List all known missions in canonical form.
        Merges from bridge cache, MissionSystem, and MetaOrchestrator.
        Never raises.
        """
        missions = {}

        # From canonical cache
        for mid, ctx in self._canonical_missions.items():
            missions[mid] = ctx.to_dict()

        # From MissionSystem
        try:
            from core.mission_system import get_mission_system
            ms = get_mission_system()
            for result in ms.list_missions(limit=limit):
                if result.mission_id not in missions:
                    canonical = self._ms_result_to_canonical(result)
                    missions[result.mission_id] = canonical.to_dict()
        except Exception as _exc:
            log.warning("swallowed_exception", action="list_missions_canonical_merge", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

        # From MetaOrchestrator
        try:
            from core.meta_orchestrator import get_meta_orchestrator
            mo = get_meta_orchestrator()
            status = mo.get_status()
            for ctx_dict in status.get("active_missions", []):
                mid = ctx_dict.get("mission_id", "")
                if mid and mid not in missions:
                    missions[mid] = {
                        "mission_id": mid,
                        "goal": ctx_dict.get("goal", ""),
                        "status": map_legacy_mission_status(
                            ctx_dict.get("status", "CREATED"), "meta_orchestrator"
                        ).value,
                        "source_system": "meta_orchestrator",
                    }
        except Exception as _exc:
            log.warning("swallowed_exception", action="mission_status_breakdown", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

        # Sort by most recent
        result_list = sorted(missions.values(), key=lambda x: x.get("updated_at", 0), reverse=True)
        return result_list[:limit]

    def get_status(self) -> dict:
        """
        Bridge status summary.
        """
        return {
            "bridge_enabled": _bridge_enabled(),
            "canonical_missions_tracked": len(self._canonical_missions),
            "status_counts": self._count_statuses(),
        }

    def _count_statuses(self) -> dict:
        counts: dict[str, int] = {}
        for ctx in self._canonical_missions.values():
            s = ctx.status.value
            counts[s] = counts.get(s, 0) + 1
        return counts

    # ── Conversion Helpers ────────────────────────────────────────────────────

    def _ms_result_to_canonical(self, result: Any) -> CanonicalMissionContext:
        """Convert MissionSystem MissionResult → CanonicalMissionContext."""
        status_str = result.status if isinstance(result.status, str) else result.status.value
        canonical_status = map_legacy_mission_status(status_str, "mission_system")
        canonical_risk = map_legacy_risk_level(
            getattr(result, "plan_risk", "LOW"), "state"
        )

        return CanonicalMissionContext(
            mission_id=result.mission_id,
            goal=result.user_input,
            status=canonical_status,
            risk_level=canonical_risk,
            intent=result.intent if isinstance(result.intent, str) else getattr(result.intent, "value", str(result.intent)),
            domain=getattr(result, "domain", "general"),
            plan_summary=getattr(result, "plan_summary", ""),
            agents=list(getattr(result, "agents_selected", [])),
            error=getattr(result, "error", ""),
            result=getattr(result, "final_output", ""),
            source_system="mission_system",
            created_at=getattr(result, "created_at", time.time()),
            updated_at=getattr(result, "updated_at", time.time()),
            metadata={
                "advisory_score": getattr(result, "advisory_score", 0),
                "advisory_decision": getattr(result, "advisory_decision", ""),
                "risk_score": getattr(result, "risk_score", 0),
                "complexity": getattr(result, "complexity", "medium"),
            },
        )

    def _mo_context_to_canonical(self, ctx: Any) -> CanonicalMissionContext:
        """Convert MetaOrchestrator MissionContext → CanonicalMissionContext."""
        status_str = ctx.status if isinstance(ctx.status, str) else ctx.status.value
        canonical_status = map_legacy_mission_status(status_str, "meta_orchestrator")

        return CanonicalMissionContext(
            mission_id=ctx.mission_id,
            goal=ctx.goal,
            status=canonical_status,
            intent="",
            domain="general",
            result=ctx.result or "",
            error=ctx.error or "",
            source_system="meta_orchestrator",
            created_at=ctx.created_at,
            updated_at=ctx.updated_at,
            metadata=ctx.metadata if hasattr(ctx, "metadata") else {},
        )


# ═══════════════════════════════════════════════════════════════
# SINGLETON + MODULE-LEVEL HELPERS
# ═══════════════════════════════════════════════════════════════

_bridge: OrchestrationBridge | None = None


def get_orchestration_bridge() -> OrchestrationBridge:
    """Return singleton OrchestrationBridge instance."""
    global _bridge
    if _bridge is None:
        _bridge = OrchestrationBridge()
        try:
            log.info("orchestration_bridge.created", enabled=_bridge_enabled())
        except Exception as _exc:
            log.warning("swallowed_exception", action="bridge_creation_log", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
    return _bridge


def submit_mission(user_input: str) -> dict:
    """Convenience: submit mission through bridge."""
    return get_orchestration_bridge().submit_mission(user_input)


def get_mission_canonical(mission_id: str) -> Optional[CanonicalMissionContext]:
    """Convenience: get canonical mission context."""
    return get_orchestration_bridge().get_mission_canonical(mission_id)


def approve_mission(mission_id: str, note: str = "") -> dict:
    """Convenience: approve mission through bridge."""
    return get_orchestration_bridge().approve_mission(mission_id, note)


def reject_mission(mission_id: str, note: str = "") -> dict:
    """Convenience: reject mission through bridge."""
    return get_orchestration_bridge().reject_mission(mission_id, note)
