"""
BEA MAX — AgentEvaluator
LLM-as-judge pour évaluer la qualité des sorties des agents.

Évalue chaque sortie sur 5 dimensions (score 0–10) :
    1. Pertinence     : la réponse adresse-t-elle la tâche ?
    2. Précision      : les faits sont-ils corrects et vérifiables ?
    3. Complétude     : la réponse couvre-t-elle tous les aspects demandés ?
    4. Actionnabilité : peut-on agir directement sur cette réponse ?
    5. Cohérence      : la réponse est-elle logique et sans contradiction ?

Score composite : moyenne pondérée → 0.0–10.0
Seuil par défaut : 6.0 (en-dessous = demande de révision)

Usage :
    evaluator = AgentEvaluator(settings)

    # Évaluer un seul agent
    result = await evaluator.evaluate(
        agent_name="forge-builder",
        task="Génère un script de backup",
        output="voici le script...",
        session=session,
    )
    print(result.score, result.feedback, result.pass_eval)

    # Évaluer tous les agents d'une session
    report = await evaluator.evaluate_session(session)
    print(report.summary())

Persistance :
    workspace/eval_history.json — max 500 évaluations
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
import structlog
from langchain_core.messages import SystemMessage, HumanMessage

from core.state import BeaSession

log = structlog.get_logger()

_EVAL_FILE   = "eval_history.json"
_MAX_ENTRIES = 500
_PASS_SCORE  = 6.0   # seuil d'acceptation


# ══════════════════════════════════════════════════════════════
# MODÈLES DE DONNÉES
# ══════════════════════════════════════════════════════════════

@dataclass
class EvalDimension:
    name:    str
    score:   float     # 0–10
    comment: str = ""


@dataclass
class EvalResult:
    """Résultat d'évaluation d'une sortie d'agent."""
    agent_name:   str
    task:         str
    output_len:   int
    dimensions:   list[EvalDimension] = field(default_factory=list)
    score:        float = 0.0     # moyenne pondérée 0–10
    feedback:     str   = ""      # résumé lisible
    pass_eval:    bool  = False   # score >= seuil
    ts:           float = field(default_factory=time.time)
    session_id:   str   = ""
    latency_ms:   int   = 0

    @property
    def scores_by_dim(self) -> dict[str, float]:
        return {d.name: d.score for d in self.dimensions}

    def to_dict(self) -> dict:
        return {
            "agent_name":   self.agent_name,
            "task":         self.task[:200],
            "output_len":   self.output_len,
            "score":        round(self.score, 2),
            "pass_eval":    self.pass_eval,
            "feedback":     self.feedback[:300],
            "dimensions":   [asdict(d) for d in self.dimensions],
            "ts":           self.ts,
            "session_id":   self.session_id,
            "latency_ms":   self.latency_ms,
        }


@dataclass
class SessionEvalReport:
    """Rapport d'évaluation d'une session complète."""
    session_id:  str
    results:     list[EvalResult] = field(default_factory=list)
    ts:          float            = field(default_factory=time.time)

    def passed(self) -> list[EvalResult]:
        return [r for r in self.results if r.pass_eval]

    def failed(self) -> list[EvalResult]:
        return [r for r in self.results if not r.pass_eval]

    def avg_score(self) -> float:
        if not self.results:
            return 0.0
        return round(sum(r.score for r in self.results) / len(self.results), 2)

    def summary(self) -> str:
        if not self.results:
            return "Aucune évaluation."
        lines = [
            f"=== Évaluation Session {self.session_id} ===",
            f"Agents évalués : {len(self.results)}",
            f"Score moyen    : {self.avg_score()}/10",
            f"Passé          : {len(self.passed())}  Échoué : {len(self.failed())}",
        ]
        for r in self.results:
            icon = "OK" if r.pass_eval else "!!"
            lines.append(
                f"  [{icon}] {r.agent_name:<20} "
                f"score={r.score:.1f}/10  "
                f"chars={r.output_len}"
            )
            if not r.pass_eval and r.feedback:
                lines.append(f"       Feedback: {r.feedback[:120]}")
        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
# AGENT EVALUATOR
# ══════════════════════════════════════════════════════════════

_SYSTEM_PROMPT = """Tu es AgentEvaluator, juge LLM expert en qualité de réponses IA.
Tu évalues chaque sortie d'agent sur 5 dimensions (score 0–10 chacune).

Dimensions :
1. pertinence    : la réponse adresse directement la tâche demandée
2. precision     : les faits sont exacts, vérifiables, sans hallucination
3. completude    : tous les aspects de la tâche sont couverts
4. actionnabilite: les résultats permettent une action directe et concrète
5. coherence     : la réponse est logique, sans contradiction interne

Sois strict mais juste. Un score < 5 = sortie problématique.
Un score < 3 = sortie inutilisable.

Réponds UNIQUEMENT en JSON strict :
{
  "dimensions": [
    {"name": "pertinence",     "score": 8, "comment": "..."},
    {"name": "precision",      "score": 7, "comment": "..."},
    {"name": "completude",     "score": 6, "comment": "..."},
    {"name": "actionnabilite", "score": 7, "comment": "..."},
    {"name": "coherence",      "score": 9, "comment": "..."}
  ],
  "feedback": "Résumé global en 1-2 phrases",
  "score_composite": 7.4
}"""


