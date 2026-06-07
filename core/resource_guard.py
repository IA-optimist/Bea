"""
BEA MAX — ResourceGuard
Surveillance et contrôle des ressources système pour éviter les crashs.

Causes du crash incident (2026-03-19) :
  - RAM saturée (~98%) par empilement : Claude + agents parallèles + Docker/WSL2 + Ollama
  - WSL2 VM ext4.vhdx corrompu suite à swap excessif
  - Absence de limites mémoire dans ParallelExecutor et orchestrateur
  - Ollama (4-8 GB par modèle) × agents parallèles = OOM

Architecture :
    ResourceGuard (singleton)
    ├── check_before_agent()   → bloque si RAM insuffisante
    ├── acquire_slot()         → sémaphore agents actifs
    ├── release_slot()         → libère le slot
    ├── get_status()           → état courant (SAFE/NORMAL/BUSY/OVERLOADED)
    └── _monitor_loop()        → monitoring continu (thread daemon)

Modes :
    NORMAL  : comportement standard selon BEA_MODE
    SAFE    : forcé si RAM < SAFE_RAM_MB ou agents > MAX_SAFE_AGENTS
    BLOCKED : refus total si RAM < HARD_LIMIT_MB

Seuils (LOCAL) :
    MAX_AGENTS     = 2   agents simultanés max
    SOFT_RAM_MB    = 2048 MB libres → warning + throttle
    SAFE_RAM_MB    = 1024 MB libres → mode SAFE (séquentiel)
    HARD_LIMIT_MB  = 512  MB libres → refus de tâche

Seuils (VPS) :
    MAX_AGENTS     = 5   agents simultanés max
    SOFT_RAM_MB    = 4096 MB libres → warning + throttle
    SAFE_RAM_MB    = 2048 MB libres → mode SAFE
    HARD_LIMIT_MB  = 1024 MB libres → refus de tâche
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import structlog

log = structlog.get_logger()

# ── Tentative import psutil ────────────────────────────────────────────────────
try:
    import psutil
    _PSUTIL_OK = True
except ImportError:
    _PSUTIL_OK = False
    log.warning(
        "psutil_missing",
        hint="pip install psutil pour activer le monitoring mémoire",
    )


class SystemStatus(str, Enum):
    NORMAL     = "NORMAL"      # tout va bien
    SOFT_WARN  = "SOFT_WARN"   # RAM commence à baisser → log
    SAFE       = "SAFE"        # mode SAFE : agents limités, séquentiel
    BLOCKED    = "BLOCKED"     # RAM critique : tâches refusées
    UNKNOWN    = "UNKNOWN"     # psutil absent, monitoring désactivé


@dataclass
class ResourceSnapshot:
    """Instantané des ressources système."""
    ram_total_mb:  int = 0
    ram_used_mb:   int = 0
    ram_avail_mb:  int = 0
    ram_pct:       float = 0.0
    cpu_pct:       float = 0.0
    active_agents: int = 0
    status:        SystemStatus = SystemStatus.UNKNOWN
    timestamp:     float = field(default_factory=time.monotonic)

    def to_dict(self) -> dict:
        return {
            "ram_total_mb":  self.ram_total_mb,
            "ram_used_mb":   self.ram_used_mb,
            "ram_avail_mb":  self.ram_avail_mb,
            "ram_pct":       round(self.ram_pct, 1),
            "cpu_pct":       round(self.cpu_pct, 1),
            "active_agents": self.active_agents,
            "status":        self.status.value,
        }


# ── Profils de ressources par mode ────────────────────────────────────────────

@dataclass(frozen=True)
class ResourceProfile:
    max_agents:     int    # agents simultanés max
    soft_ram_mb:    int    # RAM libre → warning
    safe_ram_mb:    int    # RAM libre → mode SAFE
    hard_limit_mb:  int    # RAM libre → BLOCKED
    monitor_interval_s: float  # intervalle de monitoring

LOCAL_PROFILE = ResourceProfile(
    max_agents=2,
    soft_ram_mb=2048,
    safe_ram_mb=1024,
    hard_limit_mb=512,
    monitor_interval_s=10.0,
)

VPS_PROFILE = ResourceProfile(
    max_agents=5,
    soft_ram_mb=4096,
    safe_ram_mb=2048,
    hard_limit_mb=1024,
    monitor_interval_s=15.0,
)


# ── ResourceGuard ─────────────────────────────────────────────────────────────

_GUARD_INSTANCE: Optional["ResourceGuard"] = None
_GUARD_LOCK = threading.Lock()


def get_resource_guard(settings=None) -> "ResourceGuard":
    """Retourne le singleton ResourceGuard."""
    global _GUARD_INSTANCE
    with _GUARD_LOCK:
        if _GUARD_INSTANCE is None:
            _GUARD_INSTANCE = ResourceGuard(settings)
        return _GUARD_INSTANCE


class ResourceGuard:
    """
    Gardien des ressources système.
    Bloque ou ralentit les agents si la RAM est insuffisante.
    """

    def __init__(self, settings=None):
        self.s       = settings
        self._profile = self._load_profile(settings)
        self._sem    = threading.Semaphore(self._profile.max_agents)
        self._active = 0
        self._lock   = threading.Lock()
        self._status = SystemStatus.UNKNOWN
        self._forced_safe = False  # forcé manuellement via .env BEA_SAFE_MODE
        self._last_snapshot: Optional[ResourceSnapshot] = None

        # Lire BEA_SAFE_MODE
        import os
        if os.environ.get("BEA_SAFE_MODE", "").lower() in ("1", "true", "yes"):
            self._forced_safe = True
            log.warning("resource_guard_safe_mode_forced", reason="BEA_SAFE_MODE=true")

        # Démarrer le thread de monitoring
        self._running = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            name="resource-guard-monitor",
            daemon=True,
        )
        self._monitor_thread.start()

        log.info(
            "resource_guard_started",
            mode=getattr(settings, "bea_mode", "local"),
            max_agents=self._profile.max_agents,
            soft_ram_mb=self._profile.soft_ram_mb,
            safe_ram_mb=self._profile.safe_ram_mb,
            hard_limit_mb=self._profile.hard_limit_mb,
        )

    @staticmethod
    def _load_profile(settings) -> ResourceProfile:
        """
        Charge le profil selon BEA_MODE avec overrides depuis les settings.
        Ordre de priorité : overrides .env > profil du mode (local|vps).
        """
        if settings is None:
            return LOCAL_PROFILE
        mode = getattr(settings, "bea_mode", "local").lower()
        base = VPS_PROFILE if mode == "vps" else LOCAL_PROFILE

        # Appliquer les overrides si définis (valeur > 0)
        max_agents   = getattr(settings, "resource_max_agents", 0) or base.max_agents
        soft_ram_mb  = getattr(settings, "resource_soft_ram_mb", 0) or base.soft_ram_mb
        safe_ram_mb  = getattr(settings, "resource_safe_ram_mb", 0) or base.safe_ram_mb
        hard_limit_mb = getattr(settings, "resource_hard_ram_mb", 0) or base.hard_limit_mb

        if any([
            max_agents != base.max_agents,
            soft_ram_mb != base.soft_ram_mb,
            safe_ram_mb != base.safe_ram_mb,
            hard_limit_mb != base.hard_limit_mb,
        ]):
            # Reconstruire avec les overrides
            return ResourceProfile(
                max_agents=max_agents,
                soft_ram_mb=soft_ram_mb,
                safe_ram_mb=safe_ram_mb,
                hard_limit_mb=hard_limit_mb,
                monitor_interval_s=base.monitor_interval_s,
            )
        return base

    # ── API publique ──────────────────────────────────────────────────────────

    def check_before_agent(self, agent_name: str = "") -> tuple[bool, str]:
        """
        Vérifie si un nouvel agent peut démarrer.
        Retourne (ok, reason).

        Usage :
            ok, reason = guard.check_before_agent("scout-research")
            if not ok:
                log.warning("agent_blocked", reason=reason)
                return "Agent bloqué : ressources insuffisantes"
        """
        snap = self._snapshot()

        # BLOCKED : RAM critique
        if snap.status == SystemStatus.BLOCKED:
            reason = (
                f"RAM critique : {snap.ram_avail_mb}MB libre "
                f"(min {self._profile.hard_limit_mb}MB) — agent '{agent_name}' refusé"
            )
            log.error("agent_blocked_oom", agent=agent_name, ram_avail_mb=snap.ram_avail_mb)
            return False, reason

        # SAFE : vérifie qu'on ne dépasse pas max_agents/2
        if snap.status == SystemStatus.SAFE or self._forced_safe:
            max_safe = max(1, self._profile.max_agents // 2)
            if snap.active_agents >= max_safe:
                reason = (
                    f"Mode SAFE : {snap.active_agents}/{max_safe} agents max "
                    f"({snap.ram_avail_mb}MB RAM libre)"
                )
                log.warning("agent_throttled_safe", agent=agent_name,
                            active=snap.active_agents, max_safe=max_safe)
                return False, reason

        # NORMAL/SOFT_WARN : vérifier la limite globale
        if snap.active_agents >= self._profile.max_agents:
            reason = (
                f"Limite agents atteinte : {snap.active_agents}/{self._profile.max_agents} "
                f"agents actifs — agent '{agent_name}' mis en attente"
            )
            log.warning("agent_limit_reached", agent=agent_name, active=snap.active_agents)
            return False, reason

        return True, "ok"

    def acquire_slot(self, agent_name: str = "", timeout: float = 30.0) -> bool:
        """
        Acquiert un slot d'exécution agent.
        Bloque jusqu'à timeout si tous les slots sont pris.
        Retourne False si timeout ou ressources insuffisantes.
        """
        ok, reason = self.check_before_agent(agent_name)
        if not ok:
            return False

        acquired = self._sem.acquire(timeout=timeout)
        if acquired:
            with self._lock:
                self._active += 1
            log.debug("agent_slot_acquired", agent=agent_name, active=self._active)
        else:
            log.warning("agent_slot_timeout", agent=agent_name, timeout_s=timeout)
        return acquired

    def release_slot(self, agent_name: str = "") -> None:
        """Libère un slot d'exécution agent."""
        self._sem.release()
        with self._lock:
            self._active = max(0, self._active - 1)
        log.debug("agent_slot_released", agent=agent_name, active=self._active)

    def get_status(self) -> ResourceSnapshot:
        """Retourne l'état courant des ressources."""
        return self._snapshot()

    def get_status_dict(self) -> dict:
        return self._snapshot().to_dict()

    def force_safe_mode(self, enabled: bool = True) -> None:
        """Force/désactive le mode SAFE manuellement."""
        self._forced_safe = enabled
        log.warning("resource_guard_safe_mode_changed", enabled=enabled)

    def stop(self) -> None:
        """Arrête le thread de monitoring."""
        self._running = False

    # ── Monitoring interne ────────────────────────────────────────────────────

    def _snapshot(self) -> ResourceSnapshot:
        """Lit l'état système actuel."""
        with self._lock:
            active = self._active

        if not _PSUTIL_OK:
            return ResourceSnapshot(active_agents=active, status=SystemStatus.UNKNOWN)

        try:
            mem  = psutil.virtual_memory()
            cpu  = psutil.cpu_percent(interval=None)
            avail = mem.available // 1024 // 1024  # MB

            if self._forced_safe or avail < self._profile.hard_limit_mb:
                status = SystemStatus.BLOCKED if avail < self._profile.hard_limit_mb else SystemStatus.SAFE
            elif avail < self._profile.safe_ram_mb:
                status = SystemStatus.SAFE
            elif avail < self._profile.soft_ram_mb:
                status = SystemStatus.SOFT_WARN
            else:
                status = SystemStatus.NORMAL

            snap = ResourceSnapshot(
                ram_total_mb=mem.total // 1024 // 1024,
                ram_used_mb=mem.used // 1024 // 1024,
                ram_avail_mb=avail,
                ram_pct=mem.percent,
                cpu_pct=cpu,
                active_agents=active,
                status=status,
            )
            self._status = status
            self._last_snapshot = snap
            return snap

        except Exception as exc:
            log.debug("resource_guard_snapshot_failed", err=str(exc)[:80])
            return ResourceSnapshot(active_agents=active, status=SystemStatus.UNKNOWN)

    def _monitor_loop(self) -> None:
        """Thread daemon : surveille les ressources et log les alertes."""
        interval = self._profile.monitor_interval_s
        prev_status = SystemStatus.UNKNOWN

        while self._running:
            try:
                snap = self._snapshot()

                # Log seulement si changement de statut ou si SAFE/BLOCKED
                if snap.status != prev_status:
                    log.warning(
                        "resource_status_change",
                        prev=prev_status.value,
                        new=snap.status.value,
                        ram_avail_mb=snap.ram_avail_mb,
                        ram_pct=snap.ram_pct,
                        active_agents=snap.active_agents,
                    )
                    prev_status = snap.status

                elif snap.status in (SystemStatus.SAFE, SystemStatus.BLOCKED):
                    log.warning(
                        "resource_pressure",
                        status=snap.status.value,
                        ram_avail_mb=snap.ram_avail_mb,
                        active_agents=snap.active_agents,
                    )

                elif snap.status == SystemStatus.SOFT_WARN:
                    log.info(
                        "resource_soft_warn",
                        ram_avail_mb=snap.ram_avail_mb,
                        ram_pct=snap.ram_pct,
                    )

            except Exception as exc:
                log.debug("resource_monitor_error", err=str(exc)[:80])

            time.sleep(interval)
