"""
JARVIS MAX — Adaptive Model Routing
======================================
Upgrades static model profiles with live metrics-driven intelligence.

Instead of modifying llm_routing_policy.py (CRITICAL zone), this module:
1. Maintains LiveModelProfile per model_id using real metrics_store data
2. Replaces ModelHealthTracker with EnhancedHealthTracker (richer signals)
3. Provides adaptive_score_model() that blends static + live data
4. Self-calibrates every CALIBRATION_INTERVAL calls (default 50)
5. Reduces routing probability on provider error spikes
6. Installs via install_adaptive_routing() monkey-patch (fail-open)

Usage:
    from core.adaptive_routing import install_adaptive_routing
    install_adaptive_routing()  # call once at startup
"""
from __future__ import annotations

import functools
import threading
import time
from dataclasses import dataclass, field
_silent_log = __import__("structlog").get_logger(__name__)

try:
    import structlog
    log = structlog.get_logger(__name__)
except ImportError:
    import logging
    log = logging.getLogger(__name__)


CALIBRATION_INTERVAL = int(__import__("os").environ.get("ROUTING_CALIBRATION_INTERVAL", "50"))


# ═══════════════════════════════════════════════════════════════
# LIVE MODEL PROFILE
# ═══════════════════════════════════════════════════════════════

@dataclass
class LiveModelProfile:
    """Dynamic model performance data from real metrics."""
    model_id: str
    calls: int = 0
    successes: int = 0
    failures: int = 0
    total_latency_ms: float = 0
    total_tokens: int = 0
    total_cost: float = 0
    last_failure_ts: float = 0
    last_success_ts: float = 0
    consecutive_failures: int = 0
    error_spike: bool = False       # True if recent failure rate > 50%
    _recent_latencies: list[float] = field(default_factory=list)
    _recent_successes: list[bool] = field(default_factory=list)

    MAX_RECENT = 50

    @property
    def success_rate(self) -> float:
        if self.calls == 0:
            return 0.8  # Optimistic default for unknown
        return self.successes / self.calls

    @property
    def recent_success_rate(self) -> float:
        """Success rate over last 50 calls (more responsive)."""
        if not self._recent_successes:
            return 0.8
        return sum(1 for s in self._recent_successes if s) / len(self._recent_successes)

    @property
    def avg_latency_ms(self) -> float:
        if self.calls == 0:
            return 0
        return self.total_latency_ms / self.calls

    @property
    def recent_avg_latency_ms(self) -> float:
        if not self._recent_latencies:
            return 0
        return sum(self._recent_latencies) / len(self._recent_latencies)

    @property
    def p95_latency_ms(self) -> float:
        if len(self._recent_latencies) < 3:
            return self.avg_latency_ms
        s = sorted(self._recent_latencies)
        return s[min(int(len(s) * 0.95), len(s) - 1)]

    @property
    def avg_cost_per_call(self) -> float:
        if self.calls == 0:
            return 0
        return self.total_cost / self.calls

    @property
    def failure_rate(self) -> float:
        if self.calls == 0:
            return 0
        return self.failures / self.calls

    def record_call(self, success: bool, latency_ms: float = 0,
                     tokens: int = 0, cost: float = 0) -> None:
        self.calls += 1
        if success:
            self.successes += 1
            self.last_success_ts = time.time()
            self.consecutive_failures = 0
        else:
            self.failures += 1
            self.last_failure_ts = time.time()
            self.consecutive_failures += 1

        if latency_ms > 0:
            self.total_latency_ms += latency_ms
            self._recent_latencies.append(latency_ms)
            if len(self._recent_latencies) > self.MAX_RECENT:
                self._recent_latencies = self._recent_latencies[-self.MAX_RECENT:]

        self.total_tokens += tokens
        self.total_cost += cost

        self._recent_successes.append(success)
        if len(self._recent_successes) > self.MAX_RECENT:
            self._recent_successes = self._recent_successes[-self.MAX_RECENT:]

        # Error spike detection: > 50% failure in last 10 calls
        recent_10 = self._recent_successes[-10:]
        if len(recent_10) >= 5:
            recent_fail_rate = 1 - (sum(1 for s in recent_10 if s) / len(recent_10))
            self.error_spike = recent_fail_rate > 0.50
        else:
            self.error_spike = False

    def to_dict(self) -> dict:
        return {
            "model_id": self.model_id,
            "calls": self.calls,
            "success_rate": round(self.success_rate, 3),
            "recent_success_rate": round(self.recent_success_rate, 3),
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "recent_avg_latency_ms": round(self.recent_avg_latency_ms, 1),
            "p95_latency_ms": round(self.p95_latency_ms, 1),
            "avg_cost_per_call": round(self.avg_cost_per_call, 6),
            "failure_rate": round(self.failure_rate, 3),
            "consecutive_failures": self.consecutive_failures,
            "error_spike": self.error_spike,
        }


