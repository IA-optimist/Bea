"""
Tests — ResourceGuard
Vérifie les limites, statuts et slots d'exécution.
"""
from __future__ import annotations
import threading

from core.resource_guard import (
    ResourceGuard,
    ResourceProfile,
    ResourceSnapshot,
    SystemStatus,
    LOCAL_PROFILE,
    VPS_PROFILE,
    get_resource_guard,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

class _MockSettings:
    workspace_dir = "/tmp"
    jarvis_mode   = "local"
    jarvis_safe_mode = False


def _make_guard(max_agents: int = 3) -> ResourceGuard:
    """Garde avec profil personnalisé et psutil désactivé."""
    import core.resource_guard as rg
    # Patcher psutil pour les tests déterministes
    rg._PSUTIL_OK = False
    s = _MockSettings()
    guard = ResourceGuard.__new__(ResourceGuard)
    guard.s            = s
    guard._profile     = ResourceProfile(
        max_agents=max_agents,
        soft_ram_mb=2048,
        safe_ram_mb=1024,
        hard_limit_mb=512,
        monitor_interval_s=999.0,  # désactiver le monitor
    )
    guard._sem         = threading.Semaphore(max_agents)
    guard._active      = 0
    guard._lock        = threading.Lock()
    guard._status      = SystemStatus.UNKNOWN
    guard._forced_safe = False
    guard._last_snapshot = None
    guard._running     = False  # ne pas démarrer le thread monitor
    return guard


# ── Profils ───────────────────────────────────────────────────────────────────

def test_local_profile_limits():
    assert LOCAL_PROFILE.max_agents == 2
    assert LOCAL_PROFILE.hard_limit_mb == 512
    assert LOCAL_PROFILE.safe_ram_mb == 1024


def test_vps_profile_limits():
    assert VPS_PROFILE.max_agents == 5
    assert VPS_PROFILE.hard_limit_mb == 1024
    assert VPS_PROFILE.safe_ram_mb == 2048


# ── Slots ────────────────────────────────────────────────────────────────────

def test_acquire_and_release():
    guard = _make_guard(max_agents=2)
    assert guard.acquire_slot("agent-a") is True
    assert guard._active == 1
    guard.release_slot("agent-a")
    assert guard._active == 0


def test_max_slots_respected():
    guard = _make_guard(max_agents=2)
    assert guard.acquire_slot("a1") is True
    assert guard.acquire_slot("a2") is True
    # Le 3e doit échouer (timeout=0 pour tester sans attendre)
    guard._sem = threading.Semaphore(0)  # simuler slots épuisés
    acquired = guard._sem.acquire(timeout=0.01)
    assert acquired is False


def test_release_decrements_active():
    guard = _make_guard(max_agents=3)
    guard.acquire_slot("a1")
    guard.acquire_slot("a2")
    assert guard._active == 2
    guard.release_slot("a1")
    assert guard._active == 1
    guard.release_slot("a2")
    assert guard._active == 0


def test_release_cannot_go_negative():
    guard = _make_guard(max_agents=2)
    guard.release_slot("phantom")  # ne doit pas lever d'exception
    assert guard._active == 0


# ── check_before_agent ────────────────────────────────────────────────────────

def test_check_ok_when_no_psutil():
    """Sans psutil → UNKNOWN → check passe (failsafe)."""
    guard = _make_guard(max_agents=3)
    ok, reason = guard.check_before_agent("test-agent")
    assert ok is True


def test_check_blocked_when_limit_reached():
    guard = _make_guard(max_agents=2)
    with guard._lock:
        guard._active = 2
    ok, reason = guard.check_before_agent("overflow-agent")
    assert ok is False
    assert "Limite agents" in reason


def test_check_safe_mode_halves_limit():
    guard = _make_guard(max_agents=4)
    guard._forced_safe = True
    with guard._lock:
        guard._active = 2  # = max_agents // 2
    ok, reason = guard.check_before_agent("safe-agent")
    assert ok is False
    assert "SAFE" in reason


def test_check_safe_mode_allows_below_limit():
    guard = _make_guard(max_agents=4)
    guard._forced_safe = True
    with guard._lock:
        guard._active = 1  # < max_agents // 2 (=2)
    ok, reason = guard.check_before_agent("safe-agent")
    assert ok is True


# ── Force SAFE mode ───────────────────────────────────────────────────────────

def test_force_safe_mode():
    guard = _make_guard(max_agents=4)
    assert guard._forced_safe is False
    guard.force_safe_mode(True)
    assert guard._forced_safe is True
    guard.force_safe_mode(False)
    assert guard._forced_safe is False


# ── Snapshot (psutil absent) ──────────────────────────────────────────────────

def test_snapshot_without_psutil():
    guard = _make_guard(max_agents=2)
    snap = guard._snapshot()
    assert isinstance(snap, ResourceSnapshot)
    assert snap.status == SystemStatus.UNKNOWN
    assert snap.active_agents == 0


# ── get_status_dict ───────────────────────────────────────────────────────────

def test_get_status_dict_keys():
    guard = _make_guard(max_agents=2)
    d = guard.get_status_dict()
    assert "ram_avail_mb" in d
    assert "active_agents" in d
    assert "status" in d
    assert d["status"] == "UNKNOWN"


# ── Singleton ─────────────────────────────────────────────────────────────────

def test_get_resource_guard_singleton():
    import core.resource_guard as rg
    # Réinitialiser le singleton pour ce test
    rg._GUARD_INSTANCE = None
    g1 = get_resource_guard()
    g2 = get_resource_guard()
    assert g1 is g2
    # Cleanup
    g1.stop()
    rg._GUARD_INSTANCE = None
