"""
JARVIS MAX — ParallelExecutor
Exécution simultanée de plusieurs agents via asyncio.gather().

Architecture :
    tasks = [{"agent": "scout-research", "task": "..."}, ...]
    results = await ParallelExecutor(settings).run(tasks, session)

Caractéristiques :
- Timeout individuel par agent (configurable)
- Timeout global pour l'ensemble du batch
- Les échecs d'un agent n'interrompent pas les autres
- Résultats indexés par nom d'agent
- Compatible avec AgentCrew existant

Interface :
    pe      = ParallelExecutor(settings)
    results = await pe.run(tasks, session)          # → dict[agent_name, str]
    report  = await pe.run_with_plan(session, emit) # → dict + emit progress
"""
from __future__ import annotations

import asyncio
import inspect
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Awaitable

import structlog

from core.state import JarvisSession

log = structlog.get_logger()

CB = Callable[[str], Awaitable[None]]

# Timeouts par défaut
_DEFAULT_AGENT_TIMEOUT = 90      # secondes par agent
_DEFAULT_GLOBAL_TIMEOUT = 300    # secondes pour tout le batch

_TRACE_LOG = Path("workspace/execution_trace.jsonl")
# Rotation: keep max 50 MB of trace history.
# When the file exceeds this, the oldest half is dropped (fast tail-truncation strategy).
_TRACE_LOG_MAX_BYTES = 50 * 1024 * 1024   # 50 MB


