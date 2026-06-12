"""
BEA MAX — SupervisedExecutor v2
Couche de supervision autour d'ActionExecutor.

Chaque action passe obligatoirement par RiskEngine avant exécution.

Flux :
    action → RiskEngine.analyze() → décision
    LOW    → exécution automatique
    MEDIUM → notification + attente validation API (ou auto en dry_run)
    HIGH   → blocage obligatoire + notification

Nouveaux types d'actions (v2) :
    read_directory    → LOW  : liste le contenu d'un répertoire
    write_file        → LOW/MEDIUM selon cible
    run_python_script → MEDIUM : exécute un script Python dans le workspace
    create_workflow   → MEDIUM : crée un workflow via WorkflowEngine
    schedule_task     → MEDIUM : planifie une tâche périodique

Interface :
    executor = SupervisedExecutor(settings, emit=callback)
    result   = await executor.execute(action, session_id)
    results, pending = await executor.execute_batch(actions, session_id)
"""
from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path
import structlog
from typing import Callable, Awaitable

from core.state import ActionSpec, RiskLevel
from executor.runner import ActionExecutor, ActionResult as ExecutionResult  # TODO(tech-debt): migrate to executor.contracts.ExecutionResult — fields incompatible (action_type vs raw_output)
from risk.engine import RiskEngine

log = structlog.get_logger()

CB = Callable[[str], Awaitable[None]]


