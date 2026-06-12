"""
BEA MAX — LearningEngine
Analyse les runs passés pour optimiser les stratégies futures.

Données persistées (JSON) :
    workspace/learning_runs.json

Structure d'un run :
    {
        "run_id":          "run_abc123",
        "timestamp":       1710000000.0,
        "mode":            "improve",        # improve / auto / workflow / chat
        "files_scanned":   40,
        "findings":        30,
        "patches_generated": 4,
        "patches_approved":  3,
        "patches_applied":   3,
        "duration_s":        142.5,
        "agents_used":       ["scout-research", "forge-builder"],
        "agents_success":    {"scout-research": True, "forge-builder": False},
        "llm_calls":         {"improve": 2, "builder": 1},
        "llm_latencies":     {"improve": 105.2, "builder": 141.0},
        "workflow_id":       null,
        "workflow_status":   null,
        "escalated":         false,
        "error":             null,
    }

Interface :
    engine = LearningEngine(settings)
    engine.record_run(run_data)
    rates  = engine.compute_success_rates()
    strat  = engine.recommend_strategy()
    report = engine.generate_report()
"""
from __future__ import annotations

import json
import time
import uuid
from collections import defaultdict
from pathlib import Path
import structlog

log = structlog.get_logger()

_MAX_RUNS = 500    # max entrées persistées (FIFO)