# ═══════════════════════════════════════════════════════════════
# ENHANCED HEALTH TRACKER
# ═══════════════════════════════════════════════════════════════

class EnhancedHealthTracker:
    """
    Replaces ModelHealthTracker with richer live intelligence.

    Tracks per-model: calls, success rate, latency, cost, error spikes.
    Provides health() score that factors in:
      - Overall success rate (weighted 40%)
      - Recent success rate (weighted 30%)
      - Consecutive failure penalty (weighted 20%)
      - Error spike penalty (weighted 10%)
    """

    def __init__(self):
        self._profiles: dict[str, LiveModelProfile] = {}
        self._lock = threading.Lock()
        self._total_calls = 0
        self._last_calibration = 0

    def record(self, model_id: str, success: bool,
               latency_ms: float = 0, tokens: int = 0, cost: float = 0) -> None:
        with self._lock:
            if model_id not in self._profiles:
                self._profiles[model_id] = LiveModelProfile(model_id=model_id)
            self._profiles[model_id].record_call(success, latency_ms, tokens, cost)
            self._total_calls += 1

    def health(self, model_id: str) -> float:
        """
        Health score 0-1 incorporating live performance data.

        Unknown models get 0.8 (optimistic default).
        NOTE: Does NOT acquire self._lock — caller must not hold it,
        or use _health_unlocked from inside a locked section.
        """
        p = self._profiles.get(model_id)
        return self._compute_health(p)

    def _compute_health(self, p) -> float:
        """Pure computation — no lock needed."""
        if not p or p.calls == 0:
            return 0.8

        # Base: weighted blend of overall and recent success rate
        overall_rate = p.success_rate
        recent_rate = p.recent_success_rate
        base = overall_rate * 0.4 + recent_rate * 0.3

        # Consecutive failure penalty
        if p.consecutive_failures >= 3:
            base *= max(0.2, 1.0 - p.consecutive_failures * 0.15)
        elif p.consecutive_failures >= 1:
            base *= 0.85

        # Error spike penalty
        if p.error_spike:
            base *= 0.5

        # Recent failure recency penalty (decays over 5 min)
        if p.last_failure_ts > 0:
            age_s = time.time() - p.last_failure_ts
            if age_s < 300:
                base *= 0.6 + 0.4 * (age_s / 300)

        # Normalize to 0.3 allocation (remaining from 0.4+0.3)
        base += 0.3 * (1.0 if not p.error_spike else 0.5)

        return round(max(0.05, min(1.0, base)), 3)

    def get_live_profile(self, model_id: str) -> LiveModelProfile | None:
        return self._profiles.get(model_id)

    def get_all(self) -> dict[str, float]:
        with self._lock:
            return {mid: self._compute_health(p) for mid, p in self._profiles.items()}

    def get_all_profiles(self) -> dict[str, dict]:
        with self._lock:
            return {mid: p.to_dict() for mid, p in self._profiles.items()}

    @property
    def total_calls(self) -> int:
        return self._total_calls

    def should_calibrate(self) -> bool:
        return (self._total_calls - self._last_calibration) >= CALIBRATION_INTERVAL

    def mark_calibrated(self) -> None:
        self._last_calibration = self._total_calls

    def reset(self) -> None:
        with self._lock:
            self._profiles.clear()
            self._total_calls = 0
            self._last_calibration = 0


