"""
core.executor.pipeline_auto
============================
PipelineAutoMixin: the main AUTO pipeline for BeaOrchestrator.
Covers: _run_auto, _run_parallel, _run_observer, _process_actions,
        _evaluate_session_async, classify_intent, _compute_mission_complexity.
"""
from __future__ import annotations
import asyncio
import uuid
import structlog

from core.state import BeaSession, ActionSpec, TaskMode
from .constants import CB

log = structlog.get_logger()


class PipelineAutoMixin:
    """Mixin providing the AUTO pipeline and shared utilities."""

    # ── Classify intent (local, zero LLM) ────────────────────

    def classify_intent(self, user_input: str) -> str:
        """
        Classifie l'intention via regex locale (TaskRouter).
        Retourne une clé de INTENT_MAP.
        Aucun LLM requis — instanciable sans provider cloud.
        """
        decision = self.router.route(user_input)
        _mode_to_intent: dict[str, str] = {
            "improve":  "improve",
            "code":     "code",
            "research": "research",
            "plan":     "plan",
            "night":    "night",
            "chat":     "chat",
            "auto":     "default",
        }
        intent = _mode_to_intent.get(decision.mode.value, "default")
        log.debug("intent_classified",
                  input=user_input[:60], mode=decision.mode.value, intent=intent)
        return intent

    def _compute_mission_complexity(self, text: str) -> float:
        """
        Score de complexité 0.0–1.0 pour décider si AtlasDirector est nécessaire.
        Utilise ModelSelector si disponible, sinon heuristique locale (zéro LLM).

        > 0.60 → mission complexe → AtlasDirector
        ≤ 0.60 → plan statique TaskRouter (plus rapide)
        """
        try:
            if self.model_selector:
                return self.model_selector._compute_complexity(text)
        except Exception as _exc:
            log.debug("orchestrator_exception", err=str(_exc)[:120], location="orchestrator:309")
        # Heuristique fallback — déterministe
        if not text:
            return 0.0
        length_score   = min(len(text) / 500.0, 0.35)
        keyword_score  = 0.0
        complex_kws    = (
            "architecture", "migration", "sécurité", "refactor",
            "système", "integr", "pipeline", "deploie", "configure",
            "optimise", "benchmark", "multi", "automatise",
        )
        matched = sum(1 for kw in complex_kws if kw in text.lower())
        keyword_score = min(matched * 0.10, 0.40)
        multi_sentence = 0.15 if text.count(".") >= 3 or text.count("\n") >= 2 else 0.0
        return round(min(length_score + keyword_score + multi_sentence, 1.0), 3)

    # ── AUTO pipeline ─────────────────────────────────────────

    async def _run_auto(self, session: BeaSession, emit: CB):
        # 0. GoalManager — enregistrer la mission
        try:
            if self.goal_manager:
                self.goal_manager.start(
                    text=session.user_input[:200],
                    mode=session.mode,
                    session_id=session.session_id,
                )
        except Exception as e:
            log.debug("goal_manager_start_failed", err=str(e)[:60])

        # 0b. DecisionReplay — démarrer l'enregistrement
        try:
            if self.replay:
                self.replay.record(session.session_id, "ROUTE", {
                    "mode": session.mode,
                    "input": session.user_input[:100],
                })
        except Exception as _exc:
            log.debug("orchestrator_exception", err=str(_exc)[:120], location="orchestrator:414")

        # 1. Routing
        decision = self.router.route(session.user_input, explicit_mode=session.mode)
        session.task_mode    = decision.mode
        session.needs_actions = decision.needs_actions

        # 1b. Short-circuit: if TaskRouter decided CHAT, skip the full pipeline
        # and call _run_chat() directly (direct LLM call, ~1s instead of 5+ min).
        if decision.mode == TaskMode.CHAT:
            log.info("orchestrator_chat_shortcircuit",
                     sid=session.session_id,
                     reason=getattr(decision, "reason", ""),
                     input_len=len(session.user_input.strip()))
            return await self._run_chat(session, emit)

        # 2. Memoire en premier
        await emit("Rappel memoire...")
        await self.agents.run("vault-memory", session)

        # 3. Plan — adaptatif selon complexité de la mission
        # Missions complexes (score > 0.60) → AtlasDirector (plan LLM sur mesure)
        # Missions simples/standard → plan statique TaskRouter (rapide, déterministe)
        complexity   = self._compute_mission_complexity(session.user_input)
        use_director = (
            complexity > 0.80  # 0.60->0.80: evite atlas sur research/analyse simples
            and decision.mode not in (TaskMode.CHAT, TaskMode.RESEARCH, TaskMode.PLAN,
                                      TaskMode.BUSINESS)
            # BUSINESS: plan statique requis (agents spécialisés + timeouts 90s/180s
            # que AtlasDirector ne connaît pas et ne reproduit pas)
        )

        # 3a. Hierarchical decomposition (strategic layer) — fires before AtlasDirector
        # Only for CODE/WORKFLOW — skip on RESEARCH/PLAN to avoid extra LLM call.
        _hplan_modes = (TaskMode.CODE, TaskMode.WORKFLOW) if hasattr(TaskMode, 'WORKFLOW') else (TaskMode.CODE,)
        if use_director and decision.mode in _hplan_modes:
            try:
                from core.hierarchical_planner import get_mission_decomposer
                _h_plan = get_mission_decomposer().decompose(
                    goal=session.user_input,
                    mission_type=str(getattr(decision, "mission_type", "general")),
                    complexity="high",
                    mission_id=session.session_id,
                )
                if _h_plan:
                    session._hierarchical_plan = _h_plan  # type: ignore[attr-defined]
                    await emit(
                        f"[HierarchicalPlanner] {len(_h_plan.macro_goals)} objectifs stratégiques, "
                        f"{_h_plan.total_tactical_steps} étapes tactiques."
                    )
                    log.info(
                        "hierarchical_plan_attached",
                        sid=session.session_id,
                        plan_id=_h_plan.plan_id,
                        macro_goals=len(_h_plan.macro_goals),
                        tactical_steps=_h_plan.total_tactical_steps,
                    )
            except Exception as _hp_exc:
                log.debug("hierarchical_plan_skip", err=str(_hp_exc)[:80])

        if use_director:
            await emit(f"Mission complexe (score={complexity:.2f}) — AtlasDirector planifie...")
            try:
                import asyncio as _aio
                await _aio.wait_for(self.agents.run("atlas-director", session), timeout=30.0)
                if not session.agents_plan:
                    raise ValueError("atlas-director a retourné un plan vide")
                log.info("auto_atlas_director_used",
                         sid=session.session_id, complexity=complexity,
                         agents=[a["agent"] for a in session.agents_plan])
            except Exception as e:
                log.warning("atlas_director_fallback_static",
                            err=str(e)[:80], complexity=complexity)
                # Fallback transparent vers plan statique
                session.mission_summary = session.user_input
                session.agents_plan     = [
                    a for a in decision.agents if a["agent"] != "vault-memory"
                ]
        else:
            # Plan statique TaskRouter — rapide et sans dépendance LLM
            session.mission_summary = session.user_input
            session.agents_plan     = [
                a for a in decision.agents if a["agent"] != "vault-memory"
            ]

        if session.agents_plan:
            planner    = "AtlasDirector" if use_director else "TaskRouter"
            agents_str = ", ".join(t["agent"] for t in session.agents_plan)
            await emit(
                f"Plan ({planner}) : {session.mission_summary[:100]}\n"
                f"Agents : {agents_str}"
            )

        # 3b. Smart agent selection — parse routing header from enriched goal
        try:
            import re as _re
            _shape = ""
            _complexity = ""
            # Parse structured header from enriched goal (session-safe, no shared state)
            _routing_match = _re.search(
                r'\[ROUTING:shape=(\w+),complexity=(\w*)\]',
                session.user_input or ""
            )
            if _routing_match:
                _shape = _routing_match.group(1)
                _complexity = _routing_match.group(2)

            # BUSINESS mode : le plan est figé (analystes spécialisés + forge-builder).
            # Le smart_agent_selection ne connaît pas les agents business et les
            # élimine systématiquement. On le bypass pour BUSINESS.
            _is_business = (getattr(getattr(session, "task_mode", None), "value", "") == "business")
            if _shape and session.agents_plan and not _is_business:
                # Agent relevance map based on output shape
                _SHAPE_AGENTS = {
                    "direct_answer": {"scout-research"},
                    "diagnosis":     {"scout-research", "shadow-advisor"},
                    "patch":         {"scout-research", "forge-builder", "lens-reviewer"},
                    "plan":          {"scout-research", "map-planner", "forge-builder"},
                    "report":        {"scout-research", "map-planner", "lens-reviewer"},
                    "warning":       {"scout-research", "shadow-advisor"},
                }

                _relevant = _SHAPE_AGENTS.get(_shape)
                if _relevant and len(session.agents_plan) > 1:
                    _before = len(session.agents_plan)
                    _filtered = [
                        a for a in session.agents_plan
                        if a.get("agent") in _relevant
                    ]
                    # Ne pas appliquer le filtre si tous les agents sont éliminés :
                    # cela indique un plan spécialisé (ex: business) sans agents génériques.
                    if _filtered:
                        session.agents_plan = _filtered
                        _after = len(session.agents_plan)
                        if _after < _before:
                            log.info("smart_agent_selection",
                                     shape=_shape, before=_before, after=_after,
                                     agents=[a.get("agent") for a in session.agents_plan])
                            await emit(
                                f"[Routing] {_shape} → {_after} agent(s) sélectionné(s) "
                                f"(sur {_before})"
                            )
                    else:
                        log.info("smart_agent_selection_skipped_specialized",
                                 shape=_shape, agents=[a.get("agent") for a in session.agents_plan])
        except Exception as _ras_err:
            log.debug("smart_agent_selection_skipped", err=str(_ras_err)[:60])

        # 4. Agents paralleles par priorite
        await self._run_parallel(session, emit)

        # 4b. Mémoriser les sorties réussies dans AgentMemory (per-agent)
        try:
            if self.agent_memory and session.outputs:
                for name, out in session.outputs.items():
                    if out.success and out.content:
                        task_for_agent = next(
                            (t.get("task", "") for t in session.agents_plan
                             if t.get("agent") == name),
                            session.mission_summary or "",
                        )
                        self.agent_memory.record(
                            agent_name=name,
                            task=task_for_agent,
                            output=out.content,
                            success=True,
                            score=1.0,
                        )
        except Exception as e:
            log.debug("agent_memory_record_failed", err=str(e)[:80])

        # 5. Observer workspace
        await self._run_observer(session)

        # 6. Actions — toujours tenter si needs_actions (forge-builder fallback intégré)
        if session.needs_actions:
            pulse_in_plan = any(
                t.get("agent") == "pulse-ops"
                for t in session.agents_plan
            )
            if not pulse_in_plan:
                log.info("pulse_ops_absent", note="using forge-builder fallback in _process_actions")
            await self._process_actions(session, emit)

        # 7. Rapport final — statut calculé une seule fois ici (évite double log)
        session_status = self._compute_session_status(session)
        await self._generate_report(session, emit, session_status=session_status)
        mode_str = (session.task_mode.value if hasattr(session.task_mode, "value")
                    else str(session.task_mode))
        session_ok = (session_status["label"] != "FAILURE")

        try:
            if self.metrics:
                self.metrics.record_run(
                    mode=mode_str,
                    success=session_ok,
                    duration_s=0.0,
                )
        except Exception as e:
            log.debug("metrics_record_failed", err=str(e)[:60])

        # 8bis. LearningEngine — enregistrement réel (n'était jamais appelé)
        try:
            if self.learning:
                agents_ok:    dict[str, int] = {}
                agents_total: dict[str, int] = {}
                for name, out in session.outputs.items():
                    agents_total[name] = 1
                    agents_ok[name]    = 1 if out.success else 0

                self.learning.record_run({
                    "session_id":       session.session_id,
                    "mode":             mode_str,
                    "status":           session_status["label"],
                    "agents_ok":        session_status["ok"],
                    "agents_total":     session_status["total"],
                    "success_rate":     round(session_status["rate"], 3),
                    "patches_generated": len(getattr(session, "improve_pending", [])),
                    "patches_approved":  session.auto_count,
                    "patches_applied":   len(session.actions_executed),
                    "mission":          (session.mission_summary or "")[:100],
                    "agents_results":   {n: agents_ok.get(n, 0)
                                        for n in agents_total},
                })
        except Exception as e:
            log.debug("learning_record_failed", err=str(e)[:80])

        # 8b. LLM Performance Monitor — enregistrer latences agents + détecter drift
        try:
            if self.llm_perf:
                for name, out in session.outputs.items():
                    self.llm_perf.record(
                        role=name,
                        latency_ms=out.duration_ms if hasattr(out, "duration_ms") else 0,
                        error=not out.success,
                    )
                drift = self.llm_perf.get_drift_report()
                if drift.get("drifting"):
                    log.warning("llm_drift_detected", agents=list(drift.get("drifting", {}).keys()))
        except Exception as e:
            log.debug("llm_perf_record_failed", err=str(e)[:60])

        # 8c. Évaluation qualité session (tracked background task — ne bloque pas)
        try:
            if self.evaluator and session.outputs:
                _task = asyncio.create_task(
                    self._evaluate_session_async(session)
                )
                self._bg_tasks.add(_task)
                _task.add_done_callback(self._bg_tasks.discard)
        except Exception as e:
            log.debug("evaluator_schedule_failed", err=str(e)[:60])

        # 9. Mémoriser dans VectorMemory (contexte session)
        try:
            if self.vector_memory and session.final_report:
                self.vector_memory.add(
                    session.final_report[:1000],
                    metadata={"type": "session", "mode": str(session.task_mode),
                               "session_id": session.session_id},
                )
        except Exception as e:
            log.debug("vector_memory_store_failed", err=str(e)[:60])

        # 10. Memoriser (MemoryStore existant)
        try:
            await self.memory.store_session(session)
        except Exception as e:
            log.warning("memory_store_failed", err=str(e))

        # 10b. MemoryBus — mémoriser également via bus unifié
        try:
            if self.memory_bus and session.mission_summary:
                await self.memory_bus.remember_async(
                    text=session.mission_summary[:500],
                    metadata={
                        "session_id": session.session_id,
                        "mode": str(getattr(session.task_mode, "value", session.task_mode)),
                        "agents": [t.get("agent") for t in session.agents_plan],
                    },
                )
        except Exception as e:
            log.debug("memory_bus_store_failed", err=str(e)[:60])

        # 11. GoalManager — marquer la mission comme terminée
        try:
            if self.goal_manager:
                active = self.goal_manager.get_active()
                if active and active.session_id == session.session_id:
                    result_summary = (session.final_report or "")[:200]
                    has_error = bool(getattr(session, "error", None))
                    if has_error:
                        self.goal_manager.fail(active.id,
                                               error=str(session.error)[:100])
                    else:
                        self.goal_manager.complete(active.id,
                                                   result=result_summary)
        except Exception as e:
            log.debug("goal_manager_complete_failed", err=str(e)[:60])

        # 12. SystemState — enregistrer les métriques de la session
        try:
            if self.system_state and session.outputs:
                for name, out in session.outputs.items():
                    self.system_state.update_module(
                        name,
                        healthy=out.success,
                        latency_ms=getattr(out, "duration_ms", 0),
                        error=getattr(out, "error", "") or "",
                    )
        except Exception as e:
            log.debug("system_state_update_failed", err=str(e)[:60])

        # 13. DecisionReplay — enregistrer le résultat
        try:
            if self.replay:
                ok_agents = sum(1 for o in session.outputs.values() if o.success)
                self.replay.record(session.session_id, "RESULT", {
                    "status": getattr(session.status, "value", str(session.status)),
                    "agents_ok": ok_agents,
                    "has_report": bool(session.final_report),
                })
                self.replay.flush()
        except Exception as _exc:
            log.debug("orchestrator_exception", err=str(_exc)[:120], location="orchestrator:642")

    # ── Parallel agent execution ──────────────────────────────

    async def _run_parallel(self, session: BeaSession, emit: CB):
        """
        Exécution parallèle des agents via ParallelExecutor.
        Les agents sont regroupés par priorité et exécutés par vague :
          P1 (vault-memory) → P2 (scout, map-planner, forge, …) → P3 (lens-reviewer)
        Cela garantit que lens-reviewer (P3) dispose du contexte P2 complet
        avant de démarrer son évaluation.
        """
        from agents.parallel_executor import ParallelExecutor
        # BUSINESS mode : forge-builder (P5) peut prendre jusqu'à 420s pour Codex.
        # Per-agent timeouts (90s analysts, 420s forge) bornent chaque agent ;
        # le global doit être > per-agent-max pour ne pas tuer forge-builder.
        _mode_val = getattr(getattr(session, "task_mode", None), "value", "") or ""
        _gtimeout = 450 if _mode_val == "business" else 120
        pex = ParallelExecutor(self.s, global_timeout=_gtimeout)

        # Filtrer les agents non-supportés
        skip = {"atlas-director", "vault-memory"}
        tasks = [
            t for t in session.agents_plan
            if t.get("agent", "") not in skip
            and t.get("agent", "") in self.agents.registry
        ]

        if not tasks:
            log.debug("parallel_no_tasks")
            return

        mode_val = getattr(session.task_mode, "value", str(session.task_mode))

        # ── Exécution par vague de priorité ──────────────────────
        # group_by_priority() retourne une liste de listes ordonnées par priorité.
        # On exécute chaque vague séquentiellement, mais en parallèle à l'intérieur.
        priority_waves = ParallelExecutor.group_by_priority(tasks)
        all_results: dict = {}
        total_ok = 0
        total_failed: list[str] = []

        for wave_idx, wave_tasks in enumerate(priority_waves):
            if session._raw_actions:
                wave_tasks = [
                    task for task in wave_tasks
                    if task.get("agent") != "pulse-ops"
                ]
                if not wave_tasks:
                    log.info(
                        "pulse_ops_skipped",
                        reason="forge-builder actions already extracted",
                        count=len(session._raw_actions),
                    )
                    continue
            wave_priorities = sorted({t.get("priority", 2) for t in wave_tasks})
            log.debug("parallel_wave_start",
                      wave=wave_idx, priorities=wave_priorities,
                      agents=[t.get("agent") for t in wave_tasks])

            # Replan dynamique uniquement sur les vagues non-P3 en mode non-chat
            has_critical = any(t.get("priority", 2) <= 2 for t in wave_tasks)
            # Replan only for complex modes (CODE, WORKFLOW) — skip for RESEARCH/PLAN
            # to avoid double parallel wave that doubles execution time
            _replan_modes = {"code", "workflow"}
            use_replan   = (mode_val in _replan_modes) and has_critical

            if use_replan:
                wave_results = await pex.run_with_replan(
                    wave_tasks, session, emit=emit, max_replan_rounds=1
                )
            else:
                wave_results = await pex.run(wave_tasks, session, emit=emit)

            all_results.update(wave_results)
            wave_ok     = sum(1 for r in wave_results.values() if r.success)
            wave_failed = [r.agent for r in wave_results.values() if not r.success]
            total_ok     += wave_ok
            total_failed += wave_failed

            log.info("parallel_wave_done",
                     wave=wave_idx, priorities=wave_priorities,
                     ok=wave_ok, failed=len(wave_failed))

        # Comptabiliser succès/échecs globaux
        msg = f"Parallel : {total_ok}/{len(all_results)} agents OK"
        if total_failed:
            msg += f" | Echecs : {', '.join(total_failed)}"
        await emit(msg)
        log.info("parallel_done", ok=total_ok, failed=len(total_failed),
                 waves=len(priority_waves))

    # ── Observer ──────────────────────────────────────────────

    async def _run_observer(self, session: BeaSession):
        try:
            from core.observability.watcher import SystemObserver
            snap = await SystemObserver(self.s).snapshot_workspace()
            session.set_output("observer", snap, success=True)
        except Exception as e:
            log.warning("observer_failed", err=str(e))

    # ── Action processing ─────────────────────────────────────

    async def _process_actions(self, session: BeaSession, emit: CB):
        """
        Traite les actions collectées par PulseOps via SupervisedExecutor.
        SupervisedExecutor centralise : analyse risque → décision → exécution.
        """
        raw = session._raw_actions
        if not raw:
            from agents.crew import extract_file_actions

            forge_out = getattr(session.outputs.get("forge-builder"), "content", "")
            raw = extract_file_actions(forge_out)
            session._raw_actions = raw
            if raw:
                log.info(
                    "forge_builder_actions_recovered",
                    files=[a["target"] for a in raw],
                    count=len(raw),
                )
        if not raw:
            return

        # Construire les ActionSpec depuis les dicts bruts
        actions: list[ActionSpec] = []
        for item in raw:
            if session.auto_count >= self.s.max_auto_actions:
                await emit(f"Limite d actions auto atteinte ({self.s.max_auto_actions}).")
                break
            actions.append(ActionSpec(
                id=str(uuid.uuid4())[:8],
                action_type=item.get("action_type", ""),
                target=item.get("target", ""),
                content=item.get("content", ""),
                command=item.get("command", ""),
                old_str=item.get("old_str", ""),
                new_str=item.get("new_str", ""),
                description=item.get("description", ""),
            ))

        if not actions:
            return

        # Injecter l'emit dans SupervisedExecutor pour les notifications
        from executor.supervised_executor import SupervisedExecutor
        sup = SupervisedExecutor(self.s, emit=emit)

        executed, pending = await sup.execute_batch(
            actions,
            session_id=session.session_id,
            agent="pulse-ops",
            max_auto=self.s.max_auto_actions,
        )

        # Mettre à jour la session
        for result in executed:
            if result.success:
                session.actions_executed.append(result.to_dict())
                session.auto_count += 1

        session.actions_pending.extend(pending)

        auto_done = sum(1 for r in executed if r.success)
        if auto_done:
            await emit(f"{auto_done} action(s) executee(s) automatiquement")
        if pending:
            await emit(f"{len(pending)} action(s) en attente de validation")

    # ── Async evaluation (fire-and-forget) ───────────────────

    async def _evaluate_session_async(self, session: BeaSession) -> None:
        """Évalue les sorties de la session via AgentEvaluator (fire-and-forget)."""
        try:
            report = await self.evaluator.evaluate_session(session)
            log.info(
                "session_evaluated",
                sid=session.session_id,
                avg_score=round(report.average_score, 2),
                agents=len(report.results),
            )
        except Exception as e:
            log.debug("session_eval_failed", err=str(e)[:60])
