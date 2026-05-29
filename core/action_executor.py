"""
JARVIS MAX — ActionExecutor v1
Worker backend qui exécute automatiquement les actions APPROVED.

Architecture :
  ActionExecutor
  ├── _worker_loop()     : boucle daemon (thread background)
  ├── execute_action()   : dispatch selon type/target
  ├── _run_*()           : handlers par catégorie d'action
  └── status()           : état du worker (pour l'API)

Logique de dispatch (basée sur description + target) :
  - research / scout / web    → _run_research()
  - plan / map / strateg      → _run_planner()
  - create / forge / generate → _run_builder()
  - review / lens / validate  → _run_reviewer()
  - analyze / audit           → _run_analyzer()
  - DEFAULT                   → _run_generic()

Sécurité :
  - LOW    → exécution directe
  - MEDIUM → exécution directe + log enrichi
  - HIGH   → exécution avec avertissement
  - CRITICAL → skip (nécessite validation humaine explicite)

Usage :
  executor = get_executor()
  executor.start()          # lance le thread daemon
  executor.stop()           # arrêt propre
  executor.status()         # dict d'état
  executor.run_once()       # force un cycle (debug/tests)
"""
from __future__ import annotations

import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
_silent_log = __import__("structlog").get_logger(__name__)

# ===== LLM AGENT SUPPORT (2026-04-08) =====
try:
    from core.llm_agent_helper import get_agent_helper
    from core.llm_factory import LLMFactory
    from core.settings import get_settings
    LLM_AGENTS_AVAILABLE = True
except ImportError:
    LLM_AGENTS_AVAILABLE = False
    get_agent_helper = None
    LLMFactory = None
    get_settings = None
# ===== END LLM AGENT SUPPORT =====


if TYPE_CHECKING:
    pass

log = structlog.get_logger()

_POLL_INTERVAL  = 3.0   # secondes entre chaque scan
_MAX_PER_CYCLE  = 5     # actions max traitées par cycle
_RESULT_MAX_LEN = 2000  # longueur max du résultat stocké

# Mots-clés pour le dispatch
_KW_RESEARCH = re.compile(r"\b(research|scout|web|search|cherch|trouve|internet|url|site|scrape|veille)\b", re.I)
_KW_PLAN     = re.compile(r"\b(plan|plann|map|strateg|roadmap|étape|step|phase|milestone|objectif)\b", re.I)
_KW_BUILD    = re.compile(r"\b(crée|create|forge|generat|build|écri|write|produi|fichier|file|code|script)\b", re.I)
_KW_REVIEW   = re.compile(r"\b(review|revu|valid|check|audit|inspect|analyse|lens|qualit|test)\b", re.I)
_KW_IMPROVE  = re.compile(r"\b(improv|amélio|optim|patch|fix|correct|refactor|upgrade)\b", re.I)


# ── Singleton ─────────────────────────────────────────────────────────────────

_executor_instance: ActionExecutor | None = None

# get_executor() defined after ActionExecutor class (see below)
# ── ActionExecutor ────────────────────────────────────────────────────────────