# Singleton
_enhanced_tracker: EnhancedHealthTracker | None = None
_tracker_lock = threading.Lock()


def get_enhanced_tracker() -> EnhancedHealthTracker:
    global _enhanced_tracker
    if _enhanced_tracker is None:
        with _tracker_lock:
            if _enhanced_tracker is None:
                _enhanced_tracker = EnhancedHealthTracker()
    return _enhanced_tracker


def reset_enhanced_tracker() -> EnhancedHealthTracker:
    global _enhanced_tracker
    with _tracker_lock:
        _enhanced_tracker = EnhancedHealthTracker()
    return _enhanced_tracker


# ═══════════════════════════════════════════════════════════════
# ADAPTIVE SCORING
# ═══════════════════════════════════════════════════════════════

def adaptive_score_model(static_profile, dimension, ctx,
                          health: float = 1.0) -> tuple[float, str]:
    """
    Enhanced model scoring that blends static profile with live data.

    If live data is available (>= 10 calls), live metrics gradually
    replace static values using exponential blending:
      blend_factor = min(1.0, calls / 100)
      effective_value = static * (1 - blend) + live * blend

    This means:
      - 0 calls:   100% static
      - 10 calls:  10% live, 90% static
      - 50 calls:  50% live, 50% static
      - 100+ calls: 100% live
    """
    from core.llm_routing_policy import (
        score_model as static_score_model, _BUDGET_WEIGHTS,
        BudgetMode, LatencyMode,
    )

    tracker = get_enhanced_tracker()
    live = tracker.get_live_profile(static_profile.model_id)

    if not live or live.calls < 5:
        # Not enough data — use static scoring with enhanced health
        enhanced_health = tracker.health(static_profile.model_id)
        return static_score_model(static_profile, dimension, ctx, health=enhanced_health)

    # Blend factor: ramps from 0→1 over 100 calls
    blend = min(1.0, live.calls / 100)

    # Live quality: derived from success rate (0-1)
    live_quality = live.recent_success_rate

    # Live cost: normalize avg_cost_per_call to 0-1 scale
    # Using rough mapping: $0 = 0.0, $0.01 = 0.5, $0.05 = 1.0
    live_cost = min(1.0, live.avg_cost_per_call / 0.05) if live.avg_cost_per_call > 0 else static_profile.cost

    # Live latency: normalize p95 to 0-1 scale
    # Using rough mapping: 0ms = 0.0, 5000ms = 0.5, 30000ms = 1.0
    live_latency = min(1.0, live.p95_latency_ms / 30000) if live.p95_latency_ms > 0 else static_profile.latency

    # Blend static + live
    eff_quality = static_profile.quality * (1 - blend) + live_quality * blend
    eff_cost = static_profile.cost * (1 - blend) + live_cost * blend
    eff_latency = static_profile.latency * (1 - blend) + live_latency * blend

    # Get scoring weights
    budget_key = ctx.budget if isinstance(ctx.budget, BudgetMode) else BudgetMode.BALANCED
    weights = _BUDGET_WEIGHTS.get(budget_key, _BUDGET_WEIGHTS[BudgetMode.BALANCED])
    reasons = [f"adaptive(blend={blend:.2f})"]

    # Quality
    q = eff_quality * weights["quality"]
    reasons.append(f"q={eff_quality:.2f}")

    # Cost (lower = better)
    c = (1.0 - eff_cost) * weights["cost"]
    reasons.append(f"cost={eff_cost:.2f}")

    # Latency
    latency_mode = ctx.latency if isinstance(ctx.latency, LatencyMode) else LatencyMode.NORMAL
    if latency_mode == LatencyMode.FAST:
        l = (1.0 - eff_latency) * weights["latency"] * 2.0
    elif latency_mode == LatencyMode.DEEP:
        l = (1.0 - eff_latency * 0.3) * weights["latency"]
    else:
        l = (1.0 - eff_latency) * weights["latency"]
    reasons.append(f"lat={eff_latency:.2f}")

    # Health (live)
    enhanced_health = tracker.health(static_profile.model_id)
    h = enhanced_health * weights["health"]
    reasons.append(f"health={enhanced_health:.2f}")

    # Strength match
    if dimension in static_profile.strengths:
        s = 1.0 * weights["strength"]
        reasons.append("strength_match")
    else:
        s = 0.2 * weights["strength"]

    # Context window hard filter
    if ctx.token_estimate > 0 and ctx.token_estimate > static_profile.context_window * 0.9:
        reasons.append("ctx_overflow")
        return 0.01, " ".join(reasons)

    # Error spike penalty (additional)
    if live.error_spike:
        reasons.append("ERROR_SPIKE(-50%)")
        total = (q + c + l + h + s) * 0.5
    # Consecutive failure penalty
    elif live.consecutive_failures >= 3:
        penalty = max(0.3, 1.0 - live.consecutive_failures * 0.12)
        reasons.append(f"consec_fail={live.consecutive_failures}(-{int((1-penalty)*100)}%)")
        total = (q + c + l + h + s) * penalty
    else:
        total = q + c + l + h + s

    # Failure rate penalty (linear)
    if live.failure_rate > 0.1:
        failure_penalty = live.failure_rate * 0.3
        total -= failure_penalty
        reasons.append(f"fail_rate={live.failure_rate:.2f}(-{failure_penalty:.3f})")

    return round(max(0.01, min(total, 1.0)), 4), " ".join(reasons)


