"""
BEA MAX — Night Worker Engine
Travaille en cycles autonomes sur une mission longue durée.
Analyse → Planification → Production → Review → Décision → max 5 cycles.
"""
from __future__ import annotations
import asyncio
import json
import structlog
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Awaitable

from core.state import BeaSession, RiskLevel

log = structlog.get_logger()
CB = Callable[[str], Awaitable[None]]

CYCLE_PROMPT = """Tu es le Night Worker de BeaMax, agent autonome multi-cycles.

Dans CE cycle, produis du travail concret et de qualité.

Réponds UNIQUEMENT en JSON :
{
  "analysis": "Évaluation de la situation actuelle (2-3 phrases)",
  "production": "Le livrable complet de ce cycle (aussi détaillé que possible)",
  "review": "Critique de ta propre production",
  "next_steps": "Ce qui reste à faire (vide si terminé)",
  "should_continue": true,
  "progress_percent": 40,
  "files_to_create": [
    {
      "path": "workspace/missions/SESSION_ID/output.md",
      "content": "contenu complet du fichier"
    }
  ]
}

Règle absolue : si cycle == max_cycles, should_continue DOIT être false.
"""


@dataclass
class CycleResult:
    cycle:        int
    analysis:     str
    production:   str
    review:       str
    next_steps:   str
    should_continue: bool
    progress:     int       = 0
    files:        list[str] = field(default_factory=list)
    raw_files:    list[dict] = field(default_factory=list)
    ts:           str        = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class NightWorkerEngine:

    def __init__(self, settings, executor, risk):
        self.s        = settings
        self.executor = executor
        self.risk     = risk

    async def run(self, session: BeaSession, emit: CB):
        max_cycles  = self.s.night_worker_max_cycles
        timeout     = self.s.night_worker_cycle_timeout
        mission_dir = self.s.missions_dir / session.session_id
        mission_dir.mkdir(parents=True, exist_ok=True)

        await emit(
            f"🌙 *Night Worker démarré*\n"
            f"Session : `{session.session_id}`\n"
            f"Mission : _{session.user_input[:100]}_\n"
            f"Max {max_cycles} cycles · timeout {timeout}s/cycle"
        )

        cycles: list[CycleResult] = []

        for i in range(1, max_cycles + 1):
            session.night_cycle = i
            await emit(f"🔄 *Cycle {i}/{max_cycles}*")

            try:
                result = await asyncio.wait_for(
                    self._run_cycle(session, i, max_cycles, mission_dir),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                await emit(f"Cycle {i} timeout apres {timeout}s — on continue si possible.")
                log.warning("night_cycle_timeout", cycle=i, timeout=timeout)
                # Ne pas casser la boucle sur timeout - on peut avoir d autres cycles utiles
                continue
            except Exception as e:
                log.error("night_cycle_error", cycle=i, err=str(e))
                await emit(f"Cycle {i} erreur : {str(e)[:150]}. Tentative suite...")
                continue

            # Auto-créer les fichiers LOW RISK
            created = await self._create_files(result.raw_files, session.session_id)
            result.files = created

            # Sauvegarder le cycle
            (mission_dir / f"cycle_{i:02d}.json").write_text(
                json.dumps({
                    "cycle": i, "ts": result.ts, "progress": result.progress,
                    "analysis": result.analysis, "production": result.production,
                    "review": result.review, "next_steps": result.next_steps,
                    "files": created,
                }, ensure_ascii=False, indent=2), encoding="utf-8",
            )

            cycles.append(result)
            session.night_productions.append(
                f"Cycle {i} ({result.progress}%):\n{result.production[:400]}"
            )

            preview = result.production[:350] + ("…" if len(result.production) > 350 else "")
            status  = "✅ Objectif atteint" if not result.should_continue else "⏭ Suite prévue"
            await emit(
                f"📊 *Cycle {i} — {result.progress}% — {status}*\n\n{preview}"
                + (f"\n\n🟢 {len(created)} fichier(s) créé(s)" if created else "")
            )

            if not result.should_continue:
                break

        # Rapport final
        final = await self._final_report(session.user_input, cycles)
        (mission_dir / "rapport_final.md").write_text(final, encoding="utf-8")
        session.final_report = final

        all_files = [str(f.relative_to(self.s.workspace_dir))
                     for f in mission_dir.rglob("*") if f.is_file()]
        await emit(
            f"🌙 *Night Worker terminé*\n"
            f"Cycles : {len(cycles)}/{max_cycles}\n"
            f"Fichiers : {len(all_files)}\n\n"
            f"📄 *Rapport final :*\n{final[:1200]}"
            + ("…" if len(final) > 1200 else "")
        )

    async def _run_cycle(
        self, session: BeaSession, cycle: int, max_cycles: int, mission_dir: Path
    ) -> CycleResult:
        llm = self.s.get_llm("builder")
        from langchain_core.messages import SystemMessage, HumanMessage

        prev = "\n\n".join(session.night_productions[-2:]) or "(premier cycle)"
        user = (
            f"Mission : {session.user_input}\n\n"
            f"Cycle : {cycle}/{max_cycles}\n"
            f"Productions précédentes :\n{prev}\n\n"
            f"SESSION_ID = {session.session_id}"
            + ("\n\n⚠️ Dernier cycle — should_continue DOIT être false."
               if cycle >= max_cycles else "")
        )

        resp = await llm.ainvoke([
            SystemMessage(content=CYCLE_PROMPT),
            HumanMessage(content=user),
        ])
        raw = resp.content.strip()
        try:
            if raw.startswith("```"):
                raw = raw.split("```")[1].lstrip("json").strip()
            data = json.loads(raw)
        except Exception:
            data = {
                "analysis": "Erreur parsing", "production": raw[:800],
                "review": "N/A", "next_steps": "",
                "should_continue": cycle < max_cycles,
                "progress_percent": int(cycle / max_cycles * 100),
                "files_to_create": [],
            }

        if cycle >= max_cycles:
            data["should_continue"] = False

        r = CycleResult(
            cycle=cycle,
            analysis=data.get("analysis", ""),
            production=data.get("production", ""),
            review=data.get("review", ""),
            next_steps=data.get("next_steps", ""),
            should_continue=data.get("should_continue", False),
            progress=data.get("progress_percent", 0),
        )
        r.raw_files = data.get("files_to_create", [])
        return r

    async def _create_files(self, files: list[dict], session_id: str) -> list[str]:
        from core.state import ActionSpec
        created = []
        for f in files:
            path    = str(f.get("path", "")).replace("SESSION_ID", session_id)
            content = f.get("content", "")
            if not path or not content:
                continue
            report = self.risk.analyze("create_file", target=path, content=content)
            if report.level == RiskLevel.LOW:
                action = ActionSpec(
                    id="nw", action_type="create_file",
                    target=path, content=content,
                )
                result = await self.executor.execute(action, session_id, "night-worker")
                if result.success:
                    created.append(path)
        return created

    async def _final_report(self, mission: str, cycles: list[CycleResult]) -> str:
        llm = self.s.get_llm("director")
        from langchain_core.messages import SystemMessage, HumanMessage

        prod = "\n\n---\n\n".join(
            f"**Cycle {c.cycle} ({c.progress}%)**\n{c.production[:600]}"
            for c in cycles
        )
        resp = await llm.ainvoke([
            SystemMessage(content=(
                "Génère un rapport final consolidé.\n"
                "1) Synthèse exécutive. 2) Livrables. 3) Recommandations."
            )),
            HumanMessage(content=f"Mission : {mission}\n\nCycles :\n{prod}"),
        ])
        return resp.content