class AgentEvaluator:
    """
    LLM-as-judge pour évaluer les sorties des agents BeaMax.

    Usage asynchrone :
        evaluator = AgentEvaluator(settings)
        result    = await evaluator.evaluate("forge-builder", task, output, session)
        report    = await evaluator.evaluate_session(session)
    """

    # Pondérations des dimensions (somme = 1.0)
    _WEIGHTS = {
        "pertinence":     0.30,
        "precision":      0.25,
        "completude":     0.20,
        "actionnabilite": 0.15,
        "coherence":      0.10,
    }

    def __init__(self, settings, pass_score: float = _PASS_SCORE):
        self.s          = settings
        self.pass_score = pass_score
        self._path      = self._resolve_path()
        self._history:  list[dict] = []
        self._loaded    = False

    # ── Persistance ───────────────────────────────────────────

    def _resolve_path(self) -> Path:
        base = Path(getattr(self.s, "workspace_dir", "/app/workspace"))
        base.mkdir(parents=True, exist_ok=True)
        return base / _EVAL_FILE

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            if self._path.exists():
                self._history = json.loads(self._path.read_text("utf-8"))
        except Exception as e:
            log.warning("evaluator_load_error", err=str(e))
            self._history = []

    def _save(self) -> None:
        try:
            if len(self._history) > _MAX_ENTRIES:
                self._history = self._history[-_MAX_ENTRIES:]
            self._path.write_text(
                json.dumps(self._history, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            log.warning("evaluator_save_error", err=str(e))

    # ── API principale ────────────────────────────────────────

    async def evaluate(
        self,
        agent_name:  str,
        task:        str,
        output:      str,
        session:     BeaSession | None = None,
        timeout_s:   int                  = 30,
    ) -> EvalResult:
        """
        Évalue la sortie d'un agent sur 5 dimensions.

        Retourne un EvalResult avec :
            score : 0–10 (pondéré)
            pass_eval : True si score >= seuil (défaut 6.0)
            feedback : commentaire global
        """
        t0 = time.monotonic()

        if not output or not output.strip():
            return EvalResult(
                agent_name=agent_name,
                task=task,
                output_len=0,
                score=0.0,
                feedback="Sortie vide — aucune évaluation possible.",
                pass_eval=False,
                session_id=session.session_id if session else "",
            )

        user_msg = self._build_eval_prompt(agent_name, task, output)

        try:
            llm  = self.s.get_llm("advisor")
            resp = await asyncio.wait_for(
                llm.ainvoke([
                    SystemMessage(content=_SYSTEM_PROMPT),
                    HumanMessage(content=user_msg),
                ]),
                timeout=timeout_s,
            )
            result = self._parse_response(
                resp.content,
                agent_name=agent_name,
                task=task,
                output=output,
                session=session,
                latency_ms=int((time.monotonic() - t0) * 1000),
            )
        except asyncio.TimeoutError:
            log.warning("evaluator_timeout", agent=agent_name)
            result = self._heuristic_eval(agent_name, task, output, session)
        except Exception as e:
            log.error("evaluator_error", agent=agent_name, err=str(e))
            result = self._heuristic_eval(agent_name, task, output, session)

        # Persister
        self._load()
        self._history.append(result.to_dict())
        self._save()

        log.info("agent_evaluated",
                 agent=agent_name,
                 score=result.score,
                 pass_eval=result.pass_eval,
                 ms=result.latency_ms)

        return result

    async def evaluate_session(
        self,
        session:   BeaSession,
        timeout_s: int = 30,
    ) -> SessionEvalReport:
        """
        Évalue toutes les sorties d'agents disponibles dans une session.
        Les évaluations sont faites en parallèle (max 5 concurrent).
        """
        report = SessionEvalReport(session_id=session.session_id)

        # Collecter les sorties disponibles
        outputs = {
            name: out
            for name, out in (session.context or {}).items()
            if out and out.strip()
            and name not in {"final_report", "error"}
        }

        if not outputs:
            return report

        # Trouver la tâche assignée à chaque agent dans le plan
        tasks_by_agent: dict[str, str] = {
            t.get("agent", ""): t.get("task", session.mission_summary)
            for t in (session.agents_plan or [])
        }

        # Évaluation parallèle (par batch de 5 pour ne pas saturer l'API)
        sem = asyncio.Semaphore(5)

        async def _eval_one(name: str, output: str) -> EvalResult:
            async with sem:
                task = tasks_by_agent.get(name, session.mission_summary)
                return await self.evaluate(name, task, output, session, timeout_s)

        coros   = [_eval_one(n, o) for n, o in outputs.items()]
        results = await asyncio.gather(*coros, return_exceptions=True)

        for r in results:
            if isinstance(r, EvalResult):
                report.results.append(r)
            elif isinstance(r, Exception):
                log.warning("session_eval_one_failed", err=str(r))

        return report

    # ── Helpers ───────────────────────────────────────────────

    @staticmethod
    def _build_eval_prompt(agent_name: str, task: str, output: str) -> str:
        out_preview = output[:3000] + ("...[tronqué]" if len(output) > 3000 else "")
        return (
            f"Agent évalué : {agent_name}\n"
            f"Tâche assignée :\n{task[:500]}\n\n"
            f"Sortie de l'agent :\n{out_preview}"
        )

    def _parse_response(
        self,
        raw:         str,
        agent_name:  str,
        task:        str,
        output:      str,
        session:     BeaSession | None,
        latency_ms:  int,
    ) -> EvalResult:
        """Parse la réponse JSON du LLM-judge."""
        try:
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("```")[1].lstrip("json").strip()
            data = json.loads(cleaned)

            dims = [
                EvalDimension(
                    name=d.get("name", "?"),
                    score=float(d.get("score", 5)),
                    comment=d.get("comment", "")[:200],
                )
                for d in data.get("dimensions", [])
            ]

            # Score composite pondéré
            total_weight = 0.0
            weighted_sum = 0.0
            for d in dims:
                w = self._WEIGHTS.get(d.name, 0.20)
                weighted_sum += d.score * w
                total_weight += w

            score = round(weighted_sum / total_weight, 2) if total_weight > 0 else 0.0
            # Utiliser le score composite du LLM si plausible
            llm_score = float(data.get("score_composite", 0))
            if 0 <= llm_score <= 10:
                score = round((score + llm_score) / 2, 2)

            return EvalResult(
                agent_name=agent_name,
                task=task,
                output_len=len(output),
                dimensions=dims,
                score=score,
                feedback=data.get("feedback", "")[:300],
                pass_eval=(score >= self.pass_score),
                session_id=session.session_id if session else "",
                latency_ms=latency_ms,
            )
        except Exception as e:
            log.warning("evaluator_parse_failed", err=str(e))
            return self._heuristic_eval(agent_name, task, output, session, latency_ms)

    def _heuristic_eval(
        self,
        agent_name:  str,
        task:        str,
        output:      str,
        session:     BeaSession | None,
        latency_ms:  int = 0,
    ) -> EvalResult:
        """Évaluation heuristique sans LLM (fallback si timeout/erreur)."""
        score = 5.0  # score neutre par défaut

        # Pénalités heuristiques
        if len(output) < 50:
            score -= 2.0
        elif len(output) < 200:
            score -= 0.5
        if "[ERROR]" in output.upper() or "[ÉCHEC]" in output.upper():
            score -= 2.0
        if "[WEB_UNAVAILABLE]" in output or "[TIMEOUT]" in output:
            score -= 1.0
        if output.strip().startswith("Je ne peux pas"):
            score -= 1.5

        # Bonus heuristiques
        if len(output) > 500:
            score += 0.5
        if "##" in output or "**" in output:
            score += 0.3   # formatage structuré

        score = round(max(0.0, min(10.0, score)), 2)

        return EvalResult(
            agent_name=agent_name,
            task=task,
            output_len=len(output),
            score=score,
            feedback="[Évaluation heuristique — LLM-judge indisponible]",
            pass_eval=(score >= self.pass_score),
            session_id=session.session_id if session else "",
            latency_ms=latency_ms,
        )

    # ── Stats ─────────────────────────────────────────────────

    def get_agent_stats(self, agent_name: str, last_n: int = 50) -> dict:
        """
        Retourne les statistiques d'évaluation d'un agent sur les N derniers runs.
        """
        self._load()
        entries = [e for e in self._history if e["agent_name"] == agent_name][-last_n:]
        if not entries:
            return {"agent": agent_name, "count": 0}

        scores     = [e["score"] for e in entries]
        pass_rate  = sum(1 for e in entries if e["pass_eval"]) / len(entries)
        avg_score  = round(sum(scores) / len(scores), 2)

        return {
            "agent":      agent_name,
            "count":      len(entries),
            "avg_score":  avg_score,
            "pass_rate":  round(pass_rate, 2),
            "min_score":  min(scores),
            "max_score":  max(scores),
        }

    def get_global_report(self) -> str:
        """Rapport texte des statistiques globales."""
        self._load()
        if not self._history:
            return "Aucune évaluation enregistrée."

        # Agréger par agent
        from collections import defaultdict
        by_agent: dict[str, list[float]] = defaultdict(list)
        for e in self._history:
            by_agent[e["agent_name"]].append(e["score"])

        lines = ["=== AgentEvaluator — Rapport Global ==="]
        lines.append(f"Total évaluations : {len(self._history)}")
        for agent, scores in sorted(by_agent.items()):
            avg  = round(sum(scores) / len(scores), 2)
            pass_n = sum(1 for s in scores if s >= self.pass_score)
            lines.append(
                f"  {agent:<22} n={len(scores)}  avg={avg:.1f}/10  "
                f"pass={pass_n}/{len(scores)}"
            )
        return "\n".join(lines)

    def clear(self) -> None:
        """Efface tout (pour tests)."""
        self._history = []
        self._loaded  = True
        self._save()
