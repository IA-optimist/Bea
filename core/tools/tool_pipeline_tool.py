"""tool_pipeline_tool — exécute une séquence d'outils en un seul appel (Axe 3).

« Programmatic Tool Calling » côté hôte : au lieu d'un aller-retour d'inférence
par outil, le modèle décrit une liste d'étapes `{tool, params}` exécutées en une
fois. Chaque étape passe par `ToolExecutor.execute` → **toutes les gardes
(policy / capability / approval) restent appliquées**. OPT-IN comme execute_code.

Sécurité : `tool_pipeline` ne peut pas s'appeler lui-même (anti-récursion), et
s'arrête à la première erreur par défaut (`stop_on_error=True`).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_MAX_STEPS = 20
_SELF_NAME = "tool_pipeline"


def _ok(output: str, results: list, risk_level: str = "medium") -> dict:
    return {
        "ok": True, "status": "ok",
        "output": output, "result": output,
        "error": None, "logs": results, "risk_level": risk_level,
    }


def _err(error: str, results: list | None = None, risk_level: str = "medium") -> dict:
    return {
        "ok": False, "status": "error",
        "output": "", "result": "",
        "error": error, "logs": results or [], "risk_level": risk_level,
    }


def _get_executor():
    from core.tool_executor import ToolExecutor
    return ToolExecutor()


def tool_pipeline(
    steps: list,
    approval_mode: str = "SUPERVISED",
    stop_on_error: bool = True,
    mission_id: str = "",
    principal_id: str = "",
) -> dict:
    """Exécute `steps` (liste de `{"tool": str, "params": dict}`) séquentiellement.

    Renvoie le dict outil standard ; `logs` contient le résultat par étape.
    mission_id and principal_id are propagated into each step's params so
    policy session limits are tracked per authenticated identity.
    """
    if not isinstance(steps, list) or not steps:
        return _err("empty_steps")
    if len(steps) > _MAX_STEPS:
        return _err(f"too_many_steps (max {_MAX_STEPS})")

    executor = _get_executor()
    results: list[dict] = []
    for i, step in enumerate(steps):
        if not isinstance(step, dict) or "tool" not in step:
            return _err(f"step {i}: invalid (besoin de 'tool')", results)
        tool = step["tool"]
        params = step.get("params", {}) or {}
        if tool == _SELF_NAME:
            return _err(f"step {i}: récursion interdite ({_SELF_NAME})", results)
        # Propagate mission_id and validated principal so policy engine can
        # track per-session limits per identity. The validated principal always
        # wins over any caller-provided principal field.
        params = dict(params)
        if mission_id:
            params.setdefault("mission_id", mission_id)
        if principal_id:
            params["_bea_principal_id"] = principal_id
            params.pop("principal_id", None)
        try:
            res = executor.execute(tool, params, approval_mode=approval_mode)
        except Exception as e:  # fail-closed par étape
            logger.debug("pipeline_step_failed", exc_info=True)
            res = {"ok": False, "error": str(e)[:200]}
        results.append({"step": i, "tool": tool, "ok": bool(res.get("ok")),
                        "result": str(res.get("result", ""))[:500],
                        "error": res.get("error")})
        if not res.get("ok") and stop_on_error:
            return _err(f"step {i} ({tool}) a échoué: {res.get('error')}", results)

    n_ok = sum(1 for r in results if r["ok"])
    return _ok(f"{n_ok}/{len(results)} étapes réussies", results)
