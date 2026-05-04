"""
JARVIS MAX — WorkflowEngine v1
Création, persistance et exécution de workflows multi-étapes.

Un workflow est une séquence d'étapes (steps) déclenchées par un trigger.
Persistance : fichiers JSON dans workspace/workflows/.

Structure d'un workflow :
    {
      "id":          "wf_abc12345",
      "name":        "daily_report",
      "description": "Rapport journalier automatique",
      "trigger":     "cron 08:00",          # cron | manual | event:<nom>
      "steps": [
          {"agent": "scout-research", "task": "Collecter les nouvelles IA du jour"},
          {"agent": "shadow-advisor", "task": "Synthétiser les points clés"}
      ],
      "created_at": 1710000000.0,
      "updated_at": 1710000000.0,
      "enabled":    true
    }

Interface :
    engine = WorkflowEngine(settings)
    wf_id  = await engine.create(workflow_def)
    result = await engine.execute(wf_id, emit=callback)
    wfs    = engine.list_workflows()
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Callable, Awaitable
import structlog

log = structlog.get_logger()

CB = Callable[[str], Awaitable[None]]

# Champs obligatoires dans un workflow
_REQUIRED = {"name", "steps"}

# Triggers supportés
_VALID_TRIGGERS = {"manual", "cron", "event"}


class WorkflowValidationError(ValueError):
    pass


class WorkflowEngine:
    """
    Crée, valide, sauvegarde et exécute des workflows.
    Pas de dépendance cloud. Les agents sont exécutés via AgentCrew.
    """

    def __init__(self, settings):
        self.s    = settings
        self._dir = self._resolve_dir()

    # ── Persistance ───────────────────────────────────────────

    def _resolve_dir(self) -> Path:
        base = Path(getattr(self.s, "workspace_dir", "/app/workspace"))
        d = base / "workflows"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _path(self, wf_id: str) -> Path:
        return self._dir / f"{wf_id}.json"

    def _load(self, wf_id: str) -> dict:
        p = self._path(wf_id)
        if not p.exists():
            raise FileNotFoundError(f"Workflow '{wf_id}' introuvable.")
        return json.loads(p.read_text("utf-8"))

    def _save(self, wf: dict) -> None:
        wf["updated_at"] = time.time()
        self._path(wf["id"]).write_text(
            json.dumps(wf, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ── Validation ────────────────────────────────────────────

    @staticmethod
    def _validate(definition: dict) -> None:
        missing = _REQUIRED - set(definition.keys())
        if missing:
            raise WorkflowValidationError(
                f"Champs obligatoires manquants : {missing}"
            )
        steps = definition.get("steps", [])
        if not isinstance(steps, list) or not steps:
            raise WorkflowValidationError(
                "steps doit être une liste non vide."
            )
        for i, s in enumerate(steps):
            if not isinstance(s, dict) or "agent" not in s:
                raise WorkflowValidationError(
                    f"Étape {i} invalide : champ 'agent' manquant."
                )
        trigger = definition.get("trigger", "manual")
        trigger_type = trigger.split()[0] if trigger else "manual"
        if trigger_type not in _VALID_TRIGGERS:
            raise WorkflowValidationError(
                f"Trigger invalide : '{trigger_type}'. "
                f"Valeurs acceptées : {_VALID_TRIGGERS}"
            )

    # ── API publique ──────────────────────────────────────────

    async def create(self, definition: dict) -> str:
        """
        Crée et sauvegarde un workflow.
        Retourne l'ID du workflow créé.
        Lève WorkflowValidationError si le format est invalide.
        """
        self._validate(definition)

        wf_id = f"wf_{uuid.uuid4().hex[:8]}"
        workflow = {
            "id":          wf_id,
            "name":        definition["name"],
            "description": definition.get("description", ""),
            "trigger":     definition.get("trigger", "manual"),
            "steps":       definition["steps"],
            "created_at":  time.time(),
            "updated_at":  time.time(),
            "enabled":     definition.get("enabled", True),
            "tags":        definition.get("tags", []),
        }

        self._save(workflow)
        log.info("workflow_created",
                 id=wf_id, name=workflow["name"],
                 steps=len(workflow["steps"]))
        return wf_id

    async def execute(
        self,
        wf_id: str,
        emit: CB | None = None,
        extra_context: str = "",
    ) -> dict:
        """
        Exécute un workflow étape par étape.
        Retourne un rapport d'exécution.

        Format du rapport :
            {
              "workflow_id": "wf_abc123",
              "status":      "completed" | "partial" | "failed",
              "steps_done":  3,
              "steps_total": 3,
              "outputs":     {"agent-name": "résultat…"},
              "duration_s":  12.5,
            }
        """
        _emit = emit or (lambda m: None)
        if callable(_emit) and not asyncio_is_coroutine_function(_emit):
            _emit_real = _emit
            async def _emit(msg: str):  # type: ignore[misc]
                _emit_real(msg)

        t0 = time.monotonic()

        try:
            wf = self._load(wf_id)
        except FileNotFoundError as e:
            await _emit(f"[WorkflowEngine] Erreur : {e}")
            return {"workflow_id": wf_id, "status": "failed", "error": str(e)}

        if not wf.get("enabled", True):
            await _emit(f"[WorkflowEngine] Workflow '{wf['name']}' désactivé.")
            return {"workflow_id": wf_id, "status": "skipped", "reason": "disabled"}

        await _emit(
            f"[WorkflowEngine] Démarrage : {wf['name']} "
            f"({len(wf['steps'])} étape(s))"
        )
        log.info("workflow_start", id=wf_id, name=wf["name"])

        # ── Préparer session factice pour les agents ─────────
        from core.state import JarvisSession
        session = JarvisSession(
            session_id=f"wf_{wf_id[:8]}_{uuid.uuid4().hex[:4]}",
            user_input=wf.get("description") or wf["name"],
        )
        session.mission_summary = wf.get("description") or wf["name"]

        if extra_context:
            session.set_output(
                "workflow-context",
                extra_context, success=True
            )

        # ── Charger AgentCrew ─────────────────────────────────
        from agents.crew import AgentCrew
        crew = AgentCrew(self.s)

        outputs: dict[str, str] = {}
        steps_done = 0

        for i, step in enumerate(wf["steps"], 1):
            agent_name = step.get("agent", "")
            task       = step.get("task", wf.get("description", ""))
            await _emit(f"  Étape {i}/{len(wf['steps'])} : {agent_name} — {task[:80]}")

            # Injecter la tâche dans le plan de session
            session.agents_plan = [{"agent": agent_name, "task": task, "priority": 1}]
            session.mission_summary = task or wf["name"]

            try:
                output = await crew.run(agent_name, session)
                outputs[agent_name] = output[:600] if output else "(aucun résultat)"
                steps_done += 1
                await _emit(f"  ✓ {agent_name} terminé")
            except Exception as e:
                log.error("workflow_step_error",
                          id=wf_id, step=i, agent=agent_name, err=str(e))
                outputs[agent_name] = f"[ERREUR] {str(e)[:200]}"
                await _emit(f"  ✗ {agent_name} échoué : {str(e)[:100]}")
                if step.get("on_error") == "abort":
                    break

        duration = round(time.monotonic() - t0, 2)
        status   = (
            "completed" if steps_done == len(wf["steps"]) else
            "partial"   if steps_done > 0 else
            "failed"
        )

        log.info("workflow_done",
                 id=wf_id, status=status,
                 steps_done=steps_done, duration_s=duration)

        await _emit(
            f"[WorkflowEngine] {wf['name']} — {status.upper()} "
            f"({steps_done}/{len(wf['steps'])} étapes, {duration}s)"
        )

        return {
            "workflow_id": wf_id,
            "name":        wf["name"],
            "status":      status,
            "steps_done":  steps_done,
            "steps_total": len(wf["steps"]),
            "outputs":     outputs,
            "duration_s":  duration,
        }

    def list_workflows(self) -> list[dict]:
        """Retourne tous les workflows sauvegardés (métadonnées seulement)."""
        workflows = []
        for p in sorted(self._dir.glob("wf_*.json")):
            try:
                wf = json.loads(p.read_text("utf-8"))
                workflows.append({
                    "id":          wf.get("id"),
                    "name":        wf.get("name"),
                    "description": wf.get("description", "")[:80],
                    "trigger":     wf.get("trigger", "manual"),
                    "steps":       len(wf.get("steps", [])),
                    "enabled":     wf.get("enabled", True),
                    "created_at":  wf.get("created_at"),
                })
            except Exception as e:
                log.warning("workflow_list_read_error", file=str(p), err=str(e))
        return workflows

    def get(self, wf_id: str) -> dict:
        """Charge un workflow complet par son ID."""
        return self._load(wf_id)

    async def delete(self, wf_id: str) -> bool:
        """Supprime un workflow. Retourne True si supprimé."""
        p = self._path(wf_id)
        if p.exists():
            p.unlink()
            log.info("workflow_deleted", id=wf_id)
            return True
        return False

    async def enable(self, wf_id: str, enabled: bool = True) -> None:
        """Active ou désactive un workflow."""
        wf = self._load(wf_id)
        wf["enabled"] = enabled
        self._save(wf)
        log.info("workflow_toggled", id=wf_id, enabled=enabled)


# ── Helper compat asyncio ─────────────────────────────────────

def asyncio_is_coroutine_function(f) -> bool:
    import asyncio
    import inspect
    return asyncio.iscoroutinefunction(f) or inspect.iscoroutinefunction(f)
