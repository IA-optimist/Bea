"""
JARVIS MAX — SystemState (WorldModel)
Vision en temps réel de la santé du système multi-agents.

Rôle :
    Maintient une image cohérente de l'état global de JarvisMax :
    - Santé de chaque module (agents, LLM, mémoire, outils)
    - Erreurs récentes et tendances
    - Métriques clés (latences, taux de succès, ressources)
    - Disponibilité des services (Ollama, cloud, n8n, Qdrant)

Cela permet à l'orchestrateur de prendre des décisions informées :
    - "L'agent forge-builder est lent → utiliser un modèle plus rapide"
    - "Ollama est indisponible → escalader en cloud"
    - "La mémoire vectorielle est pleine → nettoyer avant de mémoriser"

Usage :
    state = SystemState(settings)

    # Mettre à jour l'état d'un module
    state.update_module("forge-builder", healthy=True, latency_ms=2500)
    state.report_error("vault-memory", "Connection refused", severity="warning")

    # Lire l'état global
    health = state.get_health()
    report = state.get_report()

    # Détecter les problèmes
    issues = state.get_issues()
"""
from __future__ import annotations

import time
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from collections import deque
import structlog

log = structlog.get_logger()

_STATE_FILE    = "system_state.json"
_MAX_ERRORS    = 50    # erreurs récentes conservées
_MAX_METRICS   = 100   # métriques conservées par module
_STALE_AFTER_S = 300   # un module sans mise à jour depuis 5min est "stale"


class ModuleHealth(str, Enum):
    HEALTHY   = "healthy"
    DEGRADED  = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN   = "unknown"
    STALE     = "stale"


class ErrorSeverity(str, Enum):
    DEBUG   = "debug"
    WARNING = "warning"
    ERROR   = "error"
    CRITICAL = "critical"


# ══════════════════════════════════════════════════════════════
# DONNÉES
# ══════════════════════════════════════════════════════════════

@dataclass
class ModuleStatus:
    """État d'un module (agent, service, composant)."""
    name:          str
    health:        ModuleHealth = ModuleHealth.UNKNOWN
    last_update:   float        = 0.0
    last_success:  float        = 0.0
    last_failure:  float        = 0.0
    success_count: int          = 0
    failure_count: int          = 0
    avg_latency_ms: float       = 0.0
    last_latency_ms: float      = 0.0
    last_error:    str          = ""
    metadata:      dict         = field(default_factory=dict)

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        return self.success_count / total if total else 0.0

    @property
    def is_stale(self) -> bool:
        if not self.last_update:
            return True
        return (time.time() - self.last_update) > _STALE_AFTER_S

    def to_dict(self) -> dict:
        return {
            "name":          self.name,
            "health":        self.health.value,
            "last_update":   self.last_update,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "success_rate":  round(self.success_rate, 3),
            "avg_latency_ms": round(self.avg_latency_ms, 0),
            "last_latency_ms": self.last_latency_ms,
            "last_error":    self.last_error[:100] if self.last_error else "",
            "is_stale":      self.is_stale,
        }


@dataclass
class ErrorRecord:
    """Enregistrement d'une erreur système."""
    module:    str
    message:   str
    severity:  ErrorSeverity = ErrorSeverity.ERROR
    ts:        float         = field(default_factory=time.time)
    context:   dict          = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "module":   self.module,
            "message":  self.message[:200],
            "severity": self.severity.value,
            "ts":       self.ts,
            "age_s":    round(time.time() - self.ts, 0),
        }


# ══════════════════════════════════════════════════════════════
# SYSTEM STATE
# ══════════════════════════════════════════════════════════════

