"""
JARVIS MAX — Mission System v1
Point d'entrée unique pour soumettre une mission à Jarvis.

Flux complet :
  1. L'utilisateur soumet une mission en langage naturel
  2. MissionSystem analyse l'intention et crée un plan structuré
  3. Shadow Advisor évalue le plan (risques, blocages, score)
  4. Selon le mode (MANUAL/SUPERVISED/AUTO), validation ou auto-approbation
  5. Les actions concrètes sont ajoutées à ActionQueue
  6. Chaque action est exécutée selon le mode

Structure d'une mission :
  MissionPlan    : le plan proposé par Jarvis (sans LLM, analyse rapide)
  MissionResult  : résultat complet avec advisory, actions, statut
  MissionStatus  : cycle de vie de la mission

Persistance : SQLite (workspace/jarvismax.db) avec fallback JSON
"""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import asdict
from pathlib import Path
import structlog

log = structlog.get_logger()

_STORAGE    = Path("workspace/missions.json")
_MAX_STORED = 200

from core.mission_analysis import (
    _RISK_ORDER,
    CAPABILITY_DEMO as CAPABILITY_DEMO,
    MissionIntent as MissionIntent,
    classify_action as classify_action,
    compute_complexity as compute_complexity,
    compute_confidence_score as compute_confidence_score,
    compute_risk_score as compute_risk_score,
    detect_intent as detect_intent,
    evaluate_approval as evaluate_approval,
    is_capability_query as is_capability_query,
    risk_score_to_level as risk_score_to_level,
)
# ── Statuts de mission ────────────────────────────────────────────────────────
# SINGLE SOURCE: core/state.py — imported here for backward compatibility
from core.state import MissionStatus  # noqa: F811

from core.mission_models import (
    MissionPlan as MissionPlan,
    MissionResult as MissionResult,
    MissionStep as MissionStep,
)
# ── Mission System ────────────────────────────────────────────────────────────

