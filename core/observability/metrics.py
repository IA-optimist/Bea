"""
BEA MAX — MetricsCollector
Observabilité légère : collecte et exposition des métriques système.

Persistance :
    workspace/metrics.json — append-only, rotated at 10 000 entries

Métriques collectées :
    runs_per_day            : runs par jour calendaire
    patch_success_rate      : ratio patches approuvés / générés
    agent_latency_ms        : latence par agent (histogramme buckets)
    workflow_failures       : workflows en échec
    llm_call_count          : appels LLM par rôle
    llm_error_count         : erreurs LLM par rôle
    escalation_count        : escalades cloud déclenchées

Interface :
    m = MetricsCollector(settings)
    m.inc("patch_approved")
    m.record_latency("forge-builder", 1520)
    m.record_run(mode="improve", success=True, duration_s=142)
    report = m.get_report()
    snapshot = m.get_snapshot()
"""
from __future__ import annotations

import json
import time
from collections import defaultdict
from datetime import date
from pathlib import Path
import structlog

log = structlog.get_logger()

_MAX_EVENTS = 10_000


class MetricsCollector:
    """
    Collecteur de métriques léger, persistant, sans dépendance externe.
    Thread-safe via append-only + rechargement à la demande.
    """

    def __init__(self, settings):
        self.s        = settings
        self._path    = self._resolve_path()
        self._events: list[dict] = self._load()
        # Compteurs in-memory (réinitialisés au redémarrage)
        self._counters:  dict[str, int]          = defaultdict(int)
        self._latencies: dict[str, list[float]]  = defaultdict(list)

    # ── Persistance ───────────────────────────────────────────

    def _resolve_path(self) -> Path:
        base = Path(getattr(self.s, "workspace_dir", "/app/workspace"))
        base.mkdir(parents=True, exist_ok=True)
        return base / "metrics.json"

    def _load(self) -> list[dict]:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text("utf-8"))
            except Exception:
                return []
        return []

    def _append_event(self, event: dict) -> None:
        """Ajoute un événement et sauvegarde (rotation auto)."""
        event.setdefault("ts", time.time())
        self._events.append(event)
        if len(self._events) > _MAX_EVENTS:
            self._events = self._events[-_MAX_EVENTS:]
        try:
            self._path.write_text(
                json.dumps(self._events, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            log.error("metrics_save_error", err=str(e))

    # ── API publique ──────────────────────────────────────────

    def inc(self, metric: str, value: int = 1, labels: dict | None = None) -> None:
        """Incrémente un compteur nommé."""
        self._counters[metric] += value
        self._append_event({
            "type":   "counter",
            "metric": metric,
            "value":  value,
            "labels": labels or {},
        })

    def record_latency(self, component: str, latency_ms: float) -> None:
        """Enregistre une latence (ms) pour un composant."""
        self._latencies[component].append(latency_ms)
        self._append_event({
            "type":      "latency",
            "component": component,
            "ms":        round(latency_ms, 1),
        })

    def record_run(
        self,
        mode:       str,
        success:    bool,
        duration_s: float = 0.0,
        patches:    int   = 0,
        approved:   int   = 0,
    ) -> None:
        """Enregistre les métriques d'un run complet."""
        self._counters["runs_total"] += 1
        if success:
            self._counters["runs_success"] += 1
        else:
            self._counters["runs_error"] += 1

        today = str(date.today())
        self._counters[f"runs_{today}"] += 1

        self._append_event({
            "type":       "run",
            "mode":       mode,
            "success":    success,
            "duration_s": round(duration_s, 2),
            "patches":    patches,
            "approved":   approved,
        })
        log.debug("metrics_run_recorded",
                  mode=mode, success=success, duration_s=duration_s)

    def record_llm_call(self, role: str, latency_s: float, error: bool = False) -> None:
        """Enregistre un appel LLM."""
        self._counters[f"llm_calls_{role}"] += 1
        if error:
            self._counters[f"llm_errors_{role}"] += 1
        self.record_latency(f"llm_{role}", latency_s * 1000)

    def record_workflow(self, status: str) -> None:
        """Enregistre le statut d'un workflow."""
        self._counters[f"workflow_{status}"] += 1
        self._append_event({"type": "workflow", "status": status})

    def record_escalation(self, provider: str = "") -> None:
        """Enregistre une escalade cloud."""
        self._counters["escalation_total"] += 1
        if provider:
            self._counters[f"escalation_{provider}"] += 1

    # ── Rapport ───────────────────────────────────────────────

    def get_snapshot(self) -> dict:
        """Retourne un snapshot instantané des compteurs in-memory."""
        # Recalculer runs_per_day depuis les events persistés
        runs_by_day: dict[str, int] = defaultdict(int)
        patch_total  = 0
        patch_ok     = 0
        wf_fail      = 0

        for e in self._events:
            if e.get("type") == "run":
                day = str(date.fromtimestamp(e.get("ts", time.time())))
                runs_by_day[day] += 1
                patch_total += e.get("patches",  0)
                patch_ok    += e.get("approved", 0)
            elif e.get("type") == "workflow" and e.get("status") == "failed":
                wf_fail += 1

        patch_rate = round(patch_ok / patch_total, 3) if patch_total > 0 else 0.0

        # Latences moyennes par composant
        lat_avg: dict[str, float] = {}
        for comp, vals in self._latencies.items():
            if vals:
                lat_avg[comp] = round(sum(vals) / len(vals), 1)

        return {
            "runs_total":       self._counters.get("runs_total", 0),
            "runs_success":     self._counters.get("runs_success", 0),
            "runs_error":       self._counters.get("runs_error", 0),
            "runs_per_day":     dict(runs_by_day),
            "patch_success_rate": patch_rate,
            "patch_total":      patch_total,
            "patch_approved":   patch_ok,
            "workflow_failures": wf_fail,
            "agent_latency_avg_ms": lat_avg,
            "escalation_total": self._counters.get("escalation_total", 0),
        }

    def get_report(self) -> str:
        """Rapport texte lisible des métriques actuelles."""
        s = self.get_snapshot()
        lines = [
            "=== Métriques BeaMax ===",
            f"Runs total    : {s['runs_total']}  (succès:{s['runs_success']} erreurs:{s['runs_error']})",
            f"Patch rate    : {round(s['patch_success_rate']*100)}%  ({s['patch_approved']}/{s['patch_total']})",
            f"WF failures   : {s['workflow_failures']}",
            f"Escalations   : {s['escalation_total']}",
        ]
        if s["runs_per_day"]:
            lines.append("Runs/jour     :")
            for day in sorted(s["runs_per_day"])[-7:]:  # 7 derniers jours
                lines.append(f"  {day}: {s['runs_per_day'][day]}")
        if s["agent_latency_avg_ms"]:
            lines.append("Latences moy  :")
            for comp, ms in sorted(s["agent_latency_avg_ms"].items()):
                lines.append(f"  {comp:<25} : {ms}ms")
        return "\n".join(lines)

    def reset_counters(self) -> None:
        """Réinitialise les compteurs in-memory (pas les events persistés)."""
        self._counters.clear()
        self._latencies.clear()

    def clear(self) -> None:
        """Efface tout (pour tests)."""
        self._events = []
        self._counters.clear()
        self._latencies.clear()
        if self._path.exists():
            self._path.unlink()


# ══════════════════════════════════════════════════════════════
# LLM PERFORMANCE MONITOR
# ══════════════════════════════════════════════════════════════

_MAX_LLM_CALLS = 200   # max entrées conservées par rôle


class LLMPerformanceMonitor:
    """
    Surveille les performances LLM par rôle et détecte les dérives.

    Fonctionnalités :
        - Enregistre latence / tokens / erreurs par rôle
        - Détecte drift : latence > 90 s moy, erreur > 30 %, récent 1.5× historique
        - Recommande un modèle alternatif en cas de dérive
        - Persiste dans workspace/llm_perf.json (max 200 entrées par rôle)

    Usage :
        mon = LLMPerformanceMonitor(settings)
        mon.record("forge-builder", latency_ms=4200, tokens=512, error=False, provider="ollama")
        drift = mon.detect_drift("forge-builder")
        report = mon.get_drift_report()
    """

    def __init__(self, settings):
        self.s     = settings
        self._path = self._resolve_path()
        self._data: dict[str, list[dict]] = self._load()

    # ── Persistance ───────────────────────────────────────────

    def _resolve_path(self) -> Path:
        base = Path(getattr(self.s, "workspace_dir", "/app/workspace"))
        base.mkdir(parents=True, exist_ok=True)
        return base / "llm_perf.json"

    def _load(self) -> dict[str, list[dict]]:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text("utf-8"))
            except Exception:
                return {}
        return {}

    def _save(self) -> None:
        try:
            self._path.write_text(
                json.dumps(self._data, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            log.error("llm_perf_save_error", err=str(e))

    # ── API publique ──────────────────────────────────────────

    def record(
        self,
        role:       str,
        latency_ms: float,
        tokens:     int   = 0,
        error:      bool  = False,
        provider:   str   = "",
    ) -> None:
        """Enregistre les métriques d'un appel LLM."""
        if role not in self._data:
            self._data[role] = []
        entry = {
            "ts":         time.time(),
            "latency_ms": round(latency_ms, 1),
            "tokens":     tokens,
            "error":      error,
            "provider":   provider,
        }
        self._data[role].append(entry)
        # Rotation : conserver les N dernières entrées
        if len(self._data[role]) > _MAX_LLM_CALLS:
            self._data[role] = self._data[role][-_MAX_LLM_CALLS:]
        self._save()

    def get_stats(self, role: str, window: int = 20) -> dict:
        """
        Calcule les statistiques pour les `window` derniers appels du rôle.

        Retourne :
            avg_latency_ms, p95_latency_ms, max_latency_ms,
            error_rate, total_tokens, call_count
        """
        calls = self._data.get(role, [])[-window:]
        if not calls:
            return {
                "avg_latency_ms": 0.0, "p95_latency_ms": 0.0,
                "max_latency_ms": 0.0, "error_rate": 0.0,
                "total_tokens": 0, "call_count": 0,
            }
        latencies = sorted(c["latency_ms"] for c in calls)
        errors    = sum(1 for c in calls if c.get("error"))
        p95_idx   = max(0, int(len(latencies) * 0.95) - 1)
        return {
            "avg_latency_ms": round(sum(latencies) / len(latencies), 1),
            "p95_latency_ms": round(latencies[p95_idx], 1),
            "max_latency_ms": round(latencies[-1], 1),
            "error_rate":     round(errors / len(calls), 3),
            "total_tokens":   sum(c.get("tokens", 0) for c in calls),
            "call_count":     len(calls),
        }

    def detect_drift(self, role: str) -> dict:
        """
        Détecte les dérives de performance pour un rôle donné.

        3 conditions de dérive :
            - latency_high   : latence moy récente > 90 000 ms (90 s)
            - error_high     : taux d'erreur récent > 30 %
            - latency_spike  : moy 5 derniers appels > 1.5× moy 20 derniers

        Retourne :
            {"drift": bool, "reasons": [...], "stats": {...}}
        """
        stats_recent   = self.get_stats(role, window=5)
        stats_baseline = self.get_stats(role, window=20)

        reasons: list[str] = []

        if stats_recent["avg_latency_ms"] > 90_000:
            reasons.append(
                f"latence_haute: {stats_recent['avg_latency_ms']}ms moy (seuil 90s)"
            )

        if stats_recent["error_rate"] > 0.30:
            reasons.append(
                f"erreurs_elevees: {round(stats_recent['error_rate']*100)}% (seuil 30%)"
            )

        if (
            stats_baseline["avg_latency_ms"] > 0
            and stats_recent["avg_latency_ms"]
            > stats_baseline["avg_latency_ms"] * 1.5
            and stats_recent["call_count"] >= 3
        ):
            reasons.append(
                f"latence_spike: récent {stats_recent['avg_latency_ms']}ms "
                f"vs baseline {stats_baseline['avg_latency_ms']}ms (×1.5)"
            )

        if reasons:
            log.warning("llm_drift_detected", role=role, reasons=reasons)

        return {
            "drift":   bool(reasons),
            "reasons": reasons,
            "stats":   stats_recent,
        }

    def recommend_model(self, role: str) -> str | None:
        """
        Recommande un modèle alternatif si dérive détectée.

        Logique :
            latence haute  → modèle rapide (fast)
            erreurs hautes → modèle principal (main)
            sinon          → None (pas de changement)
        """
        drift = self.detect_drift(role)
        if not drift["drift"]:
            return None

        reasons = drift["reasons"]
        has_latency = any("latence" in r for r in reasons)
        has_errors  = any("erreur" in r for r in reasons)

        fast_model = getattr(self.s, "ollama_model_fast",
                             getattr(self.s, "openai_model_fast", None))
        main_model = getattr(self.s, "ollama_model_main",
                             getattr(self.s, "openai_model", None))

        if has_latency and not has_errors:
            return fast_model
        if has_errors:
            return main_model
        return fast_model

    def get_drift_report(self) -> str:
        """Rapport texte des dérives détectées sur tous les rôles tracés."""
        if not self._data:
            return "Aucune donnée LLM collectée."
        lines = ["=== LLM Performance Monitor ==="]
        for role in sorted(self._data):
            drift = self.detect_drift(role)
            s     = drift["stats"]
            status = "DRIFT" if drift["drift"] else "OK"
            lines.append(
                f"[{status}] {role:<20} "
                f"avg={s['avg_latency_ms']}ms  "
                f"p95={s['p95_latency_ms']}ms  "
                f"err={round(s['error_rate']*100)}%  "
                f"calls={s['call_count']}"
            )
            for r in drift["reasons"]:
                lines.append(f"       ! {r}")
        return "\n".join(lines)

    def clear(self) -> None:
        """Efface tout (pour tests)."""
        self._data = {}
        if self._path.exists():
            self._path.unlink()
