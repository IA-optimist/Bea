"""
JARVIS MAX — MonitoringAgent
Agrège tous les signaux de santé du système en un HealthReport.

Exposé via :
- GET /api/v2/health
- GET /api/v2/diagnostics
- Déclenché périodiquement par HealthChecker
"""
from __future__ import annotations

import time
from typing import Any

import structlog

from core.contracts import ComponentHealth, HealthReport, HealthStatus
from core.state import JarvisSession

log = structlog.get_logger()


class MonitoringAgent:
    """
    Agent de monitoring — pas un LLM agent, mais un collecteur de santé.
    Interroge tous les composants critiques et produit un HealthReport.
    """
    name = "monitoring-agent"

    def __init__(self, settings=None):
        self.s = settings

    async def run(self, session: JarvisSession | None = None) -> HealthReport:
        """Collecte la santé de tous les composants."""
        components: dict[str, ComponentHealth] = {}

        # LLM
        components["llm"] = await self._check_llm()
        # Memory
        components["memory"] = await self._check_memory()
        # Executor
        components["executor"] = await self._check_executor()
        # Task Queue
        components["task_queue"] = await self._check_task_queue()
        # Mission System
        components["missions"] = await self._check_missions()
        # API
        components["api"] = await self._check_api()

        # Status global = pire composant
        statuses = [c.status for c in components.values()]
        if HealthStatus.DOWN in statuses:
            global_status = HealthStatus.DOWN
        elif HealthStatus.DEGRADED in statuses:
            global_status = HealthStatus.DEGRADED
        else:
            global_status = HealthStatus.OK

        report = HealthReport(
            status=global_status,
            components=components,
            checked_at=time.time(),
        )

        log.info(
            "monitoring_agent_check",
            status=global_status,
            components_ok=sum(1 for c in components.values() if c.status == HealthStatus.OK),
            total=len(components),
        )

        if session:
            import json
            session.set_output(
                self.name,
                json.dumps(report.model_dump(), ensure_ascii=False, default=str)[:2000],
                success=True,
            )

        return report

    def health_dict(self) -> dict[str, Any]:
        """Version synchrone simple pour l'API HTTP."""
        import asyncio
        try:
            # get_event_loop() est deprecated en Python 3.10+ hors contexte async.
            # get_running_loop() lève RuntimeError si pas de loop en cours — c'est le signal voulu.
            asyncio.get_running_loop()
            # On est dans un contexte async — retour dict léger pour éviter le deadlock
            return self._sync_health()
        except RuntimeError:
            # Pas de loop en cours — on peut lancer run()
            try:
                report = asyncio.run(self.run())
                return report.model_dump()
            except Exception:
                return self._sync_health()

    def _sync_health(self) -> dict:
        """Health check synchrone léger (sans async)."""
        return {
            "status": "unknown",
            "components": {
                "llm":       {"status": "unknown"},
                "memory":    {"status": "unknown"},
                "executor":  {"status": "unknown"},
                "api":       {"status": "ok"},
            },
            "checked_at": time.time(),
            "note": "sync_fallback",
        }

    # ── Checkers ──────────────────────────────────────────────

    async def _check_llm(self) -> ComponentHealth:
        t0 = time.monotonic()
        try:
            if self.s:
                from core.llm_factory import LLMFactory
                factory = LLMFactory(self.s)
                llm     = factory.get("uncensored")  # health ping: local ollama (tinyllama)
                # Ping léger
                from langchain_core.messages import HumanMessage
                resp = await llm.ainvoke([HumanMessage(content="ping")])
                ms = int((time.monotonic() - t0) * 1000)
                return ComponentHealth(
                    name="llm",
                    status=HealthStatus.OK,
                    latency_ms=ms,
                    metadata={"model": getattr(llm, "model_name", "?")},
                )
        except Exception as e:
            ms = int((time.monotonic() - t0) * 1000)
            log.debug("monitoring_llm_check_failed", err=str(e)[:80])
            return ComponentHealth(
                name="llm",
                status=HealthStatus.DEGRADED,
                latency_ms=ms,
                error=str(e)[:100],
            )

    async def _check_memory(self) -> ComponentHealth:
        try:
            from memory.store import MemoryStore
            store = MemoryStore(self.s)
            items = await store.search("health_check_probe", k=1)
            return ComponentHealth(
                name="memory",
                status=HealthStatus.OK,
                metadata={"backend": "sqlite"},
            )
        except Exception as e:
            return ComponentHealth(
                name="memory",
                status=HealthStatus.DEGRADED,
                error=str(e)[:100],
            )

    async def _check_executor(self) -> ComponentHealth:
        try:
            from core.action_executor import get_executor
            ex = get_executor()
            status = ex.status()
            return ComponentHealth(
                name="executor",
                status=HealthStatus.OK if status.get("running", False) else HealthStatus.DEGRADED,
                metadata=status,
            )
        except Exception as e:
            return ComponentHealth(
                name="executor",
                status=HealthStatus.DEGRADED,
                error=str(e)[:100],
            )

    async def _check_task_queue(self) -> ComponentHealth:
        try:
            from executor.task_queue import get_task_queue
            queue = get_task_queue()
            stats = queue.stats()
            return ComponentHealth(
                name="task_queue",
                status=HealthStatus.OK,
                metadata=stats,
            )
        except Exception as e:
            return ComponentHealth(
                name="task_queue",
                status=HealthStatus.UNKNOWN,
                error=str(e)[:100],
            )

    async def _check_missions(self) -> ComponentHealth:
        try:
            from core.mission_system import get_mission_system
            ms    = get_mission_system()
            stats = ms.stats()
            return ComponentHealth(
                name="missions",
                status=HealthStatus.OK,
                metadata=stats,
            )
        except Exception as e:
            return ComponentHealth(
                name="missions",
                status=HealthStatus.UNKNOWN,
                error=str(e)[:100],
            )

    async def _check_api(self) -> ComponentHealth:
        """Check API — toujours OK si on peut appeler ce code."""
        return ComponentHealth(
            name="api",
            status=HealthStatus.OK,
            latency_ms=0,
        )