class MissionSystem:
    """
    Système de mission principal de JarvisMax.

    Usage :
        ms = MissionSystem()
        result = ms.submit("Crée un rapport d'analyse de ce code")
        print(result.summary_line())
        # Si validation requise : ms.approve(result.mission_id)
    """

    def __init__(
        self,
        storage: Path|str = _STORAGE,
        action_queue=None,
        mode_system=None,
        goal_manager=None,
    ):
        self._path    = Path(storage)
        self._missions: dict[str, MissionResult] = {}
        self._aq  = action_queue    # ActionQueue (lazy import si None)
        self._ms  = mode_system     # ModeSystem (lazy import si None)
        self._gm  = goal_manager    # GoalManager (lazy import si None)
        self._use_sqlite: bool = False
        # Track mission_id → goal_id mapping
        self._mission_goals: dict[str, str] = {}
        self._load()

    # ── API principale ────────────────────────────────────────────────────────

    def submit(self, user_input: str) -> MissionResult:
        """
        Soumet une mission en langage naturel.

        1. Analyse l'intention
        2. Crée un plan structuré
        3. Évalue via shadow advisor (si dispo)
        4. Crée les actions dans ActionQueue
        5. Selon le mode, auto-approuve ou met en attente

        Retourne un MissionResult immédiatement (non bloquant).
        """
        mission_id = str(uuid.uuid4())[:12]
        # Generate trace_id for observability
        try:
            from core.observability.event_envelope import generate_trace_id, set_trace, get_event_collector
            _trace_id = generate_trace_id()
            set_trace(_trace_id, mission_id)
            get_event_collector().emit_quick("orchestrator", "status_update",
                {"action": "mission_submitted", "user_input": user_input[:100]})
        except Exception:
            _trace_id = ""
        intent     = detect_intent(user_input)

        # Détecter le domaine
        domain = "general"
        preferred_agents: list[str] = []
        try:
            from core.domain_router import get_domain_router
            dr = get_domain_router()
            route_info = dr.route(user_input)
            domain = route_info["domain"]
            preferred_agents = route_info["preferred_agents"]
        except Exception as _exc:
            log.debug("silent_exception_caught", err=str(_exc)[:120], location="mission_system:domain_route")

        log.info("mission_submitted", id=mission_id, intent=intent,
                 domain=domain, input=user_input[:60])

        # Créer le résultat initial
        result = MissionResult(
            mission_id=mission_id,
            user_input=user_input,
            intent=intent,
            status=MissionStatus.ANALYZING,
            domain=domain,
        )
        self._missions[mission_id] = result
        self._save()

        # ── Lifecycle: mission_received ───────────────────────────────────
        try:
            from core.lifecycle_tracker import get_lifecycle_tracker
            get_lifecycle_tracker().start(mission_id)
        except Exception as _exc:
            log.debug("silent_exception_caught", err=str(_exc)[:120], location="mission_system:521")

        # 1. Construire le plan
        plan = self._build_plan(user_input, intent)
        result.plan_summary = plan.summary
        result.plan_steps   = [asdict(s) for s in plan.steps]
        result.plan_risk    = plan.estimated_risk

        # ── Lifecycle: plan_generated ─────────────────────────────────────
        try:
            from core.lifecycle_tracker import get_lifecycle_tracker
            get_lifecycle_tracker().record(mission_id, "plan_generated")
        except Exception as _exc:
            log.debug("silent_exception_caught", err=str(_exc)[:120], location="mission_system:534")

        # 1b. Score numérique 0-10 (Phase 4) + complexity score
        num_score         = compute_risk_score(user_input, result.plan_steps)
        result.risk_score = num_score
        numeric_level     = risk_score_to_level(num_score)
        result.complexity = compute_complexity(user_input, num_score)

        # Classifier le type de mission (taxonomy v2)
        _mission_type = ""
        try:
            from memory.decision_memory import classify_mission_type as _clf_mt
            _mission_type = _clf_mt(user_input, result.complexity)
        except Exception as _exc:
            log.debug("silent_exception_caught", err=str(_exc)[:120], location="mission_system:548")

        # 1c. Sélection agents (AgentSelector V1) — piloté par mission_type + complexity
        _ALL_AGENTS = [
            "scout-research", "map-planner", "shadow-advisor",
            "forge-builder", "lens-reviewer", "vault-memory", "pulse-ops",
        ]
        try:
            from agents.crew import get_agent_selector
            selector = get_agent_selector()
            selected = selector.select_agents(
                user_input,
                risk_level=plan.estimated_risk,
                domain=domain,
                mission_type=_mission_type,
                preferred_agents=preferred_agents,
                complexity=result.complexity,
            )
            result.agents_selected = selected
            # ── Lifecycle: agents_selected ────────────────────────────────
            try:
                from core.lifecycle_tracker import get_lifecycle_tracker
                get_lifecycle_tracker().record(mission_id, "agents_selected")
            except Exception as _exc:
                log.debug("silent_exception_caught", err=str(_exc)[:120], location="mission_system:572")
        except Exception:
            selected = []

        # Initialiser decision_trace (DQ v2)
        _skipped = [a for a in _ALL_AGENTS if a not in result.agents_selected]
        result.decision_trace = {
            "mission_type":       _mission_type,
            "complexity":         result.complexity,
            "risk_score":         num_score,
            "confidence_score":   0.0,
            "selected_agents":    list(result.agents_selected),
            "skipped_agents":     _skipped,
            "approval_mode":      "",    # rempli après
            "approval_decision":  "",    # rempli après
            "approval_reason":    "",    # rempli après
            "final_output_source": "unknown",
            "fallback_level_used": 0,
            "latency_ms":         0,
        }
        if _trace_id:
            result.decision_trace["trace_id"] = _trace_id

        # HIGH (7-10) → AWAITING_APPROVAL en mode SUPERVISED (pas BLOCKED)
        mode_sys = self._get_mode_system()
        if (
            mode_sys.get_mode().value == "SUPERVISED"
            and numeric_level == "HIGH"
        ):
            result.status = MissionStatus.AWAITING_APPROVAL
            result.error  = (
                f"Mission en attente d'approbation — risk_score={num_score}/10 (HIGH). "
                "Action risquée : validation humaine requise."
            )
            log.warning(
                "mission_awaiting_approval_high_risk",
                id=mission_id, risk_score=num_score, level=numeric_level,
            )
            self._save_mission(result)
            return result

        # 2. Évaluation shadow advisor (depuis metadata si disponible)
        advisory_data = self._evaluate_advisory(plan, user_input)
        result.advisory_score    = advisory_data.get("final_score", 5.0)
        result.advisory_decision = advisory_data.get("decision", "IMPROVE")
        result.advisory_issues   = advisory_data.get("blocking_issues", [])
        result.advisory_risks    = advisory_data.get("risks", [])
        result.advisory_text     = advisory_data.get("justification", "")

        # 3. Vérifier shadow gate
        from core.shadow_gate import ShadowGate
        gate = ShadowGate()
        gate_result = gate.check_advisory(advisory_data)

        if gate_result.is_blocked():
            result.status = MissionStatus.AWAITING_APPROVAL
            result.error  = gate_result.reason
            log.warning("mission_needs_approval", id=mission_id, reason=gate_result.reason[:100])
            self._save_mission(result)
            return result

        # 4. Créer les actions dans ActionQueue
        action_ids = self._create_actions(plan, mission_id)
        result.action_ids = action_ids

        # 5. Selon le mode → auto ou validation (DQ v2 — evaluate_approval centralisé)
        mode_sys = self._get_mode_system()
        shadow   = result.advisory_score
        goal_action_type, _ = classify_action(user_input)

        # Évaluation approbation centralisée (DQ v2)
        _mode_val = mode_sys.get_mode().value
        _appr = evaluate_approval(num_score, result.complexity, _mode_val)
        # Le hook SUPERVISED write/MEDIUM force pending même si evaluate_approval dit auto
        if (
            _mode_val == "SUPERVISED"
            and (
                goal_action_type == "write"
                or _RISK_ORDER.index(plan.estimated_risk) >= _RISK_ORDER.index("MEDIUM")
            )
        ):
            _appr = {
                "decision": "pending",
                "reason": (
                    f"Mode SUPERVISED, action={goal_action_type}, "
                    f"plan_risk={plan.estimated_risk} — validation requise"
                ),
                "auto_approved": False,
            }

        auto = _appr["auto_approved"]

        result.decision_trace["approval_mode"]     = _mode_val
        result.decision_trace["approval_decision"] = _appr["decision"]
        result.decision_trace["approval_reason"]   = _appr["reason"][:300]

        if auto:
            result.status = MissionStatus.APPROVED
            self._auto_approve_actions(action_ids, shadow)
            log.info("mission_auto_approved", id=mission_id, mode=mode_sys.get_mode())
        else:
            # Check if any planned actions actually require approval
            # If no blocking actions exist, auto-approve to prevent deadlock
            has_blocking_actions = self._has_approval_required_actions(action_ids)
            if has_blocking_actions:
                result.status              = MissionStatus.PENDING_VALIDATION
                result.requires_validation = True
                log.info("mission_pending_validation", id=mission_id, blocking_actions=True)
            else:
                # No actions need approval — auto-approve to prevent deadlock
                result.status = MissionStatus.APPROVED
                self._auto_approve_actions(action_ids, shadow)
                log.info(
                    "mission_auto_approved_no_blocking_actions",
                    id=mission_id,
                    reason="No actions require manual approval — deadlock prevention",
                )

        result.updated_at = time.time()
        self._save_mission(result)

        # Create a Goal in GoalManager (Mission 3)
        try:
            gm = self._get_goal_manager()
            if gm is not None:
                goal = gm.enqueue(
                    text=user_input[:200],
                    mode="auto" if auto else "manual",
                    tags=[intent.value.lower()],
                )
                self._mission_goals[mission_id] = goal.id
        except Exception as exc:
            log.warning("mission_goal_create_failed", err=str(exc))

        return result

    def set_final_output(self, mission_id: str, text: str) -> None:
        """Stocke le final_output d'une mission. Fail-open."""
        r = self._missions.get(mission_id)
        if r and text and text.strip():
            r.final_output = text  # no truncation — full response preserved
            r.updated_at   = time.time()
            self._save_mission(r)

    def approve(self, mission_id: str, note: str = "") -> MissionResult|None:
        """Approuve une mission en attente de validation."""
        r = self._missions.get(mission_id)
        if not r or r.status != MissionStatus.PENDING_VALIDATION:
            return r

        aq = self._get_action_queue()
        for aid in r.action_ids:
            aq.approve(aid, note=note)

        r.status     = MissionStatus.APPROVED
        r.updated_at = time.time()
        self._save_mission(r)
        log.info("mission_approved", id=mission_id)
        return r

    def complete(self, mission_id: str, result_text: str = "") -> MissionResult|None:
        """Marque une mission comme terminée.

        Garde-fou : une mission en PENDING_VALIDATION ne peut pas être marquée
        DONE automatiquement — elle reste bloquée jusqu'à approbation explicite.
        Si la mission est APPROVED mais qu'aucune écriture réelle n'a eu lieu
        (classify_action détecte un goal write sans preuve d'exécution), le
        statut sera PLAN_ONLY.
        """
        r = self._missions.get(mission_id)
        if not r:
            return None

        # Garde-fou 1 : jamais DONE sans approbation
        if r.status == MissionStatus.PENDING_VALIDATION:
            log.warning(
                "complete_blocked_pending_validation",
                id=mission_id,
                hint="Mission needs explicit approval before completion",
            )
            return r  # statut inchangé

        # Garde-fou 2 : si goal implique écriture mais mission non APPROVED/EXECUTING
        # → marquer PLAN_ONLY plutôt que DONE
        goal_action_type, _ = classify_action(r.user_input)
        if (
            goal_action_type == "write"
            and r.status not in {MissionStatus.APPROVED, MissionStatus.EXECUTING}
        ):
            r.status     = MissionStatus.PLAN_ONLY
            r.updated_at = time.time()
            log.warning(
                "complete_plan_only",
                id=mission_id,
                status_was=str(r.status),
                hint="Write mission completed with no execution evidence",
            )
            self._save_mission(r)
            return r

        r.status     = MissionStatus.DONE
        r.updated_at = time.time()

        # Garde-fou final_output : toujours présent
        if not r.final_output:
            r.final_output = result_text or r.summary or r.plan_summary or ""  # no truncation
        if not r.summary:
            r.summary = (r.plan_summary or r.final_output or "")[:500]

        self._save_mission(r)
        # Update goal
        try:
            gm = self._get_goal_manager()
            goal_id = self._mission_goals.get(mission_id)
            if gm and goal_id:
                gm.complete(goal_id, result=result_text or "Mission terminée")
        except Exception as _exc:
            log.debug("silent_exception_caught", err=str(_exc)[:120], location="mission_system:789")

        # ── Mission performance signal (fail-open) ──────────────────────────
        _agents = getattr(r, "agents_selected", []) or []
        _tools = []
        _mission_type_str = str(getattr(r, "intent", "unknown"))
        _complexity_str = getattr(r, "complexity", "medium") or "medium"
        _plan_steps_count = len(getattr(r, "plan_steps", []) or [])
        try:
            _dt = getattr(r, "decision_trace", {}) or {}
            _tools = _dt.get("available_tools", [])
            if _dt.get("mission_type"):
                _mission_type_str = _dt["mission_type"]
        except Exception as _exc:
            log.debug("silent_exception_caught", err=str(_exc)[:120], location="mission_system:803")
        _duration = (r.updated_at - getattr(r, "created_at", r.updated_at))
        try:
            from core.mission_performance_tracker import (
                get_mission_performance_tracker, MissionOutcome,
            )
            get_mission_performance_tracker().record(MissionOutcome(
                mission_id=mission_id,
                goal=r.user_input[:200],
                mission_type=_mission_type_str,
                success=True,
                duration_s=max(0, _duration),
                agents_used=_agents,
                tools_used=_tools,
                plan_steps=_plan_steps_count,
                complexity=_complexity_str,
                risk_score=getattr(r, "risk_score", 0) or 0,
            ))
        except Exception as _mpt_err:
            log.debug("mission_perf_track_skipped", err=str(_mpt_err)[:60])

        # ── Knowledge ingestion (fail-open) ───────────────────────────────
        try:
            from core.knowledge_ingestion import ingest_mission_outcome
            ingest_mission_outcome(
                mission_id=mission_id,
                goal=r.user_input[:300],
                mission_type=_mission_type_str,
                success=True,
                agents_used=_agents,
                tools_used=_tools,
                plan_steps=_plan_steps_count,
                complexity=_complexity_str,
                duration_s=max(0, _duration),
            )
        except Exception as _ki_err:
            log.debug("knowledge_ingestion_skipped", err=str(_ki_err)[:60])
        # ── Lifecycle: results_evaluated ──────────────────────────────
        try:
            from core.lifecycle_tracker import get_lifecycle_tracker
            get_lifecycle_tracker().record(mission_id, "results_evaluated")
        except Exception as _exc:
            log.debug("silent_exception_caught", err=str(_exc)[:120], location="mission_system:845")

        # ── Post-mission evaluation (fail-open) ─────────────────────────
        try:
            from core.execution_engine import evaluate_mission, store_evaluation
            _eval = evaluate_mission(
                mission_id=mission_id,
                success=True,
                final_output=r.final_output or "",
                goal=r.user_input[:200],
                agents_used=_agents,
                tools_used=_tools,
                duration_s=max(0, _duration),
                plan_steps=_plan_steps_count,
            )
            store_evaluation(_eval)
        except Exception as _eval_err:
            log.debug("mission_eval_skipped", err=str(_eval_err)[:60])
        # ── end post-mission evaluation ───────────────────────────────────

        # ── Mission memory: cross-mission learning (fail-open) ─────────
        try:
            from core.mission_memory import get_mission_memory
            get_mission_memory().record_outcome(
                mission_type=_mission_type_str,
                agents=_agents,
                tools=_tools,
                plan_steps=_plan_steps_count,
                success=True,
                duration_s=max(0, _duration),
                complexity=_complexity_str,
            )
        except Exception as _mm_err:
            log.debug("mission_memory_skipped", err=str(_mm_err)[:60])
        # ── Lifecycle: memory_updated ────────────────────────────────
        try:
            from core.lifecycle_tracker import get_lifecycle_tracker
            get_lifecycle_tracker().record(mission_id, "memory_updated")
        except Exception as _exc:
            log.debug("silent_exception_caught", err=str(_exc)[:120], location="mission_system:884")

        # ── Memory Facade: unified index (P5, additive) ──────────────
        try:
            from core.memory_facade import get_memory_facade
            _facade = get_memory_facade()
            _facade.store(
                content=(
                    f"Mission {mission_id}: {r.user_input[:200]}\n"
                    f"Type: {_mission_type_str} | Complexity: {_complexity_str}\n"
                    f"Agents: {', '.join(_agents[:5])}\n"
                    f"Tools: {', '.join(_tools[:5])}\n"
                    f"Duration: {max(0, _duration):.1f}s | Success: True"
                ),
                content_type="mission_outcome",
                tags=[_mission_type_str, _complexity_str, "success"],
                metadata={
                    "mission_id": mission_id,
                    "agents": _agents,
                    "tools": _tools,
                    "duration_s": max(0, _duration),
                    "plan_steps": _plan_steps_count,
                    "risk_score": getattr(r, "risk_score", 0) or 0,
                },
            )
        except Exception as _mf_err:
            log.debug("memory_facade_store_skipped", err=str(_mf_err)[:60])

        # ── Economic signals + workflow template recording (fail-open) ─
        try:
            from core.operating_primitives import compute_economics, get_workflow_store
            _econ = compute_economics(
                goal=r.user_input[:200],
                mission_type=_mission_type_str,
                complexity=_complexity_str,
                plan_steps=len(getattr(r, 'agents_selected', []) or []),
                risk_score=getattr(r, 'risk_score', 0) or 0,
            )
            r.decision_trace["economics"] = _econ.to_dict()
            # Record successful workflow template (this block is on the success path)
            _phases = ["research", "execution", "verification"]
            get_workflow_store().record_successful_workflow(
                _mission_type_str, _tools, _phases
            )
        except Exception as _exc:
            log.debug("silent_exception_caught", err=str(_exc)[:120], location="mission_system:930")

        # ── Auto-detect improvement opportunities (fail-open) ────────
        try:
            from core.safety_controls import is_proposals_enabled
            if is_proposals_enabled():
                from core.improvement_detector import detect_improvements
                detect_improvements(dry_run=False)
        except Exception as _det_err:
            log.debug("auto_detection_skipped", err=str(_det_err)[:60])

        # ── Lifecycle: proposals_checked + finish ────────────────────
        try:
            from core.lifecycle_tracker import get_lifecycle_tracker
            _lt = get_lifecycle_tracker()
            _lt.record(mission_id, "proposals_checked")
            _lt.finish(mission_id)
        except Exception as _exc:
            log.debug("silent_exception_caught", err=str(_exc)[:120], location="mission_system:948")
        # ── Mission audit trail (fail-open) ──────────────────────────────
        try:
            from core.governance import log_mission_event
            log_mission_event(
                mission_id=mission_id,
                event="mission_completed",
                detail=f"type={_mission_type_str}, agents={len(_agents)}, duration={_duration:.0f}s",
                danger_level="safe",
            )
        except Exception as _exc:
            log.debug("silent_exception_caught", err=str(_exc)[:120], location="mission_system:959")

        # ── Event triggers: notify workflow runtime (fail-open) ──────────
        try:
            from core.workflow_runtime import get_event_manager
            get_event_manager().fire_event("mission_completed", {
                "mission_id": mission_id,
                "mission_type": _mission_type_str,
                "success": True,
            })
        except Exception as _exc:
            log.debug("silent_exception_caught", err=str(_exc)[:120], location="mission_system:970")

        # ── Budget: record mission cost signal (fail-open) ───────────────
        try:
            from core.business_pipeline import get_budget_tracker
            _bt = get_budget_tracker()
            _bt.record(
                category="mission_cost",
                amount=-round(max(0, _duration) / 60 * 0.1, 2),  # heuristic: ~$0.10/min
                description=f"Mission: {r.user_input[:80]}",
                mission_id=mission_id,
            )
        except Exception as _exc:
            log.debug("silent_exception_caught", err=str(_exc)[:120], location="mission_system:983")
        # ── end mission signals ───────────────────────────────────────────

        # Phase 5 : persist MemoryEntry dans VaultMemory JSONL
        try:
            from memory.vault_memory import MemoryEntry, store_memory_entry
            me = MemoryEntry(
                context=r.user_input[:500],
                decision=r.advisory_decision or r.plan_summary[:200],
                result="SUCCESS",
                score=min(1.0, max(0.0, r.advisory_score / 10.0)),
                tags=[r.intent.lower() if isinstance(r.intent, str) else str(r.intent)],
                mission_id=mission_id,
            )
            store_memory_entry(me)
        except Exception:
            pass  # fail-open

        return r

    def cancel(self, mission_id: str, reason: str = "") -> MissionResult|None:
        """Cancel a running or pending mission.

        Transitions mission to REJECTED with cancellation metadata.
        Records lifecycle error. Safe to call on any non-terminal status.
        """
        r = self._missions.get(mission_id)
        if not r:
            return None
        # Already terminal — nothing to do
        if r.status in {MissionStatus.DONE, MissionStatus.REJECTED}:
            return r
        r.status = MissionStatus.REJECTED
        r.updated_at = time.time()
        if not hasattr(r, "decision_trace") or r.decision_trace is None:
            r.decision_trace = {}
        r.decision_trace["cancelled"] = True
        r.decision_trace["cancel_reason"] = (reason or "user_cancel")[:200]
        self._save_mission(r)
        log.info("mission_cancelled", id=mission_id, reason=reason[:60])
        # Record lifecycle error
        try:
            from core.lifecycle_tracker import get_lifecycle_tracker
            get_lifecycle_tracker().record_error(mission_id, "cancelled", reason or "user_cancel")
        except Exception as _exc:
            log.debug("silent_exception_caught", err=str(_exc)[:120], location="mission_system:1028")
        return r

    def reject(self, mission_id: str, note: str = "") -> MissionResult|None:
        """Rejette une mission en attente."""
        r = self._missions.get(mission_id)
        if not r or r.status not in {MissionStatus.PENDING_VALIDATION, MissionStatus.APPROVED}:
            return r

        aq = self._get_action_queue()
        for aid in r.action_ids:
            aq.reject(aid, note=note)

        r.status     = MissionStatus.REJECTED
        r.updated_at = time.time()
        self._save_mission(r)
        log.info("mission_rejected", id=mission_id, reason=note[:60])
        # Fail associated goal
        try:
            gm = self._get_goal_manager()
            goal_id = self._mission_goals.get(mission_id)
            if gm and goal_id:
                gm.fail(goal_id, error=note or "Mission rejetée")
        except Exception as _exc:
            log.debug("silent_exception_caught", err=str(_exc)[:120], location="mission_system:1052")
        return r

    def get(self, mission_id: str) -> MissionResult|None:
        return self._missions.get(mission_id)

    def list_missions(
        self,
        status: str|None = None,
        limit: int = 20,
    ) -> list[MissionResult]:
        missions = list(self._missions.values())
        if status:
            missions = [m for m in missions if m.status == status.upper()]
        return sorted(missions, key=lambda m: m.created_at, reverse=True)[:limit]

    def stats(self) -> dict:
        all_m = list(self._missions.values())
        by_status: dict[str, int] = {}
        for m in all_m:
            by_status[m.status] = by_status.get(m.status, 0) + 1
        return {
            "total":    len(all_m),
            "by_status": by_status,
            "by_intent": {
                i: sum(1 for m in all_m if m.intent == i)
                for i in set(m.intent for m in all_m)
            },
        }

    # ── Plan Builder ─────────────────────────────────────────────────────────

    def _build_plan(self, user_input: str, intent: MissionIntent) -> MissionPlan:
        """
        Construit un plan structuré sans LLM.
        Basé sur l'intention détectée et des templates.
        """
        templates: dict[str, list[dict]] = {
            MissionIntent.ANALYZE: [
                {"agent": "scout-research", "task": f"Analyser : {user_input[:80]}", "priority": 1, "risk": "LOW"},
                {"agent": "shadow-advisor", "task": "Valider l'analyse", "priority": 2, "risk": "LOW"},
                {"agent": "lens-reviewer",  "task": "Rapport final", "priority": 3, "risk": "LOW"},
            ],
            MissionIntent.CREATE: [
                {"agent": "scout-research", "task": "Recherche contexte", "priority": 1, "risk": "LOW"},
                {"agent": "map-planner",    "task": f"Planifier : {user_input[:60]}", "priority": 2, "risk": "MEDIUM"},
                {"agent": "forge-builder",  "task": "Générer le contenu", "priority": 3, "risk": "MEDIUM"},
                {"agent": "shadow-advisor", "task": "Valider la création", "priority": 4, "risk": "LOW"},
                {"agent": "lens-reviewer",  "task": "Contrôle qualité", "priority": 5, "risk": "LOW"},
            ],
            MissionIntent.IMPROVE: [
                {"agent": "lens-reviewer",  "task": "Audit de l'existant", "priority": 1, "risk": "LOW"},
                {"agent": "shadow-advisor", "task": "Identifier les risques", "priority": 2, "risk": "LOW"},
                {"agent": "map-planner",    "task": "Plan d'amélioration", "priority": 3, "risk": "MEDIUM"},
                {"agent": "forge-builder",  "task": "Appliquer les améliorations", "priority": 4, "risk": "HIGH"},
            ],
            MissionIntent.REVIEW: [
                {"agent": "lens-reviewer",  "task": f"Réviser : {user_input[:80]}", "priority": 1, "risk": "LOW"},
                {"agent": "shadow-advisor", "task": "Analyse critique", "priority": 2, "risk": "LOW"},
            ],
            MissionIntent.PLAN: [
                {"agent": "scout-research", "task": "Analyse du contexte", "priority": 1, "risk": "LOW"},
                {"agent": "map-planner",    "task": f"Construire le plan : {user_input[:60]}", "priority": 2, "risk": "LOW"},
                {"agent": "shadow-advisor", "task": "Valider le plan", "priority": 3, "risk": "LOW"},
            ],
        }

        steps_raw = templates.get(intent, templates[MissionIntent.ANALYZE])
        steps = [
            MissionStep(
                agent=s["agent"], task=s["task"],
                priority=s["priority"], risk=s["risk"],
            )
            for s in steps_raw
        ]

        # Risque global = max risque des étapes
        risks = [s.risk for s in steps]
        overall_risk = "CRITICAL" if "CRITICAL" in risks else (
            "HIGH" if "HIGH" in risks else (
                "MEDIUM" if "MEDIUM" in risks else "LOW"
            )
        )

        # Fix: classify_action() depuis le texte du goal — impose action_type
        # et risk minimum sur les étapes d'exécution
        goal_action_type, min_risk = classify_action(user_input)
        if _RISK_ORDER.index(min_risk) > _RISK_ORDER.index(overall_risk):
            overall_risk = min_risk
        if goal_action_type == "write":
            for step in steps:
                if step.agent in {"forge-builder", "map-planner"}:
                    step.action_type = "write"
                    if _RISK_ORDER.index("MEDIUM") > _RISK_ORDER.index(step.risk):
                        step.risk = "MEDIUM"

        summary = self._summarize_input(user_input, intent)

        return MissionPlan(
            intent=intent,
            summary=summary,
            steps=steps,
            estimated_risk=overall_risk,
            rationale=f"Plan {intent} généré automatiquement pour : {user_input[:100]}",
        )

    def _summarize_input(self, user_input: str, intent: MissionIntent) -> str:
        """Résumé court de la mission."""
        # Nettoyage et troncature
        clean = re.sub(r"\s+", " ", user_input).strip()
        if len(clean) <= 60:
            return clean
        # Prend les premiers mots significatifs
        words = clean.split()[:10]
        return " ".join(words) + "..."

    # ── Évaluation advisory ───────────────────────────────────────────────────

    def _evaluate_advisory(self, plan: MissionPlan, user_input: str) -> dict:
        """
        Évalue le plan de manière dynamique :
        - base sur le niveau de risque
        - modulée par le contenu de la mission (mots positifs/négatifs)
        - modulée par le nombre d'étapes
        - modulée par la cohérence intent/contenu
        """
        # Base par niveau de risque
        risk_scores = {"LOW": 7.5, "MEDIUM": 6.0, "HIGH": 4.5, "CRITICAL": 2.5}
        score       = risk_scores.get(plan.estimated_risk, 5.0)

        # Signaux positifs dans l'input (analyse, rapport, check = basses conséquences)
        _POSITIVE = {"analys", "rapport", "check", "inspect", "list", "monitor",
                     "verifie", "vérif", "stat", "audit", "log", "résume", "search"}
        _NEGATIVE = {"supprim", "delet", "overwrite", "écraser", "remplace",
                     "drop", "reset", "wipe", "truncat", "destruct"}

        words = user_input.lower()
        score += 0.3 * sum(1 for p in _POSITIVE if p in words)
        score -= 0.4 * sum(1 for n in _NEGATIVE if n in words)

        # Plus d'étapes = plan plus solide (jusqu'à +0.5)
        score += min(len(plan.steps), 5) * 0.1

        # Intent bonus
        intent_bonus = {
            MissionIntent.ANALYZE:  0.3,
            MissionIntent.MONITOR:  0.2,
            MissionIntent.REVIEW:   0.2,
            MissionIntent.SEARCH:   0.1,
            MissionIntent.PLAN:     0.0,
            MissionIntent.CREATE:  -0.1,
            MissionIntent.IMPROVE: -0.1,
        }
        score += intent_bonus.get(plan.intent, 0.0)

        # Clamp entre 1.0 et 9.8
        score = round(max(1.0, min(9.8, score)), 1)

        decision = "GO" if score >= 7.0 else ("IMPROVE" if score >= 4.0 else "NO-GO")

        return {
            "decision":        decision,
            "final_score":     score,
            "confidence":      0.75,
            "blocking_issues": self._auto_issues(plan),
            "risks":           self._auto_risks(plan),
            "improvements":    [],
            "justification": (
                f"Score {score}/10 — plan {plan.intent.value} "
                f"(risque={plan.estimated_risk}, {len(plan.steps)} étapes, "
                f"intent={plan.intent.value})."
            ),
        }

    def _auto_issues(self, plan: MissionPlan) -> list[dict]:
        """Issues automatiques selon le risque du plan."""
        if plan.estimated_risk in {"HIGH", "CRITICAL"}:
            return [{
                "type": "technique",
                "description": f"Plan à risque {plan.estimated_risk} — validation humaine recommandée",
                "severity": "medium" if plan.estimated_risk == "HIGH" else "high",
                "evidence": f"Étapes à risque dans le plan : {plan.estimated_risk}",
            }]
        return []

    def _auto_risks(self, plan: MissionPlan) -> list[dict]:
        """Risques automatiques selon l'intention."""
        risks_map = {
            MissionIntent.CREATE:  [{"type": "execution", "description": "Le contenu créé peut nécessiter des ajustements", "severity": "low", "probability": "medium", "impact": "low"}],
            MissionIntent.IMPROVE: [{"type": "régression", "description": "Les modifications peuvent introduire des régressions", "severity": "medium", "probability": "medium", "impact": "medium"}],
        }
        return risks_map.get(plan.intent, [])

    # ── Actions ───────────────────────────────────────────────────────────────

    def _create_actions(self, plan: MissionPlan, mission_id: str) -> list[str]:
        """Crée les actions dans ActionQueue pour chaque étape du plan."""
        aq  = self._get_action_queue()
        ids = []
        for step in plan.steps:
            action = aq.enqueue(
                description=step.task,
                risk=step.risk,
                target=f"agent:{step.agent}",
                impact=f"Exécution agent {step.agent} — priorité {step.priority}",
                rollback="Annuler la tâche (non critique pour la plupart des analyses)",
                mission_id=mission_id,
            )
            ids.append(action.id)
        return ids

    def _has_approval_required_actions(self, action_ids: list[str]) -> bool:
        """Check if any actions in the mission require manual approval.

        Returns True if at least one action uses a tool with requires_approval=True.
        Returns False if all actions are safe (analysis, search, read-only).

        Used to prevent deadlock: if no actions need approval,
        the mission should not be stuck in PENDING_VALIDATION.
        """
        try:
            from core.capabilities.registry import get_capability_registry
            registry = get_capability_registry()
            aq = self._get_action_queue()

            for aid in action_ids:
                action = aq.get(aid) if hasattr(aq, 'get') else None
                if action is None:
                    continue

                # Check tool name against capability registry
                tool_name = getattr(action, 'tool_name', '') or getattr(action, 'tool', '') or ''
                if not tool_name:
                    continue

                cap = registry.get(tool_name)
                if cap and cap.requires_approval:
                    return True

            return False
        except Exception as e:
            log.debug("approval_check_failed", err=str(e)[:80])
            # Fail-safe: if we can't determine, assume blocking (conservative)
            return True

    def _auto_approve_actions(self, action_ids: list[str], shadow_score: float) -> None:
        """Auto-approuve les actions dans ActionQueue."""
        aq = self._get_action_queue()
        for aid in action_ids:
            aq.approve(aid, note=f"Auto-approuvé (score shadow={shadow_score:.1f})")

    # ── Lazy getters ──────────────────────────────────────────────────────────

    def _get_action_queue(self):
        if self._aq is None:
            from core.action_queue import get_action_queue
            self._aq = get_action_queue()
        return self._aq

    def _get_mode_system(self):
        if self._ms is None:
            from core.mode_system import get_mode_system
            self._ms = get_mode_system()
        return self._ms

    def _get_goal_manager(self):
        if self._gm is None:
            try:
                from core.goal_manager import GoalManager

                class _FakeSettings:
                    workspace_dir = "workspace"
                self._gm = GoalManager(_FakeSettings())
            except Exception as _exc:
                log.debug("silent_exception_caught", err=str(_exc)[:120], location="mission_system:1326")
                return None
        return self._gm

    # ── Persistance ───────────────────────────────────────────────────────────

    def _save_mission(self, result: MissionResult) -> None:
        self._missions[result.mission_id] = result
        if self._use_sqlite:
            self._sqlite_upsert(result)
        else:
            self._save()

    def _load(self) -> None:
        # Try SQLite first
        try:
            from core import db as _db_mod
            db = _db_mod.get_db()
            if db is not None:
                rows = _db_mod.fetchall(
                    "SELECT * FROM missions ORDER BY created_at DESC LIMIT 200"
                )
                for row in rows:
                    try:
                        m = MissionResult(
                            mission_id=row["id"],
                            user_input=row["user_input"] or "",
                            intent=row["intent"] or "OTHER",
                            status=row["status"] or MissionStatus.ANALYZING,
                            plan_summary=row["plan_summary"] or "",
                            plan_steps=_db_mod.loads(row.get("plan_steps"), []),
                            advisory_score=row["advisory_score"] or 0.0,
                            advisory_decision=row["advisory_decision"] or "UNKNOWN",
                            advisory_issues=_db_mod.loads(row.get("advisory_issues"), []),
                            advisory_risks=_db_mod.loads(row.get("advisory_risks"), []),
                            action_ids=_db_mod.loads(row.get("action_ids"), []),
                            requires_validation=bool(row["requires_validation"]),
                            created_at=row["created_at"] or time.time(),
                            updated_at=row["updated_at"] or time.time(),
                            final_output=row.get("final_output") or "",
                            summary=row.get("summary") or "",
                            agents_selected=_db_mod.loads(row.get("agents_selected"), []),
                            domain=row.get("domain") or "general",
                            execution_trace=_db_mod.loads(row.get("execution_trace"), []),
                            decision_trace=_db_mod.loads(row.get("decision_trace"), {}),
                            risk_score=row.get("risk_score") or 0,
                            complexity=row.get("complexity") or "medium",
                            error=row.get("error") or "",
                        )
                        self._missions[m.mission_id] = m
                    except Exception as _exc:
                        log.debug("silent_exception_caught", err=str(_exc)[:120], location="mission_system:sqlite_row")
                self._use_sqlite = True
                log.debug("mission_system_loaded_sqlite", count=len(self._missions))
                return
        except Exception as exc:
            log.warning("mission_sqlite_load_failed", err=str(exc))
        # Fallback JSON
        self._use_sqlite = False
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            if not self._path.exists():
                return
            data = json.loads(self._path.read_text("utf-8"))
            for item in data.get("missions", []):
                try:
                    m = MissionResult.from_dict(item)
                    self._missions[m.mission_id] = m
                except Exception as _exc:
                    log.debug("silent_exception_caught", err=str(_exc)[:120], location="mission_system:json_row")
        except Exception as exc:
            log.warning("mission_system_load_failed", err=str(exc))

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # Rotation
            if len(self._missions) > _MAX_STORED:
                done = [m for m in self._missions.values() if m.is_done()]
                for old in sorted(done, key=lambda m: m.created_at)[:20]:
                    del self._missions[old.mission_id]
            data = {
                "version":  1,
                "saved_at": time.time(),
                "missions": [m.to_dict() for m in self._missions.values()],
            }
            self._path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), "utf-8"
            )
        except Exception as exc:
            log.warning("mission_system_save_failed", err=str(exc))

    def _sqlite_upsert(self, result: MissionResult) -> None:
        try:
            from core import db as _db_mod
            _db_mod.execute(
                """INSERT OR REPLACE INTO missions
                   (id, user_input, intent, status, plan_summary, plan_steps,
                    advisory_score, advisory_decision, advisory_issues, advisory_risks,
                    action_ids, requires_validation, auto_approved, created_at,
                    updated_at, completed_at, note, final_output, summary, agents_selected,
                    domain, execution_trace, decision_trace, risk_score, complexity, error)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    result.mission_id, result.user_input, result.intent, result.status,
                    result.plan_summary,
                    _db_mod.dumps(result.plan_steps),
                    result.advisory_score, result.advisory_decision,
                    _db_mod.dumps(result.advisory_issues),
                    _db_mod.dumps(result.advisory_risks),
                    _db_mod.dumps(result.action_ids),
                    1 if result.requires_validation else 0,
                    0,  # auto_approved
                    result.created_at, result.updated_at,
                    None,  # completed_at
                    "",  # note
                    result.final_output,
                    result.summary,
                    _db_mod.dumps(result.agents_selected),
                    result.domain,
                    _db_mod.dumps(result.execution_trace),
                    _db_mod.dumps(result.decision_trace),
                    result.risk_score,
                    result.complexity,
                    result.error,
                )
            )
        except Exception as exc:
            log.warning("mission_sqlite_upsert_failed", err=str(exc))
            self._save()


# ── Singleton ─────────────────────────────────────────────────────────────────

_mission_instance: MissionSystem|None = None


def get_mission_system() -> MissionSystem:
    global _mission_instance
    if _mission_instance is None:
        _mission_instance = MissionSystem()
    return _mission_instance