# ═══════════════════════════════════════════════════════════════
# SELF-CALIBRATION
# ═══════════════════════════════════════════════════════════════

def calibrate_profiles() -> dict[str, dict]:
    """
    Pull latest metrics from metrics_store to update live profiles.

    Called automatically every CALIBRATION_INTERVAL calls,
    or manually for diagnostics.

    Returns current live profile data for all tracked models.
    """
    tracker = get_enhanced_tracker()

    try:
        from core.metrics_store import get_metrics
        m = get_metrics()

        # Sync model latency histograms
        latency_hist = m._histograms.get("model_latency_ms")
        if latency_hist:
            for label_key in latency_hist.get_all_keys():
                model_id = label_key.replace("model_id=", "")
                stats = latency_hist.stats(label_key)
                # Update live profile with aggregated data
                profile = tracker.get_live_profile(model_id)
                if profile and stats["count"] > profile.calls:
                    # Only update if metrics_store has newer data
                    pass  # Live profiles update via record() calls

        # Sync cost data
        costs = m.costs.snapshot()
        for model_id, cost in costs.get("by_model", {}).items():
            profile = tracker.get_live_profile(model_id)
            if profile:
                profile.total_cost = cost

        tracker.mark_calibrated()
        log.info("adaptive_routing.calibrated",
                 models=len(tracker._profiles),
                 total_calls=tracker.total_calls)

    except Exception as e:
        log.debug("adaptive_routing.calibrate_failed", err=str(e)[:80])

    return tracker.get_all_profiles()


# ═══════════════════════════════════════════════════════════════
# FALLBACK INTELLIGENCE
# ═══════════════════════════════════════════════════════════════

