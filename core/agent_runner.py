"""
AgentRunner — wrapper léger pour lancer des agents avec logs debug structurés.
Mesure la durée d'exécution et log l'état avant/après chaque appel agent.
RAM : <1 KB au repos (singleton stateless).
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

logger = logging.getLogger("jarvis.agent_runner")


def _normalize_agent_output(raw: Any, agent_name: str) -> Any:
    """Normalise n'importe quel retour agent en dict structuré. Fail-open."""
    try:
        if raw is None:
            return {"agent_name": agent_name, "reasoning": "", "result": "", "confidence": 0.0, "status": "error"}
        if isinstance(raw, dict):
            return raw
        if hasattr(raw, "__dict__"):
            return raw.__dict__
        return {"agent_name": agent_name, "reasoning": "", "result": str(raw), "confidence": 0.5, "status": "success"}
    except Exception:
        return raw  # fail-open : retourner l'original en cas d'erreur


def _log_pipeline_event(event: str, agent_name: str = "", reason: str = "", **kwargs):
    """Log structuré pipeline."""
    import logging
    import json
    logger = logging.getLogger("pipeline")
    extra = {"agent": agent_name, "reason": reason, **kwargs}
    logger.info("[PIPELINE] event=%s %s", event, json.dumps(extra, default=str))


class AgentRunner:
    """
    Lance des agents via le registre central avec logs debug [AGENT_RUN] / [AGENT_DONE].
    Fail-open : retourne None si l'agent est introuvable ou lève une exception.
    """

    def run(self, agent_name: str, goal: str, settings=None, **kwargs) -> Optional[Any]:
        """
        Exécute un agent par nom.
        - Loggue [AGENT_RUN] en INFO avant exécution.
        - Loggue [AGENT_DONE] en INFO après avec durée.
        - Retourne le résultat de agent.run() ou dict {ok: False, ...} en cas d'erreur.
        """
        ts = int(time.time())
        logger.info(json.dumps({
            "event": "AGENT_RUN",
            "task": goal[:80] if goal else "",
            "agent": agent_name,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }))

        t0 = time.monotonic()
        result = None
        try:
            from agents.registry import get_agent, AGENT_CLASSES
            if agent_name not in AGENT_CLASSES:
                logger.warning(f"[AGENT_RUN] unknown agent: {agent_name}")
                elapsed = time.monotonic() - t0
                logger.warning(json.dumps({
                    "event": "AGENT_FAIL",
                    "agent": agent_name,
                    "ok": False,
                    "duration": round(elapsed, 2),
                    "error": "unknown agent",
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                }))
                return {"ok": False, "error": "unknown_agent", "agent": agent_name, "duration": elapsed}

            # Instanciation lazy avec settings optionnel
            if settings is None:
                try:
                    from config.settings import get_settings
                    settings = get_settings()
                except Exception:
                    settings = {}

            agent = get_agent(agent_name, settings)
            if agent is None:
                elapsed = time.monotonic() - t0
                logger.warning(json.dumps({
                    "event": "AGENT_FAIL",
                    "agent": agent_name,
                    "ok": False,
                    "duration": round(elapsed, 2),
                    "error": "agent_instantiation_failed",
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                }))
                return {"ok": False, "error": "agent_instantiation_failed", "agent": agent_name, "duration": elapsed}

            result = agent.run(goal, **kwargs)
            result = _normalize_agent_output(result, agent_name)

        except Exception as e:
            elapsed = time.monotonic() - t0
            logger.warning(json.dumps({
                "event": "AGENT_FAIL",
                "agent": agent_name,
                "ok": False,
                "duration": round(elapsed, 2),
                "error": str(e),
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }))
            _log_pipeline_event("agent_failed", agent_name=agent_name, reason=str(e))
            return {"ok": False, "error": str(e), "agent": agent_name, "duration": elapsed}
        finally:
            elapsed = time.monotonic() - t0
            logger.info(json.dumps({
                "event": "AGENT_DONE",
                "agent": agent_name,
                "ok": result is not None,
                "duration": round(elapsed, 2),
                "result_len": len(str(result)) if result is not None else 0,
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }))

        # Stocker en mémoire si succès
        try:
            from core.tools.memory_toolkit import memory_store_solution
            memory_store_solution(
                problem=goal[:200],
                solution=f"agent={agent_name}, duration={elapsed:.2f}s",
                tags=["execution", agent_name, "success"],
            )
        except Exception as e:
            logger.debug("memory_store_skipped: %s", str(e)[:80])  # non-critical

        return result


# ── Singleton ──────────────────────────────────────────────────────────────────

_runner: Optional[AgentRunner] = None


def get_agent_runner() -> AgentRunner:
    """Return the singleton AgentRunner instance. Thread-safe (GIL)."""
    global _runner
    if _runner is None:
        _runner = AgentRunner()
    return _runner