def _rotate_trace_log_if_needed() -> None:
    """Rotate execution_trace.jsonl when it exceeds _TRACE_LOG_MAX_BYTES.

    Strategy: keep the newest ~half of the file by reading all lines,
    dropping the oldest 50%, and rewriting. Simple and dependency-free.
    Fail-open: any error is silently ignored (trace is optional observability).
    """
    try:
        if not _TRACE_LOG.exists():
            return
        if _TRACE_LOG.stat().st_size < _TRACE_LOG_MAX_BYTES:
            return
        lines = _TRACE_LOG.read_bytes().split(b"\n")
        lines = [l for l in lines if l.strip()]
        keep = lines[len(lines) // 2:]   # keep newest half
        _TRACE_LOG.write_bytes(b"\n".join(keep) + b"\n")
        log.info("trace_log_rotated",
                 kept_lines=len(keep),
                 dropped_lines=len(lines) - len(keep))
    except Exception:
        _silent_log.debug("suppressed_exception", src='parallel_executor.py')


# Seuil d'output vide — déclenche un retry automatique
_MIN_OUTPUT_LEN = 10


@dataclass
class AgentTrace:
    """Trace d'exécution d'un agent individuel."""
    agent:        str
    input_summary:  str    # 200 chars max du goal
    output_summary: str    # 200 chars max de l'output
    latency_ms:   int
    status:       str      # SUCCESS / FAILED / RETRIED / TIMEOUT / FALLBACK
    retry_count:  int      = 0
    error:        str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _append_trace_log(mission_id: str, trace: AgentTrace) -> None:
    """Append un AgentTrace dans workspace/execution_trace.jsonl (fail-open)."""
    try:
        _TRACE_LOG.parent.mkdir(parents=True, exist_ok=True)
        _rotate_trace_log_if_needed()
        record = {"mission_id": mission_id, "ts": time.time(), **trace.to_dict()}
        with _TRACE_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        _silent_log.debug("suppressed_exception", src='parallel_executor.py')


class AgentResult:
    """Résultat d'un agent individuel."""
    __slots__ = ("agent", "task", "output", "success", "error", "duration_ms",
                 "agent_output", "trace")

    def __init__(
        self,
        agent: str,
        task: str,
        output: str = "",
        success: bool = True,
        error: str = "",
        duration_ms: int = 0,
        agent_output=None,
        trace: AgentTrace | None = None,
    ):
        self.agent        = agent
        self.task         = task
        self.output       = output
        self.success      = success
        self.error        = error
        self.duration_ms  = duration_ms
        self.agent_output = agent_output   # AgentOutput | None
        self.trace        = trace          # AgentTrace  | None

    def to_dict(self) -> dict:
        d = {
            "agent":       self.agent,
            "task":        self.task,
            "output":      self.output[:800],
            "success":     self.success,
            "error":       self.error,
            "duration_ms": self.duration_ms,
        }
        if self.agent_output is not None:
            d["agent_output"] = self.agent_output.to_dict()
        if self.trace is not None:
            d["trace"] = self.trace.to_dict()
        return d


class ParallelExecutor:
    """
    Lance plusieurs agents en parallèle et collecte leurs résultats.

    Usage :
        pe = ParallelExecutor(settings)
        results = await pe.run(
            tasks=[
                {"agent": "scout-research", "task": "Analyser les tendances IA"},
                {"agent": "shadow-advisor", "task": "Identifier les risques"},
                {"agent": "map-planner",    "task": "Planifier les prochaines étapes"},
            ],
            session=session,
        )
        # results["scout-research"] → texte du résultat
    """

    def __init__(
        self,
        settings,
        agent_timeout: int = _DEFAULT_AGENT_TIMEOUT,
        global_timeout: int = _DEFAULT_GLOBAL_TIMEOUT,
    ):
        self.s              = settings
        self.agent_timeout  = agent_timeout
        self.global_timeout = global_timeout
        self._crew          = None

    # ── Lazy AgentCrew ────────────────────────────────────────

    @property
    def crew(self):
        if not self._crew:
            from agents.crew import AgentCrew
            self._crew = AgentCrew(self.s)
        return self._crew

    # ── API principale ────────────────────────────────────────

    async def run(
        self,
        tasks: list[dict],
        session: JarvisSession,
        emit: CB | None = None,
    ) -> dict[str, AgentResult]:
        """
        Exécute les tâches en parallèle.
        Retourne un dict {agent_name: AgentResult}.

        - Un timeout individuel protège contre les agents bloquants.
        - Un timeout global couvre l'ensemble du batch.
        - Les échecs sont capturés et reportés sans interrompre les autres.
        """
        if not tasks:
            return {}

        # Garantir que _emit est toujours une coroutine awaitable.
        # "lambda m: asyncio.sleep(0)" retourne une coroutine non-awaited → bug.
        # On utilise un no-op async explicite comme valeur par défaut.
        async def _noop(msg: str) -> None:
            pass
        _emit = emit or _noop
        if not inspect.iscoroutinefunction(_emit):
            _sync_emit = _emit
            async def _emit(msg: str):  # type: ignore[misc]
                _sync_emit(msg)

        # ── ResourceGuard : vérifier que la machine peut supporter ce batch ──
        try:
            from core.resource_guard import get_resource_guard
            guard = get_resource_guard(self.s)
            snap  = guard.get_status()
            from core.resource_guard import SystemStatus
            if snap.status == SystemStatus.BLOCKED:
                log.error(
                    "parallel_blocked_oom",
                    ram_avail_mb=snap.ram_avail_mb,
                    tasks=len(tasks),
                )
                await _emit(
                    f"[ResourceGuard] BLOQUE — RAM critique ({snap.ram_avail_mb}MB libre). "
                    f"Tâche refusée pour protéger la machine."
                )
                return {}
            if snap.status == SystemStatus.SAFE:
                # En mode SAFE : tronquer à max 1 agent simultané
                log.warning(
                    "parallel_safe_mode_active",
                    ram_avail_mb=snap.ram_avail_mb,
                    tasks_requested=len(tasks),
                    tasks_allowed=1,
                )
                await _emit(
                    f"[ResourceGuard] Mode SAFE — RAM basse ({snap.ram_avail_mb}MB). "
                    f"Exécution séquentielle (1 agent à la fois)."
                )
                tasks = tasks[:1]  # n'exécuter qu'un seul agent
        except Exception:
            pass  # ResourceGuard absent → continuer normalement

        await _emit(
            f"[ParallelExecutor] Lancement de {len(tasks)} agent(s) en parallèle..."
        )
        log.info("parallel_start", tasks=len(tasks), sid=session.session_id)

        # ── Garantir que chaque agent peut trouver sa tâche via BaseAgent._task()
        # sans toucher au session dans _run_one() (fix bug mutation concurrente).
        # On fusionne les tâches manquantes dans session.agents_plan une seule fois,
        # avant le gather — opération non concurrente, donc thread-safe.
        _plan_names = {t.get("agent") for t in session.agents_plan}
        for t in tasks:
            if t.get("agent") not in _plan_names:
                session.agents_plan.append(t)
                _plan_names.add(t.get("agent"))

        t0 = time.monotonic()

        try:
            raw_results = await asyncio.wait_for(
                asyncio.gather(
                    *[self._run_one(t, session) for t in tasks],
                    return_exceptions=True,
                ),
                timeout=self.global_timeout,
            )
        except asyncio.TimeoutError:
            log.warning("parallel_global_timeout",
                        timeout=self.global_timeout, tasks=len(tasks))
            await _emit(
                f"[ParallelExecutor] Timeout global ({self.global_timeout}s) — "
                f"résultats partiels."
            )
            return {}

        # Assembler les résultats
        results: dict[str, AgentResult] = {}
        ok, failed = 0, 0

        for i, (task, raw) in enumerate(zip(tasks, raw_results)):
            name = task.get("agent", f"agent_{i}")
            if isinstance(raw, AgentResult):
                results[name] = raw
                if raw.success:
                    ok += 1
                else:
                    failed += 1
            else:
                # Exception non capturée (ne devrait pas arriver — _run_one catch-all)
                results[name] = AgentResult(
                    agent=name, task=task.get("task", ""),
                    success=False, error=str(raw)[:200],
                )
                failed += 1

        elapsed = round(time.monotonic() - t0, 1)
        await _emit(
            f"[ParallelExecutor] {ok}/{len(tasks)} agents OK "
            f"({failed} échoué(s)) — {elapsed}s"
        )
        log.info("parallel_done",
                 ok=ok, failed=failed, duration_s=elapsed, sid=session.session_id)

        return results

    async def run_with_plan(
        self,
        session: JarvisSession,
        emit: CB | None = None,
    ) -> dict[str, AgentResult]:
        """
        Exécute le plan existant de la session en parallèle (session.agents_plan).
        Pratique pour l'intégration dans _run_auto() de l'orchestrateur.
        """
        tasks = session.agents_plan or []
        return await self.run(tasks, session, emit=emit)

    async def run_with_replan(
        self,
        tasks:   list[dict],
        session: JarvisSession,
        emit:    CB | None = None,
        max_replan_rounds: int = 1,
    ) -> dict[str, AgentResult]:
        """
        Exécution avec replan dynamique si des agents critiques échouent.

        Stratégie de replan :
          1. Exécuter le plan original
          2. Si un agent P1/P2 échoue → tenter un fallback
             - scout-research échoue → shadow-advisor en remplacement
             - forge-builder échoue  → map-planner (plan alternatif)
             - map-planner échoue    → shadow-advisor
          3. Maximum max_replan_rounds tours de replan
          4. Émettre un message de replan si nécessaire

        Retourne tous les résultats (originaux + replan fusionnés).
        """
        async def _noop_rp(msg: str) -> None:
            pass
        _emit = emit or _noop_rp

        results = await self.run(tasks, session, emit=_emit)
        if not results:
            return results

        # Identifier les agents critiques qui ont échoué
        failed = [
            task for task in tasks
            if not results.get(task.get("agent", ""), AgentResult(
                agent="", task="", success=True
            )).success
            and task.get("priority", 2) <= 2  # priorité 1 ou 2 seulement
        ]

        if not failed or max_replan_rounds <= 0:
            return results

        # Table de fallback (agent échoué → agent de remplacement)
        _FALLBACK_MAP: dict[str, str] = {
            "scout-research": "shadow-advisor",
            "forge-builder":  "map-planner",
            "map-planner":    "shadow-advisor",
            "shadow-advisor": "scout-research",
            "web-scout":      "scout-research",
        }

        replan_tasks: list[dict] = []
        for task in failed:
            agent_name = task.get("agent", "")
            fallback   = _FALLBACK_MAP.get(agent_name)
            if fallback and fallback not in results:
                replan_tasks.append({
                    "agent":    fallback,
                    "task":     task.get("task", session.mission_summary),
                    "priority": task.get("priority", 2),
                    "_replan":  True,
                    "_replaces": agent_name,
                })

        if replan_tasks:
            await _emit(
                f"[Replan] {len(failed)} agent(s) en echec — "
                f"replan : {', '.join(t['agent'] for t in replan_tasks)}"
            )
            log.info("parallel_replan", failed=[t.get("agent") for t in failed],
                     replan=[t["agent"] for t in replan_tasks],
                     sid=session.session_id)
            replan_results = await self.run(replan_tasks, session, emit=_emit)
            results.update(replan_results)

        return results

    # ── Exécution d'un agent individuel ──────────────────────

    async def _run_one(
        self,
        task: dict,
        session: JarvisSession,
    ) -> AgentResult:
        """
        Lance un agent avec timeout individuel.
        - Si output vide (< _MIN_OUTPUT_LEN chars) → 1 retry automatique.
        - Normalise l'output via AgentOutput.from_raw().
        - Construit un AgentTrace et le log dans workspace/execution_trace.jsonl.
        Capture toutes les exceptions — ne propage jamais.
        """
        from agents.agent_output import AgentOutput

        agent_name = task.get("agent", "unknown")
        agent_task = task.get("task", session.mission_summary or "")
        mission_id = getattr(session, "session_id", "") or ""

        t0 = time.monotonic()

        # ── ResourceGuard : slot d'exécution ─────────────────
        _guard = None
        _slot_acquired = False
        try:
            from core.resource_guard import get_resource_guard
            _guard = get_resource_guard(self.s)
            _slot_acquired = _guard.acquire_slot(agent_name, timeout=5.0)
            if not _slot_acquired:
                log.warning("parallel_agent_no_slot", agent=agent_name)
                trace = AgentTrace(
                    agent=agent_name,
                    input_summary=agent_task[:200],
                    output_summary="",
                    latency_ms=int((time.monotonic() - t0) * 1000),
                    status="FAILED",
                    error="Slot refusé par ResourceGuard (surcharge)",
                )
                _append_trace_log(mission_id, trace)
                return AgentResult(
                    agent=agent_name, task=agent_task,
                    success=False, error=trace.error, trace=trace,
                )
        except Exception:
            pass  # ResourceGuard absent → continuer

        individual_timeout = task.get("timeout", self.agent_timeout)
        retry_count = 0
        status = "SUCCESS"
        output = ""
        err_str: str | None = None

        try:
            output = await asyncio.wait_for(
                self.crew.run(agent_name, session),
                timeout=individual_timeout,
            ) or ""

            # Retry si output trop court
            if len(output) < _MIN_OUTPUT_LEN:
                retry_count = 1
                log.warning("parallel_agent_empty_output",
                            agent=agent_name, output_len=len(output))
                try:
                    output = await asyncio.wait_for(
                        self.crew.run(agent_name, session),
                        timeout=individual_timeout,
                    ) or ""
                    status = "RETRIED"
                except Exception as retry_err:
                    output = output or ""
                    status = "FALLBACK"
                    err_str = str(retry_err)[:200]

            ms = int((time.monotonic() - t0) * 1000)
            log.info("parallel_agent_done",
                     agent=agent_name, ms=ms, output_len=len(output))

            ao = AgentOutput.from_raw(output)
            trace = AgentTrace(
                agent=agent_name,
                input_summary=agent_task[:200],
                output_summary=output[:200],
                latency_ms=ms,
                status=status,
                retry_count=retry_count,
                error=err_str,
            )
            _append_trace_log(mission_id, trace)
            return AgentResult(
                agent=agent_name, task=agent_task,
                output=output, success=True, duration_ms=ms,
                agent_output=ao, trace=trace,
            )

        except asyncio.TimeoutError:
            ms = int((time.monotonic() - t0) * 1000)
            log.warning("parallel_agent_timeout", agent=agent_name, timeout=individual_timeout)
            trace = AgentTrace(
                agent=agent_name,
                input_summary=agent_task[:200],
                output_summary="",
                latency_ms=ms,
                status="TIMEOUT",
                retry_count=retry_count,
                error=f"Timeout ({individual_timeout}s)",
            )
            _append_trace_log(mission_id, trace)
            return AgentResult(
                agent=agent_name, task=agent_task, success=False,
                error=trace.error, duration_ms=ms, trace=trace,
            )

        except Exception as e:
            ms = int((time.monotonic() - t0) * 1000)
            log.error("parallel_agent_error", agent=agent_name, err=str(e))
            trace = AgentTrace(
                agent=agent_name,
                input_summary=agent_task[:200],
                output_summary="",
                latency_ms=ms,
                status="FAILED",
                retry_count=retry_count,
                error=str(e)[:300],
            )
            _append_trace_log(mission_id, trace)
            return AgentResult(
                agent=agent_name, task=agent_task, success=False,
                error=str(e)[:300], duration_ms=ms, trace=trace,
            )

        finally:
            # Libérer le slot ResourceGuard quoi qu'il arrive
            if _guard and _slot_acquired:
                try:
                    _guard.release_slot(agent_name)
                except Exception:
                    _silent_log.debug("suppressed_exception", src='parallel_executor.py')

    # ── Utilitaires ───────────────────────────────────────────

    @staticmethod
    def group_by_priority(tasks: list[dict]) -> list[list[dict]]:
        """
        Regroupe les tâches par priorité pour une exécution séquentielle
        par groupe mais parallèle à l'intérieur de chaque groupe.

        Exemple :
            P1: [vault-memory]
            P2: [scout-research, shadow-advisor, map-planner]  ← parallèle
            P3: [lens-reviewer]
        """
        groups: dict[int, list[dict]] = {}
        for t in tasks:
            p = t.get("priority", 2)
            groups.setdefault(p, []).append(t)
        return [groups[k] for k in sorted(groups)]

    @staticmethod
    def outputs_to_dict(results: dict[str, "AgentResult"]) -> dict[str, str]:
        """Convertit les AgentResult en dict {agent: output} pour le Synthesizer."""
        return {
            name: r.output
            for name, r in results.items()
            if r.success and r.output
        }
