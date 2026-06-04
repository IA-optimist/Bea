"""delegate_tool — délègue une sous-tâche à un subagent isolé (Axe 3, Hermes).

Spawn un `DynamicAgent` dédié via `AgentFactory` et renvoie sa sortie texte,
permettant au modèle d'isoler/paralléliser un workstream. OPT-IN comme
`execute_code` : enregistré dans `core.tool_executor` mais sans impact tant que
le modèle ne l'appelle pas.

Le wrapper `_run_coro` exécute la coroutine agent que l'appelant soit synchrone
(asyncio.run) ou déjà dans une boucle (thread dédié) — robuste dans les deux cas.

Limite connue : exécute un vrai agent (appel LLM + contrat `JarvisSession`) — le
comportement de bout en bout doit être validé en environnement complet/tests.
"""
from __future__ import annotations

import asyncio
import logging
import uuid

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 120
_MAX_TIMEOUT = 600
_MAX_OUTPUT = 20_000
_ALLOWED_ROLES = {"default", "director", "research", "builder", "advisor"}


def _ok(output: str, risk_level: str = "medium") -> dict:
    return {
        "ok": True, "status": "ok",
        "output": output, "result": output,
        "error": None, "logs": [], "risk_level": risk_level,
    }


def _err(error: str, risk_level: str = "medium") -> dict:
    return {
        "ok": False, "status": "error",
        "output": "", "result": "",
        "error": error, "logs": [], "risk_level": risk_level,
    }


def _run_coro(coro):
    """Exécute une coroutine que l'appelant ait ou non une boucle asyncio active."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # Une boucle tourne déjà : exécuter dans un thread isolé pour ne pas la bloquer.
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


async def _adelegate(task: str, role: str, timeout: int) -> str:
    from agents.agent_factory import AgentFactory
    from config.settings import get_settings
    from core.state import JarvisSession

    settings = get_settings()
    factory = AgentFactory(settings)
    name = f"delegate-{uuid.uuid4().hex[:8]}"
    agent = factory.create_dynamic(
        name=name, role=role, timeout_s=timeout,
        description="Subagent délégué (one-shot)",
    )
    session = JarvisSession(session_id=name, user_input=task)
    session.metadata["delegated"] = True
    out = await agent.run(session)
    return str(out or "")


def delegate(task: str, role: str = "default", timeout: int = _DEFAULT_TIMEOUT) -> dict:
    """Délègue `task` à un subagent isolé et renvoie sa sortie (dict outil standard).

    `role` ∈ {default, director, research, builder, advisor}. `timeout` borné
    à [1, 600] s. Fail-closed : toute erreur renvoie un dict `error`.
    """
    if not isinstance(task, str) or not task.strip():
        return _err("empty_task")
    if role not in _ALLOWED_ROLES:
        role = "default"
    try:
        timeout = min(max(int(timeout), 1), _MAX_TIMEOUT)
    except (TypeError, ValueError):
        timeout = _DEFAULT_TIMEOUT

    try:
        out = _run_coro(_adelegate(task, role, timeout))
        return _ok(out[:_MAX_OUTPUT])
    except Exception as e:  # fail-closed
        logger.debug("delegate_failed", exc_info=True)
        return _err(str(e)[:300])