class LearningEngine:
    """
    Moteur d'apprentissage basé sur l'historique des runs.
    Zéro dépendance LLM — tout est calculé localement.
    """

    def __init__(self, settings):
        self.s     = settings
        self._path = self._resolve_path()
        self._runs: list[dict] = self._load()

    # ── Persistance ───────────────────────────────────────────

    def _resolve_path(self) -> Path:
        base = Path(getattr(self.s, "workspace_dir", "/app/workspace"))
        base.mkdir(parents=True, exist_ok=True)
        return base / "learning_runs.json"

    def _load(self) -> list[dict]:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text("utf-8"))
            except Exception as e:
                log.warning("learning_load_error", err=str(e))
        return []

    def _save(self) -> None:
        # Garder les MAX_RUNS plus récents
        if len(self._runs) > _MAX_RUNS:
            self._runs = self._runs[-_MAX_RUNS:]
        try:
            self._path.write_text(
                json.dumps(self._runs, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            log.error("learning_save_error", err=str(e))

    # ── API publique ──────────────────────────────────────────

    def record_run(self, run_data: dict) -> str:
        """
        Enregistre un run dans l'historique.
        Injecte run_id et timestamp si absents.
        Retourne le run_id.
        """
        if "run_id" not in run_data:
            run_data = dict(run_data)
            run_data["run_id"]    = f"run_{uuid.uuid4().hex[:8]}"
        if "timestamp" not in run_data:
            run_data["timestamp"] = time.time()

        self._runs.append(run_data)
        self._save()
        log.info("learning_run_recorded",
                 run_id=run_data["run_id"], mode=run_data.get("mode", "?"))
        return run_data["run_id"]

    def compute_success_rates(self) -> dict:
        """
        Calcule les taux de succès par catégorie :
        - global patch success rate
        - par agent
        - par mode (improve / auto / workflow)
        - latence LLM moyenne par rôle
        """
        if not self._runs:
            return {"total_runs": 0}

        total_runs       = len(self._runs)
        patch_generated  = sum(r.get("patches_generated", 0) for r in self._runs)
        patch_approved   = sum(r.get("patches_approved",  0) for r in self._runs)
        patch_applied    = sum(r.get("patches_applied",   0) for r in self._runs)

        # Taux patch
        patch_approval_rate = (
            round(patch_approved / patch_generated, 3)
            if patch_generated > 0 else 0.0
        )
        patch_apply_rate = (
            round(patch_applied / patch_approved, 3)
            if patch_approved > 0 else 0.0
        )

        # Succès par agent
        agent_ok:    dict[str, int] = defaultdict(int)
        agent_total: dict[str, int] = defaultdict(int)
        for r in self._runs:
            for agent, success in r.get("agents_success", {}).items():
                agent_total[agent] += 1
                if success:
                    agent_ok[agent] += 1

        agent_rates = {
            a: round(agent_ok[a] / agent_total[a], 3)
            for a in agent_total
        }

        # Succès par mode
        mode_ok:    dict[str, int] = defaultdict(int)
        mode_total: dict[str, int] = defaultdict(int)
        for r in self._runs:
            mode = r.get("mode", "unknown")
            mode_total[mode] += 1
            if not r.get("error"):
                mode_ok[mode] += 1

        mode_rates = {
            m: round(mode_ok[m] / mode_total[m], 3)
            for m in mode_total
        }

        # Latence LLM moyenne
        llm_lat_sum:   dict[str, float] = defaultdict(float)
        llm_lat_count: dict[str, int]   = defaultdict(int)
        for r in self._runs:
            for role, lat in r.get("llm_latencies", {}).items():
                llm_lat_sum[role]   += lat
                llm_lat_count[role] += 1

        llm_avg_latency = {
            role: round(llm_lat_sum[role] / llm_lat_count[role], 1)
            for role in llm_lat_count
        }

        # Durée moyenne par mode
        dur_sum:   dict[str, float] = defaultdict(float)
        dur_count: dict[str, int]   = defaultdict(int)
        for r in self._runs:
            mode = r.get("mode", "unknown")
            if "duration_s" in r:
                dur_sum[mode]   += r["duration_s"]
                dur_count[mode] += 1

        avg_duration = {
            m: round(dur_sum[m] / dur_count[m], 1)
            for m in dur_count
        }

        return {
            "total_runs":          total_runs,
            "patch_generated":     patch_generated,
            "patch_approved":      patch_approved,
            "patch_applied":       patch_applied,
            "patch_approval_rate": patch_approval_rate,
            "patch_apply_rate":    patch_apply_rate,
            "agent_success_rates": agent_rates,
            "mode_success_rates":  mode_rates,
            "llm_avg_latency_s":   llm_avg_latency,
            "avg_duration_s":      avg_duration,
        }

    def recommend_strategy(self) -> dict:
        """
        Retourne des recommandations d'optimisation basées sur l'historique.

        Format :
            {
                "preferred_model":   "llama3.1:8b",
                "slow_roles":        ["builder"],
                "weak_agents":       ["forge-builder"],
                "suggest_escalate":  False,
                "notes":             ["..."],
            }
        """
        rates = self.compute_success_rates()
        notes: list[str] = []
        slow_roles:  list[str] = []
        weak_agents: list[str] = []

        if rates.get("total_runs", 0) < 3:
            return {
                "preferred_model":  None,
                "slow_roles":       [],
                "weak_agents":      [],
                "suggest_escalate": False,
                "notes": ["Pas assez de runs pour générer des recommandations (min 3)."],
            }

        # Rôles LLM lents (> 120s en moyenne)
        for role, lat in rates.get("llm_avg_latency_s", {}).items():
            if lat > 120:
                slow_roles.append(role)
                notes.append(f"Rôle '{role}' lent ({lat}s moy.) — envisager modèle plus rapide.")

        # Agents à faible succès (< 60%)
        for agent, rate in rates.get("agent_success_rates", {}).items():
            if rate < 0.6:
                weak_agents.append(agent)
                notes.append(f"Agent '{agent}' en échec ({round(rate*100)}%) — vérifier la configuration.")

        # Taux d'approbation patches faible
        apr = rates.get("patch_approval_rate", 1.0)
        if apr < 0.5:
            notes.append(
                f"Taux d'approbation patches bas ({round(apr*100)}%) — "
                "les prompts du builder peuvent être améliorés."
            )

        # Suggestion d'escalade (uniquement si échecs persistants > 50%)
        mode_rates = rates.get("mode_success_rates", {})
        improve_rate = mode_rates.get("improve", 1.0)
        suggest_escalate = improve_rate < 0.5 and rates["total_runs"] >= 5

        if suggest_escalate:
            notes.append(
                "Taux de succès 'improve' < 50% sur ≥5 runs — "
                "l'escalade cloud pourrait être bénéfique."
            )

        if not notes:
            notes.append("Performances nominales — aucun ajustement requis.")

        return {
            "preferred_model":  None,   # déterminé par ModelSelector
            "slow_roles":       slow_roles,
            "weak_agents":      weak_agents,
            "suggest_escalate": suggest_escalate,
            "notes":            notes,
        }

    def generate_report(self, last_n: int = 10) -> str:
        """
        Génère un rapport texte lisible des N derniers runs.
        """
        if not self._runs:
            return "Aucun run enregistré."

        recent = self._runs[-last_n:]
        rates  = self.compute_success_rates()
        strat  = self.recommend_strategy()

        lines = [
            f"=== LearningEngine — {len(self._runs)} runs total ===",
            f"Taux d'approbation patches : {round(rates.get('patch_approval_rate', 0)*100)}%",
            f"Patches appliqués          : {rates.get('patch_applied', 0)} / {rates.get('patch_generated', 0)}",
            "",
            "--- Derniers runs ---",
        ]
        for r in reversed(recent):
            r.get("timestamp", 0)
            mode = r.get("mode", "?")
            err  = " [ERR]" if r.get("error") else ""
            dur  = f"{r.get('duration_s', 0):.0f}s"
            pa   = r.get("patches_approved", 0)
            lines.append(
                f"  {mode:<10} {dur:>6}  patches:{pa}{err}  id={r.get('run_id','?')}"
            )

        if strat["notes"]:
            lines.append("")
            lines.append("--- Recommandations ---")
            for note in strat["notes"]:
                lines.append(f"  • {note}")

        return "\n".join(lines)

    def get_recent_runs(self, n: int = 20) -> list[dict]:
        """Retourne les N runs les plus récents."""
        return list(self._runs[-n:])

    def clear(self) -> None:
        """Efface l'historique (pour tests)."""
        self._runs = []
        if self._path.exists():
            self._path.unlink()
