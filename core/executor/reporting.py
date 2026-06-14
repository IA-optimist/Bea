"""
core.executor.reporting
========================
ReportingMixin: session status computation and final report generation.
Covers: _compute_session_status, _generate_report.
"""
from __future__ import annotations
import asyncio
import structlog

from core.state import BeaSession
from .constants import CB

log = structlog.get_logger()


class ReportingMixin:
    """Mixin providing _compute_session_status and _generate_report."""

    # ── Session status (vérité sur le succès) ─────────────────

    def _compute_session_status(self, session: BeaSession) -> dict:
        """
        Calcule le statut réel de la session : SUCCESS / PARTIAL / FAILURE.

        Règles :
            SUCCESS  : ≥80 % des agents planifiés ont réussi
            PARTIAL  : 20–79 % de succès
            FAILURE  : <20 % de succès OU erreur explicite de session

        Retourne :
            {
              "label":   "SUCCESS" | "PARTIAL" | "FAILURE",
              "badge":   "✅" | "⚠️" | "❌",
              "ok":      int,   # agents réussis
              "total":   int,   # agents planifiés
              "rate":    float, # 0.0 – 1.0
              "failed":  list[str],  # noms des agents échoués
            }
        """
        planned_names = [t.get("agent", "") for t in session.agents_plan if t.get("agent")]
        total = len(planned_names)

        if session.needs_actions and session.actions_executed:
            raw_actions = session._raw_actions or []
            accounted_actions = len(session.actions_executed) + len(session.actions_pending)
            if not raw_actions or accounted_actions >= len(raw_actions):
                return {
                    "label": "SUCCESS",
                    "badge": "✅",
                    "ok": len(session.actions_executed),
                    "total": len(raw_actions) or len(session.actions_executed),
                    "rate": 1.0,
                    "failed": [],
                }

        if total == 0:
            # Aucun plan : statut basé sur la présence d'une erreur session
            if getattr(session, "error", None):
                return {"label": "FAILURE", "badge": "❌", "ok": 0, "total": 0,
                        "rate": 0.0, "failed": []}
            return {"label": "SUCCESS", "badge": "✅", "ok": 0, "total": 0,
                    "rate": 1.0, "failed": []}

        ok    = 0
        failed: list[str] = []
        for name in planned_names:
            out = session.outputs.get(name)
            if out and out.success and out.content:
                ok += 1
            else:
                failed.append(name)

        rate = ok / total

        if getattr(session, "error", None):
            label, badge = "FAILURE", "❌"
        elif rate >= 0.80:
            label, badge = "SUCCESS", "✅"
        elif rate >= 0.20:
            label, badge = "PARTIAL", "⚠️"
        else:
            label, badge = "FAILURE", "❌"

        log.info("session_status_computed",
                 label=label, ok=ok, total=total, rate=round(rate, 2),
                 failed=failed[:5], sid=session.session_id)

        return {
            "label": label, "badge": badge,
            "ok": ok, "total": total,
            "rate": rate, "failed": failed,
        }

    # ── Final report ──────────────────────────────────────────

    async def _generate_report(self, session: BeaSession, emit: CB, session_status: dict | None = None):
        # Import messages uniquement — le LLM est invoqué via safe_invoke
        from langchain_core.messages import SystemMessage, HumanMessage

        # Exclure les agents internes du rapport visible
        exclude = {"vault-memory", "pulse-ops", "observer", "atlas-director"}
        raw_outputs = {
            k: v.content
            for k, v in session.outputs.items()
            if v.success and v.content and k not in exclude
        }

        # Synthèse heuristique des résultats multi-agents
        if len(raw_outputs) > 1:
            try:
                from agents.synthesizer_agent import SynthesizerAgent
                synth  = SynthesizerAgent(self.s)
                synth_result = await synth.synthesize(
                    raw_outputs, session.mission_summary, emit=emit, include_plan=False
                )
                snippets = synth_result.get("merged", "") or "\n\n".join(
                    f"[{k}]:\n{v[:600]}" for k, v in raw_outputs.items()
                )
            except Exception as e:
                log.warning("synthesizer_skipped", err=str(e)[:80])
                snippets = "\n\n".join(
                    f"[{k}]:\n{v[:600]}" for k, v in raw_outputs.items()
                )
        else:
            snippets = "\n\n".join(
                f"[{k}]:\n{v[:600]}" for k, v in raw_outputs.items()
            )

        if not snippets:
            snippets = "(aucun resultat agent)"

        actions_note = ""
        if session.actions_executed:
            actions_note += f"\n{len(session.actions_executed)} action(s) executee(s)"
        if session.actions_pending:
            actions_note += f"\n{len(session.actions_pending)} action(s) en attente de ta validation"

        # ── Statut réel de la session (vérité obligatoire dans le rapport) ──
        # Réutilise le statut précalculé (évite double émission session_status_computed)
        status_info = session_status if session_status is not None else self._compute_session_status(session)
        status_label = status_info["label"]
        status_badge = status_info["badge"]
        status_note  = (
            f"Statut réel : {status_badge} {status_label} "
            f"({status_info['ok']}/{status_info['total']} agents OK)"
        )
        if status_info["failed"]:
            status_note += f"\nAgents en échec : {', '.join(status_info['failed'])}"

        if session.actions_executed:
            targets = [
                str(action.get("target", "")).strip()
                for action in session.actions_executed
                if action.get("target")
            ]
            target_lines = "\n".join(f"- `{target}`" for target in targets)
            session.final_report = (
                "## Résumé\n"
                f"Mission matérialisée avec {len(targets)} livrable(s) créé(s) "
                "par le pipeline d'exécution supervisé.\n\n"
                "## Livrables créés\n"
                f"{target_lines or '- Actions exécutées sans cible fichier déclarée.'}\n\n"
                "## Exécution\n"
                f"- {status_note}\n"
                f"- Actions en attente : {len(session.actions_pending)}\n\n"
                "## Recommandation\n"
                "Contrôler les livrables créés avant toute action externe."
            )
            await emit(f"Rapport final\n\n{session.final_report[:3500]}")
            return

        try:
            from core.llm_factory import LLMFactory
            factory  = LLMFactory(self.s)
            messages = [
                SystemMessage(content=(
                    f"Tu es {self.s.bea_name}, assistant business expert. "
                    "Redige un rapport final professionnel en francais, directement presentable a un client.\n\n"
                    "FORMAT OBLIGATOIRE (Markdown):\n"
                    "## Résumé\n"
                    "(2-3 phrases synthétisant les résultats principaux)\n\n"
                    "## Points clés\n"
                    "- Point 1 concret\n"
                    "- Point 2 concret\n"
                    "- ...\n\n"
                    "## Recommandations\n"
                    "(1-2 actions concrètes et prioritaires)\n\n"
                    "REGLES: "
                    "NE PAS commencer par 1) Statut / 2) Synthese. "
                    "NE PAS mettre de prefixe SUCCESS/FAILED. "
                    "NE PAS lister les resultats bruts des agents. "
                    "Ecrire comme si tu presentais a un dirigeant: concis, factuel, actionnable. "
                    "Max 250 mots."
                )),
                HumanMessage(content=(
                    f"Mission : {session.mission_summary}\n\n"
                    f"{status_note}\n\n"
                    f"Contexte agents (résumé) :\n{snippets[:800]}{actions_note}"
                )),
            ]
            resp = await factory.safe_invoke(messages, role="fast", timeout=60.0)
            report_text = resp.content if resp else snippets[:2000]
            session.final_report = report_text
            await emit(f"Rapport final\n\n{report_text[:3500]}")
        except asyncio.TimeoutError:
            session.final_report = f"{status_badge} **{status_label}** (timeout LLM)\n\n{snippets[:2000]}"
            await emit(f"Rapport (timeout LLM)\n\n{snippets[:2000]}")