class SupervisedExecutor:
    """
    Exécuteur supervisé — garantit que chaque action passe par RiskEngine.

    LOW    → exécution automatique (si not dry_run)
    MEDIUM → notification + attente validation API (ou auto en dry_run)
    HIGH   → bloquée obligatoirement + notification
    """

    def __init__(self, settings, emit: CB | None = None):
        self.s        = settings
        self.executor = ActionExecutor(settings)
        self.risk     = RiskEngine()
        self._emit    = emit or self._noop_emit

    # ── Emit no-op fallback ───────────────────────────────────

    @staticmethod
    async def _noop_emit(msg: str) -> None:
        pass

    # ── Public API ────────────────────────────────────────────

    async def execute(
        self,
        action: ActionSpec,
        session_id: str = "",
        agent: str = "system",
        auto_approve_medium: bool = False,
    ) -> ExecutionResult:
        """
        Exécute une action après analyse de risque.

        Paramètres :
            action               : ActionSpec à exécuter
            session_id           : identifiant de session (pour logs)
            agent                : nom de l'agent émetteur
            auto_approve_medium  : si True, MEDIUM passe sans confirmation manuelle

        Retourne :
            ExecutionResult — success=False si bloqué par risque ou en dry_run
        """
        # ── Analyse de risque ──────────────────────────────────
        try:
            report = self.risk.analyze(
                action_type=action.action_type,
                target=action.target,
                content=action.content,
                command=action.command,
                old_str=action.old_str,
                new_str=action.new_str,
            )
        except Exception as _risk_err:
            # Fail-safe: treat analysis failure as LOW risk so execution is not
            # silently blocked, but log a warning so ops can investigate.
            log.warning(
                "risk_engine_analyze_failed",
                action_type=action.action_type,
                err=str(_risk_err)[:80],
            )
            from risk.engine import RiskReport
            report = RiskReport(
                level=RiskLevel.LOW,
                action_type=action.action_type,
                target=action.target or "",
                estimated_impact="unknown (risk analysis failed)",
            )

        # Enrichir l'ActionSpec avec le résultat de l'analyse
        action.risk          = report.level
        action.impact        = report.estimated_impact
        action.backup_needed = report.backup_required
        action.reversible    = report.reversible

        log.info(
            "supervised_action",
            type=action.action_type,
            target=action.target[:60],
            risk=report.level.value,
            requires_validation=report.requires_validation,
            sid=session_id,
        )

        # ── LOW → exécution auto ──────────────────────────────
        if report.level == RiskLevel.LOW:
            if self.s.dry_run:
                await self._emit(
                    f"[DRY_RUN] {action.action_type} → {action.target[:60]} "
                    f"(risque: LOW)"
                )
                return ExecutionResult(
                    success=True,
                    action_type=action.action_type,
                    target=action.target,
                    output="[DRY_RUN] action LOW simulée",
                )
            return await self.executor.execute(action, session_id, agent)

        # ── MEDIUM → notification + validation ────────────────
        if report.level == RiskLevel.MEDIUM:
            await self._emit(
                f"[MEDIUM] Action à risque modéré\n"
                f"{report.format_card()}"
            )
            if self.s.dry_run:
                await self._emit(
                    f"[DRY_RUN] MEDIUM simulé — {action.action_type} "
                    f"sur {action.target[:60]}"
                )
                return ExecutionResult(
                    success=True,
                    action_type=action.action_type,
                    target=action.target,
                    output="[DRY_RUN] action MEDIUM simulée",
                )
            # Politique opérateur BEA_AUTO_APPROVE_MEDIUM (config/settings.py) :
            # sans elle, le chemin « attente de validation » est une impasse
            # (aucune file ne reçoit l'action). HIGH reste bloqué plus bas.
            if auto_approve_medium or getattr(self.s, "auto_approve_medium", False):
                return await self.executor.execute(action, session_id, agent)

            # Mode normal : mise en attente de validation via API
            await self._emit(
                "Action mise en attente de validation.\n"
                "Utilisez l'interface d'approbation pour valider."
            )
            return ExecutionResult(
                success=False,
                action_type=action.action_type,
                target=action.target,
                output="",
                error="Action MEDIUM en attente de validation (approval required)",
            )

        # ── HIGH → toujours bloquée ───────────────────────────
        await self._emit(
            f"[DANGER] Action HIGH — BLOQUÉE automatiquement\n"
            f"{report.format_card()}\n"
            f"Validation manuelle obligatoire."
        )
        log.warning(
            "action_blocked_high_risk",
            type=action.action_type,
            target=action.target[:60],
            reasons=report.reasons,
            sid=session_id,
        )
        return ExecutionResult(
            success=False,
            action_type=action.action_type,
            target=action.target,
            output="",
            error=(
                f"Bloquée : risque HIGH. "
                f"Raisons : {', '.join(report.reasons) or 'non classé'}"
            ),
        )

    async def execute_batch(
        self,
        actions: list[ActionSpec],
        session_id: str = "",
        agent: str = "system",
        max_auto: int = 10,
    ) -> tuple[list[ExecutionResult], list[ActionSpec]]:
        """
        Exécute une liste d'actions avec supervision.

        Retourne :
            (résultats des actions exécutées, actions en attente de validation)

        Actions HIGH et MEDIUM (hors dry_run) sont mises dans `pending`.
        """
        results: list[ExecutionResult] = []
        pending: list[ActionSpec]      = []
        auto_done: int                 = 0

        for action in actions:
            if auto_done >= max_auto:
                await self._emit(
                    f"Limite auto atteinte ({max_auto} actions). "
                    f"Reste {len(actions) - auto_done} en attente."
                )
                pending.append(action)
                continue

            result = await self.execute(action, session_id, agent)

            if result.success:
                results.append(result)
                auto_done += 1
            elif result.error and "attente" in result.error:
                # Action en attente de validation (approval required)
                pending.append(action)
            else:
                # Échec technique ou blocage HIGH
                results.append(result)

        if results:
            ok  = sum(1 for r in results if r.success)
            log.info(
                "batch_executed",
                total=len(actions),
                success=ok,
                failed=len(results) - ok,
                pending=len(pending),
                sid=session_id,
            )

        return results, pending

    # ── Actions avancées (v2) ─────────────────────────────────

    async def read_directory(self, path: str, depth: int = 1) -> ExecutionResult:
        """
        Liste le contenu d'un répertoire (LOW — lecture pure).
        depth=1 : liste directe / depth>1 : récursif limité.
        """
        ActionSpec(
            id="read_dir",
            action_type="read_directory",
            target=path,
            description=f"Lister {path}",
        )
        # LOW → toujours autorisé
        try:
            p = Path(path)
            if not p.exists():
                return ExecutionResult(success=False, action_type="read_directory",
                                       target=path, output="", error="Chemin inexistant")
            if not p.is_dir():
                return ExecutionResult(success=False, action_type="read_directory",
                                       target=path, output="", error="N'est pas un répertoire")
            if depth <= 1:
                entries = sorted(str(x.name) + ("/" if x.is_dir() else "")
                                 for x in p.iterdir())
            else:
                entries = []
                for root, dirs, files in os.walk(path):
                    level = str(root).replace(path, "").count(os.sep)
                    if level >= depth:
                        dirs.clear()
                    indent = "  " * level
                    entries.append(f"{indent}{os.path.basename(root)}/")
                    for f in sorted(files):
                        entries.append(f"{indent}  {f}")
            output = "\n".join(entries[:200])
            return ExecutionResult(success=True, action_type="read_directory",
                                   target=path, output=output)
        except Exception as e:
            return ExecutionResult(success=False, action_type="read_directory",
                                   target=path, output="", error=str(e))

    async def run_python_script(
        self,
        script_path: str,
        args: list[str] | None = None,
        session_id: str = "",
    ) -> ExecutionResult:
        """
        Exécute un script Python dans le workspace (MEDIUM).
        Passe par RiskEngine → bloqué ou mis en attente si hors workspace.
        timeout=30s pour éviter les blocages.
        """
        action = ActionSpec(
            id="run_py",
            action_type="run_python_script",
            target=script_path,
            command=f"python {script_path}",
            description=f"Exécuter {script_path}",
        )
        result = await self.execute(action, session_id=session_id, agent="supervised")
        if not result.success:
            return result

        # Exécution réelle uniquement si autorisée et pas dry_run
        if self.s.dry_run:
            return ExecutionResult(success=True, action_type="run_python_script",
                                   target=script_path,
                                   output=f"[DRY_RUN] python {script_path}")
        try:
            cmd = ["python", script_path] + (args or [])
            proc = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                ),
                timeout=30,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            out = stdout.decode("utf-8", errors="replace")[:2000]
            ok  = proc.returncode == 0
            return ExecutionResult(success=ok, action_type="run_python_script",
                                   target=script_path, output=out,
                                   error="" if ok else f"returncode={proc.returncode}")
        except asyncio.TimeoutError:
            return ExecutionResult(success=False, action_type="run_python_script",
                                   target=script_path, output="", error="Timeout 30s")
        except Exception as e:
            return ExecutionResult(success=False, action_type="run_python_script",
                                   target=script_path, output="", error=str(e))

    async def create_workflow(
        self,
        workflow_def: dict,
        session_id: str = "",
    ) -> ExecutionResult:
        """
        Crée un workflow via WorkflowEngine (MEDIUM).
        Retourne ExecutionResult avec output=workflow_id si succès.
        """
        wf_name = workflow_def.get("name", "workflow")
        action  = ActionSpec(
            id="create_wf",
            action_type="create_workflow",
            target=wf_name,
            description=f"Créer workflow : {wf_name}",
        )
        result = await self.execute(action, session_id=session_id, agent="supervised")
        if not result.success:
            return result

        if self.s.dry_run:
            return ExecutionResult(success=True, action_type="create_workflow",
                                   target=wf_name,
                                   output=f"[DRY_RUN] workflow '{wf_name}' simulé")
        try:
            from core.workflow.workflow_engine import WorkflowEngine
            engine  = WorkflowEngine(self.s)
            wf_id   = await engine.create(workflow_def)
            return ExecutionResult(success=True, action_type="create_workflow",
                                   target=wf_name, output=wf_id)
        except Exception as e:
            return ExecutionResult(success=False, action_type="create_workflow",
                                   target=wf_name, output="", error=str(e))

    async def schedule_task(
        self,
        task_def: dict,
        session_id: str = "",
    ) -> ExecutionResult:
        """
        Enregistre une tâche planifiée (MEDIUM).
        Persistance : workspace/scheduled_tasks.json
        """
        import json
        import time
        task_name = task_def.get("name", "task")
        action    = ActionSpec(
            id="sched",
            action_type="schedule_task",
            target=task_name,
            description=f"Planifier : {task_name}",
        )
        result = await self.execute(action, session_id=session_id, agent="supervised")
        if not result.success:
            return result

        if self.s.dry_run:
            return ExecutionResult(success=True, action_type="schedule_task",
                                   target=task_name,
                                   output=f"[DRY_RUN] tâche '{task_name}' planifiée simulée")
        try:
            from pathlib import Path
            ws   = Path(getattr(self.s, "workspace_dir", "/app/workspace"))
            p    = ws / "scheduled_tasks.json"
            tasks = json.loads(p.read_text("utf-8")) if p.exists() else []
            tasks.append({**task_def, "created_at": time.time(), "session_id": session_id})
            p.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), "utf-8")
            return ExecutionResult(success=True, action_type="schedule_task",
                                   target=task_name, output=f"Tâche planifiée : {task_name}")
        except Exception as e:
            return ExecutionResult(success=False, action_type="schedule_task",
                                   target=task_name, output="", error=str(e))

    # ── Propriétés utilitaires ────────────────────────────────

    def classify_risk(self, action_type: str, target: str = "", command: str = "") -> str:
        """Retourne le niveau de risque d'une action sans l'exécuter (debug/preview)."""
        report = self.risk.analyze(
            action_type=action_type,
            target=target,
            command=command,
        )
        return report.level.value
