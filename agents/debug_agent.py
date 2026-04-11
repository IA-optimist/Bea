"""
JARVIS MAX — DebugAgent
Analyse les erreurs agents et propose des corrections ciblées.

Déclenché automatiquement par l'orchestrateur quand :
- Un agent échoue 2+ fois consécutives
- Le RetryEngine est épuisé
- L'orchestrateur reçoit un ErrorReport

Sortie :
    AgentResult avec metadata:
        fix_proposal : str         — patch recommandé ou action à prendre
        root_cause   : str         — classification de la cause
        confidence   : float       — 0.0-1.0
        is_auto_fixable : bool     — si True, RecoveryAgent peut appliquer
"""
from __future__ import annotations

import json
import time

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from agents.crew import BaseAgent
from core.contracts import (
    AgentResult, ErrorReport, RootCauseType
)
from core.state import JarvisSession

log = structlog.get_logger()


class DebugAgent(BaseAgent):
    name     = "debug-agent"
    role     = "builder"   # LLM puissant requis pour l'analyse
    timeout_s= 90

    _SYSTEM = """Tu es DebugAgent, expert en analyse de pannes pour JarvisMax.

MISSION : Analyser les erreurs et proposer des corrections précises.

PROCESSUS OBLIGATOIRE :
1. Identifier le root_cause parmi : timeout | llm_error | parse_error | security | configuration | logic | network | unknown
2. Analyser le contexte de l'erreur (agent, tâche, message)
3. Proposer une fix_proposal concrète et actionnable
4. Évaluer si la correction peut être appliquée automatiquement

FORMAT DE RÉPONSE (JSON strict) :
{
  "root_cause": "timeout",
  "confidence": 0.85,
  "analysis": "L'agent scout-research dépasse le timeout de 120s car la requête LLM est trop volumineuse.",
  "fix_proposal": "Réduire le timeout_s à 90s et tronquer le contexte à 500 chars max.",
  "is_auto_fixable": false,
  "auto_fix_action": null,
  "preventive_measures": ["Ajouter un cache pour les requêtes répétitives", "Fragmente les grandes missions"]
}

RÈGLES :
- is_auto_fixable=true uniquement pour des actions sûres (retry, réduction de timeout, skip agent)
- Sois précis sur la cause — "timeout" != "overload" != "logic error"
- Si insuffisamment d'informations : root_cause="unknown", confidence=0.2
"""

    def system_prompt(self) -> str:
        return self._SYSTEM

    def user_message(self, session: JarvisSession) -> str:
        # Récupère l'ErrorReport depuis session.metadata si disponible
        error_report: dict = session.metadata.get("debug_target_error", {})
        failed_agent = error_report.get("agent", "inconnu")
        error_type   = error_report.get("error_type", "?")
        error_msg    = error_report.get("message", "")
        traceback    = error_report.get("traceback", "")[:800]
        retry_count  = error_report.get("retry_count", 0)
        task_desc    = error_report.get("context", {}).get("task", session.mission_summary or "")

        return (
            f"Agent en échec : {failed_agent}\n"
            f"Tâche : {task_desc}\n"
            f"Erreur : {error_type}: {error_msg}\n"
            f"Tentatives : {retry_count}\n"
            + (f"\nTraceback :\n```\n{traceback}\n```" if traceback else "")
            + f"\n\nMission globale : {session.mission_summary or session.user_input}"
        )

    async def run(self, session: JarvisSession) -> str:
        t0  = time.monotonic()
        log.info("debug_agent_start",
                 sid=session.session_id,
                 target=session.metadata.get("debug_target_error", {}).get("agent", "?"))

        try:
            from core.llm_factory import LLMFactory
            factory  = LLMFactory(self.s)
            messages = [
                SystemMessage(content=self.system_prompt()),
                HumanMessage(content=self.user_message(session)),
            ]
            resp = await factory.safe_invoke(messages, role=self.role, timeout=float(self.timeout_s))
            raw  = (resp.content if resp else "").strip()

            # Parse JSON
            try:
                if raw.startswith("```"):
                    raw = raw.split("```")[1].lstrip("json").strip()
                data = json.loads(raw)
            except Exception:
                data = {
                    "root_cause": "unknown",
                    "confidence": 0.2,
                    "analysis":   raw[:500],
                    "fix_proposal": "Analyse non concluante — vérification manuelle requise",
                    "is_auto_fixable": False,
                    "auto_fix_action": None,
                    "preventive_measures": [],
                }

            ms = int((time.monotonic() - t0) * 1000)

            # Stocker dans les metadata pour RecoveryAgent
            session.metadata["debug_result"]        = data
            session.metadata["debug_root_cause"]    = data.get("root_cause", "unknown")
            session.metadata["debug_auto_fixable"]  = data.get("is_auto_fixable", False)

            summary = (
                f"[DebugAgent] root_cause={data.get('root_cause')} "
                f"confidence={data.get('confidence', 0):.0%} "
                f"auto_fixable={data.get('is_auto_fixable', False)}"
            )
            session.set_output(self.name, summary, success=True, ms=ms)

            log.info(
                "debug_agent_done",
                root_cause=data.get("root_cause"),
                confidence=data.get("confidence"),
                auto_fixable=data.get("is_auto_fixable"),
                ms=ms,
                sid=session.session_id,
            )
            return summary

        except Exception as e:
            ms = int((time.monotonic() - t0) * 1000)
            log.error("debug_agent_error", err=str(e)[:100], sid=session.session_id)
            session.set_output(self.name, "", success=False, error=str(e))
            return ""

    @classmethod
    def from_error_report(cls, report: ErrorReport, session: JarvisSession) -> None:
        """Injecte un ErrorReport dans les metadata de session pour l'analyse."""
        session.metadata["debug_target_error"] = {
            "agent":       report.agent,
            "task_id":     report.task_id,
            "error_type":  report.error_type,
            "message":     report.message,
            "traceback":   report.traceback,
            "retry_count": report.retry_count,
            "context":     report.context,
        }