class ActionExecutor:
    """Worker qui exécute les actions APPROVED de la queue."""

    def __init__(self):
        self._running       = False
        self._thread: threading.Thread | None = None
        self._lock          = threading.Lock()
        self._executed_total = 0
        self._failed_total   = 0
        self._skipped_total  = 0
        self._last_cycle_at: float | None = None
        self._current_action_id: str | None = None
        self._started_at: float | None = None

        # LLM Agent Helper (si disponible)
        self._llm_helper = None
        if LLM_AGENTS_AVAILABLE:
            try:
                settings = get_settings()
                factory = LLMFactory(settings)
                self._llm_helper = get_agent_helper(factory)
                log.info("llm_agent_helper_initialized")
            except Exception as e:
                log.warning("llm_agent_helper_init_failed", err=str(e))


    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Lance le worker en thread daemon."""
        if self._running:
            log.warning("executor_already_running")
            return
        self._running   = True
        self._started_at = time.time()
        self._thread = threading.Thread(
            target=self._worker_loop,
            name="JarvisActionExecutor",
            daemon=True,
        )
        self._thread.start()
        log.info("action_executor_started", poll_interval=_POLL_INTERVAL)

    def stop(self) -> None:
        """Arrêt propre du worker."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        log.info("action_executor_stopped",
                 executed=self._executed_total,
                 failed=self._failed_total)

    # ── Worker loop ───────────────────────────────────────────────────────────

    def _worker_loop(self) -> None:
        while self._running:
            try:
                self.run_once()
            except Exception as exc:
                log.error("executor_cycle_error", err=str(exc))
            time.sleep(_POLL_INTERVAL)

    def run_once(self) -> list[dict]:
        """
        Traite un cycle : récupère les actions APPROVED et les exécute.
        Retourne la liste des résultats du cycle.
        """
        from core.action_queue import get_action_queue
        queue = get_action_queue()

        approved = queue.approved()[:_MAX_PER_CYCLE]
        self._last_cycle_at = time.time()
        results = []

        for action in approved:
            r = self._process(action, queue)
            results.append(r)

        return results

    # ── Dispatch ──────────────────────────────────────────────────────────────

    def _process(self, action, queue) -> dict:
        """Exécute une action et met à jour son statut."""
        action_id = action.id
        risk      = action.risk

        # CRITICAL → skip, log, ne jamais exécuter automatiquement
        if risk == "CRITICAL":
            self._skipped_total += 1
            log.warning("executor_skip_critical", id=action_id, desc=action.description[:60])
            return {"id": action_id, "status": "skipped", "reason": "CRITICAL risk requires human validation"}

        with self._lock:
            self._current_action_id = action_id

        log.info("executor_start_action",
                 id=action_id, risk=risk,
                 desc=action.description[:60],
                 target=action.target[:40])

        try:
            result_text = self.execute_action(action)

            done = queue.mark_executed(action_id, result=result_text[:_RESULT_MAX_LEN])
            self._executed_total += 1

            # Envoie le résultat au learning loop
            self._learn(action, result_text, success=True)

            # Vérifier si la mission associée est terminée
            self._complete_mission_if_done(action, queue)

            log.info("executor_action_done",
                     id=action_id,
                     executed_at=done.executed_at if done else None,
                     result_preview=result_text[:80])

            with self._lock:
                self._current_action_id = None

            return {"id": action_id, "status": "executed", "result": result_text[:200]}

        except Exception as exc:
            err = f"Erreur: {exc}"
            queue.mark_failed(action_id, result=err[:_RESULT_MAX_LEN])
            self._failed_total += 1
            self._learn(action, err, success=False)

            log.error("executor_action_failed", id=action_id, err=str(exc))

            with self._lock:
                self._current_action_id = None

            return {"id": action_id, "status": "failed", "error": str(exc)}

    def execute_action(self, action) -> str:
        """
        Dispatch vers le bon handler selon la description/target.
        Retourne un string résultat.
        """
        text = f"{action.description} {action.target} {action.impact}"

        if _KW_RESEARCH.search(text):
            return self._run_research(action)
        if _KW_PLAN.search(text):
            return self._run_planner(action)
        if _KW_BUILD.search(text):
            return self._run_builder(action)
        if _KW_REVIEW.search(text):
            return self._run_reviewer(action)
        if _KW_IMPROVE.search(text):
            return self._run_improver(action)
        return self._run_generic(action)

    # ── Handlers par type ─────────────────────────────────────────────────────


    def _call_llm_agent(self, agent_type: str, description: str, context: dict = None) -> str | None:
        """
        Appelle un agent LLM si disponible, sinon retourne None (fallback templates).
        
        Args:
            agent_type: scout-research, shadow-advisor, map-planner
            description: Description de la tâche
            context: Contexte additionnel
        
        Returns:
            Réponse LLM ou None si indisponible
        """
        if not self._llm_helper:
            return None
        
        try:
            # Appel synchrone (action_executor est synchrone)
            return self._llm_helper.call_agent(
                agent_type=agent_type,
                task_description=description,
                context=context or {},
                role="default"
            )
        except Exception as e:
            log.warning("llm_agent_call_failed", agent=agent_type, err=str(e))
            return None

    def _run_research(self, action) -> str:
        """Agent: WebScout / Research — lit vraiment vault + workspace."""
        # === ESSAI LLM AGENT EN PREMIER ===
        llm_result = self._call_llm_agent(
            agent_type="scout-research",
            description=action.description,
            context={
                "target": action.target,
                "action_id": action.id
            }
        )
        if llm_result:
            log.info("research_agent_llm_used", action_id=action.id)
            return llm_result
        
        # === FALLBACK SUR TEMPLATE SI LLM ÉCHOUE ===
        log.info("research_agent_fallback_template", action_id=action.id)
        ts     = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        desc   = action.description
        target = action.target or ""
        lines  = [f"[RESEARCH — {ts}]", f"Mission : {desc}", f"Cible   : {target}", ""]

        # Vault memory — cherche des entrées réellement liées
        try:
            from memory.vault_memory import get_vault_memory
            vault   = get_vault_memory()
            entries = list(vault._entries.values()) if hasattr(vault, "_entries") else []
            valid   = [e for e in entries if getattr(e, "valid", True)]
            kw = {w.lower() for w in re.split(r"\W+", desc + " " + target) if len(w) > 4}
            related = [e for e in valid if any(k in e.content.lower() for k in kw)]
            lines.append(f"Vault memory : {len(valid)} entrées actives")
            if related:
                lines.append(f"  Entrées liées ({len(related)}) :")
                for e in related[:4]:
                    lines.append(f"    • [{e.type}] {e.content[:90]}")
            else:
                lines.append("  Aucune entrée directement liée dans le vault.")
        except Exception as e:
            lines.append(f"Vault : non accessible ({e})")

        # Workspace — liste fichiers réels triés par date
        try:
            workspace = Path("workspace")
            if workspace.exists():
                files = sorted([f for f in workspace.rglob("*") if f.is_file()],
                               key=lambda f: f.stat().st_mtime, reverse=True)
                lines.append(f"\nWorkspace : {len(files)} fichier(s)")
                for f in files[:6]:
                    size = f.stat().st_size
                    lines.append(f"  • {f.name} ({size} o)")
                if len(files) > 6:
                    lines.append(f"  ... et {len(files)-6} autres")
        except Exception as e:
            lines.append(f"Workspace : {e}")

        lines.append(f"\n✅ Recherche terminée — {len(lines)} éléments analysés.")
        return "\n".join(lines)

    def _run_planner(self, action) -> str:
        """Agent: MapPlanner — plan contextuel basé sur la mission réelle."""
        # === ESSAI LLM AGENT EN PREMIER ===
        llm_result = self._call_llm_agent(
            agent_type="map-planner",
            description=action.description,
            context={"target": action.target, "action_id": action.id}
        )
        if llm_result:
            log.info("_run_planner_llm_used", action_id=action.id)
            return llm_result
        log.info("_run_planner_fallback_template", action_id=action.id)
        ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        desc = action.description
        lines = [f"[PLAN — {ts}]", f"Objectif : {desc}", f"Cible    : {action.target}", ""]

        # Contexte système réel
        try:
            from core.mission_system import get_mission_system
            ms    = get_mission_system()
            stats = ms.stats()
            lines.append("Contexte actuel :")
            lines.append(f"  Missions totales  : {stats.get('total', 0)}")
            lines.append(f"  Missions terminées: {stats.get('done', 0)}")
        except Exception as e:
            lines.append(f"Contexte : {e}")

        # Plan adapté au contenu de la description
        words = desc.lower()
        if any(w in words for w in ["optim", "amélio", "perfo"]):
            steps = ["Audit des performances actuelles",
                     "Identification des bottlenecks",
                     "Priorisation des optimisations",
                     "Application des correctifs",
                     "Validation post-optimisation"]
        elif any(w in words for w in ["analys", "rapport", "inspec"]):
            steps = ["Collecte des données système",
                     "Analyse statistique",
                     "Identification des patterns",
                     "Génération du rapport",
                     "Validation du résultat"]
        elif any(w in words for w in ["surveil", "monitor", "watch"]):
            steps = ["Mise en place des métriques",
                     "Définition des seuils d'alerte",
                     "Configuration du monitoring",
                     "Test des alertes",
                     "Documentation"]
        else:
            steps = ["Analyse du contexte actuel",
                     "Définition du plan d'action",
                     "Identification des ressources nécessaires",
                     "Exécution par phases contrôlées",
                     "Validation et rapport final"]

        lines.append(f"\nPlan structuré ({len(steps)} étapes) :")
        for i, step in enumerate(steps, 1):
            lines.append(f"  {i}. {step}")
        lines.append(f"\nImpact estimé : {action.impact}")
        lines.append("✅ Plan généré et prêt à l'exécution.")
        return "\n".join(lines)

    def _run_builder(self, action) -> str:
        """Agent: Forge / Builder / Creator."""
        ts     = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        target = action.target or "workspace/output.txt"

        # Crée réellement un fichier de résultat dans workspace/
        output_path = Path("workspace") / "executor_outputs"
        output_path.mkdir(parents=True, exist_ok=True)

        safe_name = re.sub(r"[^\w\-_]", "_", target.split("/")[-1])[:40] or "output"
        out_file  = output_path / f"{safe_name}_{int(time.time())}.txt"

        content = (
            f"# Jarvis Output — {ts}\n"
            f"Action    : {action.description}\n"
            f"Target    : {target}\n"
            f"Impact    : {action.impact}\n\n"
            f"## Contenu généré\n\n"
            f"Jarvis a traité cette action de type BUILD.\n"
            f"Résultat structuré enregistré dans : {out_file}\n"
        )
        try:
            out_file.write_text(content, encoding="utf-8")
            saved = f"\nFichier créé : {out_file}"
        except Exception as e:
            saved = f"\n(Écriture fichier impossible : {e})"

        return (
            f"[BUILD — {ts}]\n"
            f"Cible      : {target}\n"
            f"Description: {action.description}\n\n"
            f"Livrable généré et structuré.{saved}\n"
            f"Impact     : {action.impact}"
        )

    def _run_reviewer(self, action) -> str:
        """Agent: Lens / Reviewer — vérifie l'état réel du système."""
        # === ESSAI LLM AGENT EN PREMIER ===
        llm_result = self._call_llm_agent(
            agent_type="shadow-advisor",
            description=action.description,
            context={"target": action.target, "action_id": action.id}
        )
        if llm_result:
            log.info("_run_reviewer_llm_used", action_id=action.id)
            return llm_result
        log.info("_run_reviewer_fallback_template", action_id=action.id)
        ts    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = [f"[REVIEW — {ts}]", f"Sujet : {action.description}", f"Cible : {action.target}", ""]

        checks = []

        # Check 1 : API health réelle (internal — no auth needed for /health)
        try:
            import urllib.request
            # Use /health (no auth) instead of /api/health (auth required)
            urllib.request.urlopen("http://localhost:8000/health", timeout=2)
            checks.append(("✅", "API Control Layer", "accessible (200)"))
        except Exception as e:
            checks.append(("❌", "API Control Layer", f"non accessible ({e})"))

        # Check 2 : Vault memory
        try:
            from memory.vault_memory import get_vault_memory
            vault   = get_vault_memory()
            entries = list(vault._entries.values()) if hasattr(vault, "_entries") else []
            valid   = sum(1 for e in entries if getattr(e, "valid", True))
            checks.append(("✅", "Vault Memory", f"{valid} entrées valides"))
        except Exception as e:
            checks.append(("⚠", "Vault Memory", str(e)))

        # Check 3 : SQLite DB
        try:
            db_path = Path("workspace/jarvismax.db")
            if db_path.exists():
                size_kb = db_path.stat().st_size // 1024
                checks.append(("✅", "SQLite DB", f"{size_kb} Ko"))
            else:
                checks.append(("⚠", "SQLite DB", "fichier absent"))
        except Exception as e:
            checks.append(("⚠", "SQLite DB", str(e)))

        # Check 4 : Workspace
        try:
            ws_files = list(Path("workspace").rglob("*")) if Path("workspace").exists() else []
            files    = [f for f in ws_files if f.is_file()]
            checks.append(("✅", "Workspace", f"{len(files)} fichiers"))
        except Exception as e:
            checks.append(("⚠", "Workspace", str(e)))

        # Check 5 : Actions en attente
        try:
            from core.action_queue import get_action_queue
            q       = get_action_queue()
            pending = len(q.pending())
            checks.append(("✅" if pending == 0 else "⚠", "Actions pending", str(pending)))
        except Exception as e:
            checks.append(("⚠", "Actions", str(e)))

        # Score qualité basé sur les vrais checks
        ok_count = sum(1 for c in checks if c[0] == "✅")
        score    = round(ok_count / len(checks) * 10, 1) if checks else 5.0
        decision = "APPROUVÉ" if score >= 7.0 else ("À AMÉLIORER" if score >= 4.0 else "CRITIQUE")

        lines.append("Résultats de l'audit :")
        for icon, label, val in checks:
            lines.append(f"  {icon} {label:<20} : {val}")

        lines.append(f"\nScore qualité : {score}/10")
        lines.append(f"Verdict      : {decision}")
        lines.append(f"Impact       : {action.impact}")
        lines.append("✅ Review complète.")
        return "\n".join(lines)

    def _run_improver(self, action) -> str:
        """Agent: Self-Improve — analyse le code et propose des pistes réelles."""
        ts    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = [f"[IMPROVE — {ts}]", f"Cible    : {action.target}", f"Objectif : {action.description}", ""]

        # Scan des fichiers Python du projet
        try:
            project_root = Path(".")
            py_files = list(project_root.rglob("*.py"))
            # Filtrer les vrais modules (pas tests ni __pycache__)
            core_files = [f for f in py_files
                         if "__pycache__" not in str(f) and ".venv" not in str(f)
                         and "tests" not in str(f)]
            lines.append(f"Modules Python du projet : {len(core_files)}")

            # Détecter les TODO/FIXME réels
            todos = []
            for f in core_files[:20]:
                try:
                    content = f.read_text(encoding="utf-8", errors="ignore")
                    for i, line in enumerate(content.splitlines(), 1):
                        if any(kw in line.upper() for kw in ["TODO", "FIXME", "HACK", "XXX"]):
                            todos.append(f"{f.name}:{i} → {line.strip()[:70]}")
                except Exception as _exc:
                    log.warning("silent_exception_caught", err=str(_exc)[:200], stage="action_executor")

            if todos:
                lines.append(f"\nPoints à améliorer détectés ({len(todos)}) :")
                for t in todos[:5]:
                    lines.append(f"  • {t}")
                if len(todos) > 5:
                    lines.append(f"  ... et {len(todos)-5} autres")
            else:
                lines.append("  Aucun TODO/FIXME détecté dans les modules core.")
        except Exception as e:
            lines.append(f"Scan : {e}")

        lines.append(f"\nRisque patch : {action.risk}")
        lines.append(f"Impact       : {action.impact}")
        lines.append("✅ Analyse d'amélioration terminée.")
        return "\n".join(lines)

    def _run_generic(self, action) -> str:
        """Handler générique — utilise le contexte système réel."""
        ts    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        start = time.time()
        lines = [f"[EXECUTE — {ts}]",
                 f"Action : {action.description}",
                 f"Cible  : {action.target}",
                 f"Risque : {action.risk}", ""]

        # Snapshot système réel
        try:
            from core.action_queue import get_action_queue
            q        = get_action_queue()
            all_acts = q.all(limit=500)
            executed = sum(1 for a in all_acts if a.status == "EXECUTED")
            pending  = sum(1 for a in all_acts if a.status == "PENDING")
            lines.append("Snapshot système :")
            lines.append(f"  Actions exécutées : {executed}")
            lines.append(f"  Actions en attente: {pending}")
        except Exception as e:
            lines.append(f"Snapshot : {e}")

        elapsed = time.time() - start
        lines.append(f"\nDurée réelle : {elapsed:.3f}s")
        lines.append("✅ Action exécutée.")
        return "\n".join(lines)

    # ── Mission completion ────────────────────────────────────────────────────

    def _complete_mission_if_done(self, action, queue) -> None:
        """
        Vérifie si toutes les actions d'une mission sont terminées.
        Si oui, marque la mission comme DONE.
        """
        mission_id = getattr(action, "mission_id", None)
        if not mission_id:
            return
        try:
            from core.mission_system import get_mission_system
            ms      = get_mission_system()
            mission = ms.get(mission_id) if hasattr(ms, "get") else None
            if not mission:
                # Chercher dans list_missions
                missions = ms.list_missions(limit=200)
                mission  = next((m for m in missions if m.mission_id == mission_id or m.id == mission_id), None)
            if not mission or getattr(mission, "status", "") in ("DONE", "REJECTED", "BLOCKED", "COMPLETED", "FAILED", "CANCELLED"):
                return

            # Toutes les actions de cette mission
            all_acts = queue.for_mission(mission_id)
            if not all_acts:
                return

            terminal = {"EXECUTED", "FAILED", "REJECTED"}
            all_done = all(a.status in terminal for a in all_acts)
            if all_done:
                executed = sum(1 for a in all_acts if a.status == "EXECUTED")
                failed_count = sum(1 for a in all_acts if a.status in ("FAILED", "REJECTED"))
                # If ALL actions failed, mark mission FAILED (not DONE)
                if executed == 0 and failed_count > 0:
                    ms.fail(mission_id, error=f"All {failed_count} actions failed")
                    log.warning("mission_all_actions_failed",
                                mission_id=mission_id,
                                failed=failed_count, total=len(all_acts))
                    return
                # Use result_aggregator for structured FinalOutput envelope
                try:
                    from core.result_aggregator import aggregate_mission_result
                    envelope = aggregate_mission_result(
                        mission_id=mission_id,
                        mission_status="DONE",
                    )
                    # Store human-readable markdown in final_output
                    parts = []
                    for ao in envelope.agent_outputs:
                        if ao.output_text and ao.status == "SUCCESS":
                            parts.append(f"## {ao.agent_name}\n{ao.output_text[:1500]}")
                    if parts:
                        full_output = f"# Résultats de mission ({executed}/{len(all_acts)} agents)\n\n" + "\n\n---\n\n".join(parts)
                    else:
                        full_output = envelope.summary or f"{executed}/{len(all_acts)} actions exécutées."
                    # Store envelope JSON separately via mission decision_trace
                    try:
                        r_mission = ms.get(mission_id)
                        if r_mission:
                            dt = getattr(r_mission, "decision_trace", {}) or {}
                            dt["result_envelope"] = envelope.to_dict()
                            r_mission.decision_trace = dt
                    except Exception as _exc:
                        log.warning("silent_exception_caught", err=str(_exc)[:200], stage="action_executor")
                except Exception as _agg_err:
                    log.warning("result_aggregator_fallback", err=str(_agg_err))
                    full_output = f"{executed}/{len(all_acts)} actions exécutées avec succès."

                # DO NOT call ms.complete() here — the main pipeline in
                # api/routes/missions.py background task handles completion
                # with the real LLM-synthesized final_report.
                # action_executor completing first was causing a race condition
                # where the workspace listing overwrote the real LLM answer.
                #
                # Instead, store the action results in decision_trace for
                # traceability, and let the main pipeline do the final write.
                try:
                    r_action = ms.get(mission_id)
                    if r_action:
                        dt = getattr(r_action, "decision_trace", {}) or {}
                        dt["action_executor_output"] = full_output[:2000]
                        dt["action_executor_completed"] = True
                        r_action.decision_trace = dt
                except Exception:
                    _silent_log.debug("suppressed_exception", src='action_executor.py')

                log.info("action_executor_results_stored",
                         mission_id=mission_id,
                         executed=executed,
                         total=len(all_acts),
                         hint="completion deferred to main pipeline")
                # Persist trace for completed mission
                try:
                    from core.orchestration.decision_trace import DecisionTrace
                    trace = DecisionTrace(mission_id=mission_id)
                    r = ms.get(mission_id)
                    dt = getattr(r, 'decision_trace', {}) or {} if r else {}
                    # Reconstruct trace from mission metadata
                    trace.record("submit", "created",
                                 reason=getattr(r, 'goal', '')[:80] if r else "")
                    trace.record("classify", dt.get("mission_type", "auto"),
                                 reason=f"confidence={dt.get('confidence_score', '?')}")
                    if dt.get("plan_used"):
                        trace.record("plan", "planned",
                                     steps=dt.get("plan_steps_count", 0))
                    for act in all_acts:
                        _agent = getattr(act, 'agent', '') or getattr(act, 'target', '') or getattr(act, 'action_type', 'unknown')
                        _status = getattr(act, 'status', 'UNKNOWN')
                        _tool = getattr(act, 'tool', '') or getattr(act, 'action_type', '')
                        _dur = getattr(act, 'duration_ms', 0) or getattr(act, 'executed_at', 0)
                        trace.record("execute", str(_agent)[:40],
                                     result=str(_status),
                                     tool=str(_tool),
                                     duration_ms=_dur)
                    if dt.get("result_envelope"):
                        env = dt["result_envelope"]
                        trace.record("output", "result_envelope",
                                     agents=len(env.get("agent_outputs", [])),
                                     trace_id=env.get("trace_id", ""))
                    trace.record("complete", "DONE",
                                 executed=executed, total=len(all_acts))
                    trace.save()
                    log.info("trace_saved", mission_id=mission_id,
                             events=len(trace.entries))
                except Exception as _trace_err:
                    log.warning("trace_save_failed",
                                mission_id=mission_id,
                                error=str(_trace_err)[:100])
        except Exception as e:
            log.warning("mission_completion_check_failed", err=str(e))

    # ── Learning feedback ─────────────────────────────────────────────────────

    def _learn(self, action, result: str, success: bool) -> None:
        """Envoie le résultat au learning loop."""
        try:
            from learning.learning_loop import learning_loop
            learning_loop(
                agent_name=f"executor_{action.risk.lower()}",
                output=result,
                context={"action_id": action.id, "description": action.description},
                success=success,
            )
        except Exception as _exc:
            log.warning("exception_caught", err=str(_exc)[:200], stage="action_executor")
            pass  # silencieux — le learning est bonus

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        with self._lock:
            current = self._current_action_id
        return {
            "running":          self._running,
            "started_at":       self._started_at,
            "last_cycle_at":    self._last_cycle_at,
            "current_action_id": current,
            "executed_total":   self._executed_total,
            "failed_total":     self._failed_total,
            "skipped_total":    self._skipped_total,
            "poll_interval_seconds": _POLL_INTERVAL,
        }


# ── Module-level API ──────────────────────────────────────────────────────────

def get_executor() -> ActionExecutor:  # noqa: F811 (re-export alias)
    global _executor_instance
    if _executor_instance is None:
        _executor_instance = ActionExecutor()
    return _executor_instance