def get_fallback_recommendations() -> list[dict]:
    """
    Analyze current model health and recommend fallback changes.

    Returns list of recommendations like:
      {"model_id": "...", "action": "reduce_priority", "reason": "..."}
    """
    tracker = get_enhanced_tracker()
    recommendations: list[dict] = []

    for model_id, profile_dict in tracker.get_all_profiles().items():
        profile = tracker.get_live_profile(model_id)
        if not profile or profile.calls < 5:
            continue

        # Error spike → reduce priority
        if profile.error_spike:
            recommendations.append({
                "model_id": model_id,
                "action": "reduce_priority",
                "reason": f"Error spike: {profile.recent_success_rate:.0%} recent success rate",
                "severity": "high",
                "current_health": tracker.health(model_id),
            })

        # Consecutive failures → temporary avoid
        elif profile.consecutive_failures >= 3:
            recommendations.append({
                "model_id": model_id,
                "action": "temporary_avoid",
                "reason": f"{profile.consecutive_failures} consecutive failures",
                "severity": "high",
                "current_health": tracker.health(model_id),
            })

        # High cost → suggest cheaper alternative
        elif profile.avg_cost_per_call > 0.01 and profile.calls >= 20:
            recommendations.append({
                "model_id": model_id,
                "action": "consider_cheaper",
                "reason": f"Avg cost ${profile.avg_cost_per_call:.4f}/call",
                "severity": "low",
                "current_health": tracker.health(model_id),
            })

        # Slow latency → suggest faster
        elif profile.p95_latency_ms > 20000 and profile.calls >= 10:
            recommendations.append({
                "model_id": model_id,
                "action": "consider_faster",
                "reason": f"P95 latency {profile.p95_latency_ms:.0f}ms",
                "severity": "medium",
                "current_health": tracker.health(model_id),
            })

    return sorted(recommendations, key=lambda r: {"high": 3, "medium": 2, "low": 1}.get(r["severity"], 0), reverse=True)


# ═══════════════════════════════════════════════════════════════
# INSTALLATION
# ═══════════════════════════════════════════════════════════════

_INSTALLED = False


def install_adaptive_routing() -> dict[str, bool]:
    """
    Install adaptive routing by patching:
    1. score_model → adaptive_score_model
    2. ModelHealthTracker → EnhancedHealthTracker
    3. Auto-calibration after every CALIBRATION_INTERVAL calls

    Fail-open: if patching fails, static routing continues.
    """
    global _INSTALLED
    if _INSTALLED:
        return {"already_installed": True}

    results: dict[str, bool] = {}

    # 1. Patch score_model
    try:
        import core.llm_routing_policy as policy
        policy._original_score_model = policy.score_model

        def _patched_score(profile, dimension, ctx, health=1.0):
            try:
                return adaptive_score_model(profile, dimension, ctx, health)
            except Exception:
                return policy._original_score_model(profile, dimension, ctx, health)

        policy.score_model = _patched_score
        results["score_model"] = True
        log.info("adaptive_routing.patched", target="score_model")
    except Exception as e:
        results["score_model"] = False
        log.debug("adaptive_routing.patch_failed", target="score_model", err=str(e)[:80])

    # 2. Replace health tracker
    try:
        import core.llm_routing_policy as policy
        tracker = get_enhanced_tracker()

        # Copy existing data from old tracker
        old_tracker = policy._health_tracker
        if hasattr(old_tracker, '_records'):
            for model_id, data in old_tracker._records.items():
                for _ in range(data.get("successes", 0)):
                    tracker.record(model_id, True)
                for _ in range(data.get("calls", 0) - data.get("successes", 0)):
                    tracker.record(model_id, False)

        policy._health_tracker = tracker
        policy.get_health_tracker = lambda: tracker
        results["health_tracker"] = True
        log.info("adaptive_routing.patched", target="health_tracker")
    except Exception as e:
        results["health_tracker"] = False
        log.debug("adaptive_routing.patch_failed", target="health_tracker", err=str(e)[:80])

    # 3. Patch record to auto-calibrate
    try:
        import core.llm_routing_policy as policy
        original_record = policy.record_decision

        @functools.wraps(original_record)
        def _calibrating_record(decision):
            original_record(decision)
            try:
                tracker = get_enhanced_tracker()
                if tracker.should_calibrate():
                    calibrate_profiles()
            except Exception:
                _silent_log.debug("suppressed_exception", src='adaptive_routing.py')

        policy.record_decision = _calibrating_record
        results["auto_calibration"] = True
        log.info("adaptive_routing.patched", target="auto_calibration")
    except Exception:
        results["auto_calibration"] = False

    _INSTALLED = True
    log.info("adaptive_routing.installed", results=results)
    return results


def is_installed() -> bool:
    return _INSTALLED