class SystemState:
    """
    Vision en temps réel de l'état du système JarvisMax.

    Conçu pour être un singleton partagé entre l'orchestrateur,
    les agents et les outils de monitoring.
    """

    def __init__(self, settings):
        self.s          = settings
        self._modules:  dict[str, ModuleStatus] = {}
        self._errors:   deque[ErrorRecord]      = deque(maxlen=_MAX_ERRORS)
        self._metrics:  dict[str, list[float]]  = {}   # module → liste latences
        self._started   = time.time()
        self._path      = self._resolve_path()

    def _resolve_path(self) -> Path:
        base = Path(getattr(self.s, "workspace_dir", "/app/workspace"))
        base.mkdir(parents=True, exist_ok=True)
        return base / _STATE_FILE

    # ── Mise à jour modules ───────────────────────────────

    def update_module(
        self,
        name:        str,
        healthy:     bool  = True,
        latency_ms:  float = 0.0,
        error:       str   = "",
        metadata:    dict | None = None,
    ) -> ModuleStatus:
        """
        Met à jour l'état d'un module après une opération.

        Calcule automatiquement :
        - la santé (HEALTHY/DEGRADED/UNHEALTHY) selon le taux de succès
        - la latence moyenne glissante
        """
        if name not in self._modules:
            self._modules[name] = ModuleStatus(name=name)

        mod = self._modules[name]
        now = time.time()

        mod.last_update      = now
        mod.last_latency_ms  = latency_ms

        # Mise à jour latence moyenne (rolling average sur 10 dernières)
        if name not in self._metrics:
            self._metrics[name] = []
        self._metrics[name].append(latency_ms)
        if len(self._metrics[name]) > _MAX_METRICS:
            self._metrics[name] = self._metrics[name][-_MAX_METRICS:]
        mod.avg_latency_ms = sum(self._metrics[name]) / len(self._metrics[name])

        if healthy:
            mod.success_count += 1
            mod.last_success  = now
        else:
            mod.failure_count += 1
            mod.last_failure  = now
            mod.last_error    = error[:200] if error else ""

        if metadata:
            mod.metadata.update(metadata)

        # Calculer la santé
        mod.health = self._compute_health(mod)

        return mod

    def report_error(
        self,
        module:   str,
        message:  str,
        severity: str = "error",
        context:  dict | None = None,
    ) -> None:
        """Enregistre une erreur dans la liste des erreurs récentes."""
        try:
            sev = ErrorSeverity(severity)
        except ValueError:
            sev = ErrorSeverity.ERROR

        record = ErrorRecord(
            module   = module,
            message  = message,
            severity = sev,
            context  = context or {},
        )
        self._errors.append(record)

        # Mettre à jour le module associé
        if module in self._modules:
            self._modules[module].last_error = message[:200]

        if sev in (ErrorSeverity.ERROR, ErrorSeverity.CRITICAL):
            log.warning("system_error_recorded", module=module,
                       severity=severity, msg=message[:60])

    def mark_service_available(self, service: str) -> None:
        """Marque un service comme disponible (Ollama, Qdrant, Redis, etc.)."""
        self.update_module(f"service:{service}", healthy=True)

    def mark_service_unavailable(self, service: str, reason: str = "") -> None:
        """Marque un service comme indisponible."""
        self.update_module(f"service:{service}", healthy=False, error=reason)
        self.report_error(f"service:{service}",
                         f"Service indisponible: {reason}", severity="warning")

    # ── Lecture état ──────────────────────────────────────

    def get_module(self, name: str) -> ModuleStatus | None:
        return self._modules.get(name)

    def get_health(self) -> dict[str, str]:
        """
        Retourne la santé de tous les modules.
        Format : {module_name: health_value}
        """
        return {
            name: mod.health.value
            for name, mod in self._modules.items()
        }

    def get_issues(self, severity: str = "error") -> list[dict]:
        """
        Retourne les problèmes actifs (modules unhealthy + erreurs récentes).
        """
        issues: list[dict] = []

        # Modules non-healthy
        for name, mod in self._modules.items():
            if mod.health in (ModuleHealth.UNHEALTHY, ModuleHealth.DEGRADED):
                issues.append({
                    "type":    "module_unhealthy",
                    "module":  name,
                    "health":  mod.health.value,
                    "details": mod.last_error or f"taux_succès={mod.success_rate:.0%}",
                })
            elif mod.is_stale and mod.last_update > 0:
                issues.append({
                    "type":    "module_stale",
                    "module":  name,
                    "details": f"pas de mise à jour depuis {int(time.time()-mod.last_update)}s",
                })

        # Erreurs récentes graves
        try:
            sev_filter = ErrorSeverity(severity)
        except ValueError:
            sev_filter = ErrorSeverity.ERROR

        for err in self._errors:
            if err.severity in (ErrorSeverity.CRITICAL,) or err.severity == sev_filter:
                issues.append({
                    "type":     "recent_error",
                    "module":   err.module,
                    "severity": err.severity.value,
                    "message":  err.message[:100],
                    "age_s":    round(time.time() - err.ts),
                })

        return issues[:20]

    def get_errors(self, n: int = 10, module: str = "") -> list[dict]:
        """Retourne les N erreurs récentes (filtrables par module)."""
        errors = list(self._errors)
        if module:
            errors = [e for e in errors if e.module == module]
        return [e.to_dict() for e in errors[-n:]]

    def get_report(self) -> str:
        """Rapport texte de l'état système."""
        uptime = int(time.time() - self._started)
        lines  = [
            f"=== SystemState (uptime: {uptime}s) ===",
            f"Modules: {len(self._modules)} | Erreurs recentes: {len(self._errors)}",
        ]

        # Trier par santé (unhealthy en premier)
        health_order = {
            ModuleHealth.UNHEALTHY: 0,
            ModuleHealth.DEGRADED:  1,
            ModuleHealth.STALE:     2,
            ModuleHealth.UNKNOWN:   3,
            ModuleHealth.HEALTHY:   4,
        }
        sorted_mods = sorted(
            self._modules.items(),
            key=lambda x: health_order.get(x[1].health, 5),
        )

        for name, mod in sorted_mods[:15]:
            icon = {"healthy": "OK", "degraded": "!", "unhealthy": "X",
                    "unknown": "?", "stale": "~"}.get(mod.health.value, "?")
            lines.append(
                f"  [{icon}] {name:<25} "
                f"sr={mod.success_rate:.0%} "
                f"lat={mod.avg_latency_ms:.0f}ms"
            )

        issues = self.get_issues()
        if issues:
            lines.append(f"\nProblemes detectes ({len(issues)}):")
            for iss in issues[:5]:
                lines.append(f"  - {iss['type']}: {iss.get('module','')} — {iss.get('details','')[:60]}")

        return "\n".join(lines)

    def get_stats(self) -> dict:
        """Statistiques globales du système."""
        total_success = sum(m.success_count for m in self._modules.values())
        total_failure = sum(m.failure_count for m in self._modules.values())
        total         = total_success + total_failure

        healthy   = sum(1 for m in self._modules.values() if m.health == ModuleHealth.HEALTHY)
        unhealthy = sum(1 for m in self._modules.values() if m.health == ModuleHealth.UNHEALTHY)

        return {
            "modules_total":    len(self._modules),
            "modules_healthy":  healthy,
            "modules_unhealthy": unhealthy,
            "total_calls":      total,
            "total_success":    total_success,
            "total_failure":    total_failure,
            "global_success_rate": total_success / total if total else 0.0,
            "recent_errors":    len(self._errors),
            "uptime_s":         round(time.time() - self._started),
        }

    def save_snapshot(self) -> None:
        """Sauvegarde l'état actuel dans workspace/system_state.json."""
        try:
            data = {
                "ts":      time.time(),
                "modules": {n: m.to_dict() for n, m in self._modules.items()},
                "stats":   self.get_stats(),
                "errors":  [e.to_dict() for e in list(self._errors)[-20:]],
            }
            self._path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            log.warning("system_state_save_failed", err=str(e))

    def reset(self):
        """Remet à zéro pour tests."""
        self._modules.clear()
        self._errors.clear()
        self._metrics.clear()

    # ── Helpers ───────────────────────────────────────────

    def _compute_health(self, mod: ModuleStatus) -> ModuleHealth:
        """Calcule la santé selon le taux de succès et la latence."""
        total = mod.success_count + mod.failure_count
        if total == 0:
            return ModuleHealth.UNKNOWN
        if mod.is_stale:
            return ModuleHealth.STALE

        sr = mod.success_rate
        if sr >= 0.90:
            return ModuleHealth.HEALTHY
        if sr >= 0.60:
            return ModuleHealth.DEGRADED
        return ModuleHealth.UNHEALTHY


# ══════════════════════════════════════════════════════════════
# SINGLETON GLOBAL (optionnel)
# ══════════════════════════════════════════════════════════════

_GLOBAL_STATE: SystemState | None = None


def get_system_state(settings=None) -> SystemState | None:
    """
    Retourne l'instance globale de SystemState.
    Crée une nouvelle instance si settings est fourni.
    """
    global _GLOBAL_STATE
    if settings is not None and _GLOBAL_STATE is None:
        _GLOBAL_STATE = SystemState(settings)
    return _GLOBAL_STATE