# ── DebugMonitor ─────────────────────────────────────────────────────────────
# Monitoring statique basé sur workspace/execution_trace.jsonl.
# Pas de LLM — utilisé par l'API monitoring.

from pathlib import Path as _Path  # noqa: E402

_TRACE_LOG = _Path("workspace/execution_trace.jsonl")


class DebugMonitor:
    """Analyse des missions et détection d'anomalies depuis les traces JSONL."""

    def analyze_mission(self, mission_id: str) -> dict:
        """Analyse une mission et retourne un debug_report structuré."""
        traces = self._load_traces(mission_id=mission_id)

        timeout_count  = sum(1 for t in traces if t.get("status") == "TIMEOUT")
        failed_count   = sum(1 for t in traces if t.get("status") == "FAILED")
        retry_count    = sum(1 for t in traces if t.get("retry_count", 0) > 0)
        fallback_count = sum(1 for t in traces if t.get("status") == "FALLBACK")
        empty_outputs  = [
            t for t in traces
            if len((t.get("output_summary") or "")) < 10 and t.get("status") == "SUCCESS"
        ]

        issues: list[dict] = []
        if timeout_count:
            issues.append({"type": "TIMEOUT", "count": timeout_count,
                           "message": f"{timeout_count} agent(s) ont expiré"})
        if failed_count:
            issues.append({"type": "FAILED", "count": failed_count,
                           "message": f"{failed_count} agent(s) ont échoué"})
        if retry_count:
            issues.append({"type": "RETRY", "count": retry_count,
                           "message": f"{retry_count} agent(s) ont nécessité un retry"})
        if fallback_count:
            issues.append({"type": "FALLBACK", "count": fallback_count,
                           "message": f"{fallback_count} agent(s) en fallback"})
        if empty_outputs:
            issues.append({"type": "EMPTY_OUTPUT", "count": len(empty_outputs),
                           "agents": [t.get("agent") for t in empty_outputs],
                           "message": "Outputs vides malgré statut SUCCESS"})

        severity = "LOW"
        if timeout_count + failed_count >= 3:
            severity = "HIGH"
        elif timeout_count + failed_count + retry_count >= 1:
            severity = "MEDIUM"

        recommendations: list[str] = []
        if timeout_count:
            recommendations.append("Augmenter agent_timeout ou optimiser le modèle LLM")
        if failed_count:
            recommendations.append("Vérifier les logs agents et la disponibilité Ollama")
        if retry_count or empty_outputs:
            recommendations.append("Vérifier que le prompt agent retourne bien du contenu")

        return {
            "mission_id": mission_id,
            "traces_found": len(traces),
            "issues": issues,
            "severity": severity,
            "recommendations": recommendations,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    def detect_api_errors(self) -> list[dict]:
        """Retourne les erreurs d'agents des 60 dernières minutes."""
        cutoff = time.time() - 3600
        errors: list[dict] = []
        for trace in self._load_traces():
            if trace.get("ts", 0) < cutoff:
                continue
            if trace.get("status") in {"FAILED", "TIMEOUT", "FALLBACK"}:
                errors.append({
                    "mission_id": trace.get("mission_id"),
                    "agent":      trace.get("agent"),
                    "status":     trace.get("status"),
                    "error":      trace.get("error"),
                    "latency_ms": trace.get("latency_ms"),
                    "ts":         trace.get("ts"),
                })
        return errors

    def generate_debug_report(self) -> dict:
        """Rapport global système (fenêtre 1h glissante)."""
        all_traces = self._load_traces()
        cutoff     = time.time() - 3600
        recent     = [t for t in all_traces if t.get("ts", 0) >= cutoff]

        total    = len(recent)
        failed   = sum(1 for t in recent if t.get("status") not in {"SUCCESS", "RETRIED"})
        retried  = sum(1 for t in recent if t.get("retry_count", 0) > 0)
        timeouts = sum(1 for t in recent if t.get("status") == "TIMEOUT")
        lats     = [t.get("latency_ms", 0) for t in recent if t.get("latency_ms")]
        avg_lat  = int(sum(lats) / len(lats)) if lats else 0

        agent_errs: dict[str, dict] = {}
        for t in recent:
            n = t.get("agent", "unknown")
            agent_errs.setdefault(n, {"total": 0, "failed": 0})
            agent_errs[n]["total"] += 1
            if t.get("status") not in {"SUCCESS", "RETRIED"}:
                agent_errs[n]["failed"] += 1

        return {
            "window":            "last_1h",
            "total_executions":  total,
            "error_rate":        round(failed / max(1, total), 3),
            "retry_rate":        round(retried / max(1, total), 3),
            "timeout_count":     timeouts,
            "avg_latency_ms":    avg_lat,
            "agent_error_rates": {
                n: round(v["failed"] / max(1, v["total"]), 3)
                for n, v in agent_errs.items()
            },
            "recent_errors":     self.detect_api_errors()[:10],
            "generated_at":      time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    def _load_traces(self, mission_id: str | None = None) -> list[dict]:
        if not _TRACE_LOG.exists():
            return []
        traces: list[dict] = []
        try:
            for line in _TRACE_LOG.read_text("utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    if mission_id and record.get("mission_id") != mission_id:
                        continue
                    traces.append(record)
                except Exception:
                    _silent_log.debug("suppressed_exception", src='debug_agent.py')
        except Exception:
            _silent_log.debug("suppressed_exception", src='debug_agent.py')
        return traces
