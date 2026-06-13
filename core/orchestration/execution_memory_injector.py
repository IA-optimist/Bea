"""Runtime memory context injection for supervised mission execution.

Extracted from ExecutionMixin._execute_supervised — memory-injection phase.
Handles: ContinualMemory replay, AlignmentLayer check, CausalModule context,
ComprehensionChecker, UnifiedMemory recall, client profile, and context cap.

Returns enriched_goal (str), or None if AlignmentLayer blocks execution.
The caller is responsible for performing the MissionStatus.DONE transition on None.
"""
from __future__ import annotations

import asyncio
import structlog

from typing import Callable

from core.state import MissionStatus

log = structlog.get_logger(__name__)


async def inject_memory_context(
    goal: str,
    mid: str,
    mode: str,
    ctx,
    trace,
    enriched_goal: str,
    transition_fn: Callable,
) -> str | None:
    """Inject runtime memory context into enriched_goal.

    Returns:
        Updated enriched_goal string, or None if AlignmentLayer blocks execution
        (caller must handle transition to DONE).
    """
    # ── ContinualMemory: inject past experiences ───────────────────────────────
    try:
        from core.orchestration.continual_memory import ContinualMemory
        _cm = ContinualMemory()
        _experiences = await _cm.get_replay_batch(enriched_goal, n=3)
        if _experiences:
            _ctx_injection = _cm.build_context_injection(_experiences)
            enriched_goal = enriched_goal + "\n\n" + _ctx_injection
            log.info("continual_memory.injected", n=len(_experiences))
    except Exception as _cm_err:
        log.debug("continual_memory.inject_skipped", err=str(_cm_err)[:80])

    # ── AlignmentLayer: check action before execution ──────────────────────────
    try:
        from core.orchestration.alignment_layer import AlignmentLayer
        _al = AlignmentLayer()
        _al_decision = _al.check_action(enriched_goal, {"mode": mode, "mission_id": mid})
        if not _al_decision.allowed and not _al_decision.requires_confirmation:
            log.warning("alignment.blocked", reason=_al_decision.reasoning,
                        mission_id=mid)
            ctx.result = f"[BLOCKED BY ALIGNMENT] {_al_decision.reasoning}"
            transition_fn(ctx, MissionStatus.DONE,
                          result_len=len(ctx.result), retries=0,
                          duration_ms=0, confidence=0.0)
            return None  # Signal: alignment blocked — caller returns immediately
        if _al_decision.requires_confirmation:
            log.info("alignment.confirmation_required",
                     action=enriched_goal[:60], mission_id=mid)
            ctx.metadata["alignment_confirmation_required"] = True
            ctx.metadata["alignment_reason"] = _al_decision.reasoning
    except Exception as _al_err:
        log.debug("alignment.check_skipped", err=str(_al_err)[:80])

    # ── CausalModule: enrich goal with causal context ──────────────────────────
    try:
        from core.orchestration.causal_module import BeaMaxCausalIntegration
        _causal = BeaMaxCausalIntegration()
        _causal_ctx = _causal.get_causal_context(enriched_goal)
        if _causal_ctx and _causal_ctx.strip() and "No causal" not in _causal_ctx:
            enriched_goal = enriched_goal + "\n\n" + _causal_ctx
            log.info("causal_module.context_injected", mission_id=mid)
        try:
            _causal.update_graph_from_text(enriched_goal[:500])
        except Exception as _exc:
            log.warning("swallowed_exception", action="causal_graph_update",
                        exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
    except Exception as _causal_err:
        log.debug("causal_module.skipped", err=str(_causal_err)[:80])

    # ── ComprehensionChecker: verify goal is well-understood ───────────────────
    try:
        from core.orchestration.comprehension_checker import ComprehensionChecker
        _cc = ComprehensionChecker()
        _cc_report = await asyncio.wait_for(_cc.check(enriched_goal), timeout=5.0)
        if _cc_report and not _cc_report.get("understood", True):
            _clarification = _cc_report.get("clarification_needed", "")
            if _clarification:
                enriched_goal = (
                    enriched_goal + f"\n\n[COMPREHENSION NOTE] {_clarification}"
                )
                log.info("comprehension_checker.clarification_injected",
                         mission_id=mid)
    except Exception as _cc_err:
        log.debug("comprehension_checker.skipped", err=str(_cc_err)[:80])

    # ── UnifiedMemory: semantic recall before mission ──────────────────────────
    try:
        from core.orchestration.memory_system import UnifiedMemory
        _um = UnifiedMemory()
        _memories = await asyncio.wait_for(
            _um.recall(enriched_goal, top_k=3), timeout=3.0
        )
        if _memories:
            _mem_block = "\n".join(
                f"- {m['content'][:200]}"
                for m in _memories
                if m.get("content")
            )
            if _mem_block:
                enriched_goal = enriched_goal + f"\n\n[MEMORY RECALL]\n{_mem_block}"
                log.info("unified_memory.recalled", mission_id=mid,
                         n=len(_memories))
    except Exception as _um_err:
        log.debug("unified_memory.skipped", err=str(_um_err)[:80])

    # ── Client profile context ─────────────────────────────────────────────────
    try:
        from core.client_profile import ClientProfile as _CP
        _gl = goal.lower()
        _sector_map = {
            "jardin": "2f190993", "tonte": "2f190993", "tondeuse": "2f190993",
            "chauffage": "a08c93ad", "pompe": "a08c93ad", "pac": "a08c93ad",
            "ecommerce": "9ac01d10", "piece": "9ac01d10", "radiateur": "9ac01d10",
        }
        for _kw, _pid in _sector_map.items():
            if _kw in _gl:
                _p = _CP.load(_pid)
                if _p:
                    enriched_goal = _p.inject_context(enriched_goal)
                break
    except Exception:
        log.debug("swallowed_exception", exc_info=True)

    # ── Context cap (avoid overwhelming agents) ────────────────────────────────
    if len(enriched_goal) > 2000:
        enriched_goal = (
            enriched_goal[:2000] + "\n[...context truncated for performance...]"
        )
        log.debug("enriched_goal_capped", mission_id=mid)

    return enriched_goal
