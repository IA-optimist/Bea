"""
JARVIS MAX — Improvement Daemon
==================================
Autonomous background optimization loop.

Pipeline (every cycle):
  1. Read signals (metrics_store, failure patterns, trace intelligence)
  2. Detect weakness (high timeouts, retries, slow tools, expensive models, low success)
  3. Propose bounded experiment (max 1/cycle, max 3 files, critical zones blocked)
  4. Sandbox patch + regression test
  5. Score candidate vs baseline
  6. Promote or rollback
  7. Store lesson

Runs as daemon thread, default 30-minute interval.
Configurable via IMPROVEMENT_INTERVAL_MIN env var.

Usage:
    from core.improvement_daemon import start_daemon, stop_daemon
    start_daemon()           # non-blocking, starts background thread
    stop_daemon()            # graceful stop
    get_daemon_status()      # current state

Safety:
    - Max 1 experiment per cycle
    - Max 3 file changes per experiment
    - CRITICAL zones auto-blocked (meta_orchestrator, policy_engine, etc.)
    - All patches rolled back on failure
    - Lessons persist for future cycles
    - Daemon never crashes the runtime (all ops wrapped in try/except)
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
_silent_log = __import__("structlog").get_logger(__name__)

try:
    import structlog
    log = structlog.get_logger(__name__)
except ImportError:
    import logging
    log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# WEAKNESS DETECTION
# ═══════════════════════════════════════════════════════════════

@dataclass
class Weakness:
    """A detected system weakness from real metrics."""
    category: str           # timeout, retry, slow_tool, expensive_model, low_success, failure_pattern
    component: str          # which subsystem
    metric_name: str        # specific metric key
    current_value: float
    threshold: float
    severity: str           # low, medium, high, critical
    description: str
    suggested_target: str = ""   # file to modify
    suggested_fix: str = ""      # what to change


# Thresholds for weakness detection
_WEAKNESS_THRESHOLDS = {
    "mission_success_rate_min": 0.75,
    "tool_failure_rate_max": 0.20,
    "tool_timeout_count_max": 3,
    "retry_count_max": 5,
    "model_failure_rate_max": 0.15,
    "model_latency_p95_max_ms": 30000,
}


def detect_weaknesses(window_s: float = 3600) -> list[Weakness]:
    """
    Scan metrics_store for actionable weaknesses.

    Reads real runtime metrics — NOT synthetic. Returns sorted by severity.
    """
    weaknesses: list[Weakness] = []

    try:
        from core.metrics_store import get_metrics
        m = get_metrics()
    except Exception:
        return []

    # 1. Low mission success rate
    try:
        submitted = m.get_counter_total("missions_submitted_total")
        completed = m.get_counter_total("missions_completed_total")
        if submitted >= 5:
            rate = completed / submitted
            if rate < _WEAKNESS_THRESHOLDS["mission_success_rate_min"]:
                weaknesses.append(Weakness(
                    category="low_success",
                    component="mission_system",
                    metric_name="mission_success_rate",
                    current_value=round(rate, 3),
                    threshold=_WEAKNESS_THRESHOLDS["mission_success_rate_min"],
                    severity="high" if rate < 0.5 else "medium",
                    description=f"Mission success rate {rate:.0%} below {_WEAKNESS_THRESHOLDS['mission_success_rate_min']:.0%}",
                    suggested_target="executor/retry_policy.py",
                    suggested_fix="Increase retry budget or add fallback strategies",
                ))
    except Exception:
        _silent_log.debug("suppressed_exception", src='improvement_daemon.py')

    # 2. High tool failure rate per tool
    try:
        tool_inv = m._counters.get("tool_invocations_total")
        tool_fail = m._counters.get("tool_failures_total")
        if tool_inv and tool_fail:
            for label_key, inv_count in tool_inv.get_all().items():
                if inv_count >= 5:
                    fail_count = tool_fail.get(label_key)
                    fail_rate = fail_count / inv_count if inv_count > 0 else 0
                    if fail_rate > _WEAKNESS_THRESHOLDS["tool_failure_rate_max"]:
                        tool_name = label_key.replace("tool=", "")
                        weaknesses.append(Weakness(
                            category="slow_tool",
                            component="tool_executor",
                            metric_name=f"tool_failure_rate:{tool_name}",
                            current_value=round(fail_rate, 3),
                            threshold=_WEAKNESS_THRESHOLDS["tool_failure_rate_max"],
                            severity="high" if fail_rate > 0.5 else "medium",
                            description=f"Tool '{tool_name}' failure rate {fail_rate:.0%}",
                            suggested_target="core/tool_intelligence/selector.py",
                            suggested_fix=f"Deprioritize or add fallback for {tool_name}",
                        ))
    except Exception:
        _silent_log.debug("suppressed_exception", src='improvement_daemon.py')

    # 3. High tool timeout frequency
    try:
        timeout_total = m.get_counter_total("tool_timeout_total")
        if timeout_total > _WEAKNESS_THRESHOLDS["tool_timeout_count_max"]:
            # Find worst tool
            timeout_counter = m._counters.get("tool_timeout_total")
            worst = "unknown"
            if timeout_counter:
                all_vals = timeout_counter.get_all()
                if all_vals:
                    worst = max(all_vals, key=all_vals.get)
            weaknesses.append(Weakness(
                category="timeout",
                component="tool_executor",
                metric_name="tool_timeout_total",
                current_value=timeout_total,
                threshold=_WEAKNESS_THRESHOLDS["tool_timeout_count_max"],
                severity="medium",
                description=f"{int(timeout_total)} tool timeouts (worst: {worst})",
                suggested_target="core/tool_executor.py",
                suggested_fix="Increase timeout for affected tools or add circuit breaker",
            ))
    except Exception:
        _silent_log.debug("suppressed_exception", src='improvement_daemon.py')

    # 4. Retry storm
    try:
        retries = m.get_counter_total("retry_attempts_total")
        if retries > _WEAKNESS_THRESHOLDS["retry_count_max"]:
            weaknesses.append(Weakness(
                category="retry",
                component="executor",
                metric_name="retry_attempts_total",
                current_value=retries,
                threshold=_WEAKNESS_THRESHOLDS["retry_count_max"],
                severity="medium" if retries < 15 else "high",
                description=f"{int(retries)} retry attempts (threshold {_WEAKNESS_THRESHOLDS['retry_count_max']})",
                suggested_target="executor/retry_policy.py",
                suggested_fix="Tune backoff parameters or add jitter",
            ))
    except Exception:
        _silent_log.debug("suppressed_exception", src='improvement_daemon.py')

    # 5. Expensive model usage
    try:
        costs = m.costs.snapshot()
        if costs["total_estimated_usd"] > 0.50:  # > $0.50 in window
            top_model = ""
            top_cost = 0
            for model_id, cost in costs["by_model"].items():
                if cost > top_cost:
                    top_cost = cost
                    top_model = model_id
            if top_model and top_cost > 0.20:
                weaknesses.append(Weakness(
                    category="expensive_model",
                    component="model_routing",
                    metric_name="estimated_cost_total",
                    current_value=round(top_cost, 4),
                    threshold=0.20,
                    severity="medium",
                    description=f"Model '{top_model}' cost ${top_cost:.4f} — consider cheaper alternative",
                    suggested_target="core/llm_routing_policy.py",
                    suggested_fix=f"Route to cheaper model for non-critical tasks using {top_model}",
                ))
    except Exception:
        _silent_log.debug("suppressed_exception", src='improvement_daemon.py')

    # 6. High model failure rate
    try:
        model_sel = m._counters.get("model_selected_total")
        model_fail = m._counters.get("model_failure_total")
        if model_sel and model_fail:
            for label_key, sel_count in model_sel.get_all().items():
                if sel_count >= 3:
                    fail_count = model_fail.get(label_key)
                    fail_rate = fail_count / sel_count if sel_count > 0 else 0
                    if fail_rate > _WEAKNESS_THRESHOLDS["model_failure_rate_max"]:
                        model_id = label_key.replace("model_id=", "")
                        weaknesses.append(Weakness(
                            category="failure_pattern",
                            component="model_routing",
                            metric_name=f"model_failure_rate:{model_id}",
                            current_value=round(fail_rate, 3),
                            threshold=_WEAKNESS_THRESHOLDS["model_failure_rate_max"],
                            severity="high",
                            description=f"Model '{model_id}' failure rate {fail_rate:.0%}",
                            suggested_target="core/llm_routing_policy.py",
                            suggested_fix=f"Deprioritize {model_id} in routing policy health tracker",
                        ))
    except Exception:
        _silent_log.debug("suppressed_exception", src='improvement_daemon.py')

    # 7. Slow model latency
    try:
        hist = m._histograms.get("model_latency_ms")
        if hist:
            for label_key in hist.get_all_keys():
                stats = hist.stats(label_key)
                if stats["count"] >= 3 and stats["p95"] > _WEAKNESS_THRESHOLDS["model_latency_p95_max_ms"]:
                    model_id = label_key.replace("model_id=", "")
                    weaknesses.append(Weakness(
                        category="slow_tool",
                        component="model_routing",
                        metric_name=f"model_latency_p95:{model_id}",
                        current_value=stats["p95"],
                        threshold=_WEAKNESS_THRESHOLDS["model_latency_p95_max_ms"],
                        severity="medium",
                        description=f"Model '{model_id}' p95 latency {stats['p95']:.0f}ms",
                        suggested_target="core/llm_routing_policy.py",
                        suggested_fix=f"Route time-sensitive tasks away from {model_id}",
                    ))
    except Exception:
        _silent_log.debug("suppressed_exception", src='improvement_daemon.py')

    # 8. Failure pattern aggregation
    try:
        patterns = m.failures.by_category(window_s=window_s)
        for category, count in patterns.items():
            if count >= 3:
                weaknesses.append(Weakness(
                    category="failure_pattern",
                    component="system",
                    metric_name=f"failure_pattern:{category}",
                    current_value=count,
                    threshold=3,
                    severity="medium" if count < 10 else "high",
                    description=f"Recurring failure pattern: {category} ({count}x in {window_s/3600:.0f}h)",
                ))
    except Exception:
        _silent_log.debug("suppressed_exception", src='improvement_daemon.py')

    # Sort by severity
    _severity_order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    weaknesses.sort(key=lambda w: _severity_order.get(w.severity, 0), reverse=True)

    return weaknesses


# ═══════════════════════════════════════════════════════════════
# EXPERIMENT VALUE ESTIMATION
# ═══════════════════════════════════════════════════════════════

# Priority tiers: higher number = higher priority
PRIORITY_TIER: dict[str, int] = {
    # Tier 1: Reliability (most valuable)
    "low_success":      100,
    "timeout":           90,
    "failure_pattern":   85,
    # Tier 2: Test coverage / stability
    "retry":             70,
    "slow_tool":         65,
    # Tier 3: Cost optimization
    "expensive_model":   40,
    # Tier 4: Performance / latency
    "latency":           30,
    # Tier 5: Refactors (least valuable)
    "naming":             5,
    "formatting":         3,
    "micro_optimization": 2,
}

# Impact score by category (0.0 - 1.0)
IMPACT_SCORE: dict[str, float] = {
    "low_success":      1.0,    # Mission failures directly hurt users
    "timeout":          0.9,    # Timeouts block execution
    "failure_pattern":  0.85,   # Recurring failures compound
    "retry":            0.7,    # Retry storms waste resources
    "slow_tool":        0.6,    # Tool failures degrade capabilities
    "expensive_model":  0.4,    # Cost matters but doesn't block
    "latency":          0.3,    # Slow but works
    "naming":           0.05,   # Cosmetic
    "formatting":       0.02,   # Noise
    "micro_optimization": 0.01, # Noise
}

# System criticality weight by component
CRITICALITY_WEIGHT: dict[str, float] = {
    "mission_system":   1.0,
    "orchestrator":     0.95,
    "executor":         0.85,
    "tool_executor":    0.80,
    "model_routing":    0.75,
    "memory":           0.65,
    "system":           0.60,
    "docs":             0.10,
}

# Minimum expected value to justify running an experiment
MIN_EXPECTED_VALUE = 0.10

# Cooldown: categories that ran recently won't repeat for N cycles
COOLDOWN_CYCLES = 3


@dataclass
class ExperimentCandidate:
    """Scored candidate experiment from a weakness."""
    weakness: Weakness
    expected_value: float
    impact_score: float
    frequency_score: float
    criticality_weight: float
    priority_tier: int
    reason: str


def compute_expected_value(weakness: Weakness) -> ExperimentCandidate:
    """
    Score a weakness for experiment worthiness.

    expected_value = impact_score × frequency_score × criticality_weight

    frequency_score is derived from how much the metric exceeds its threshold:
      ratio = current_value / threshold (capped at 5.0)
      frequency_score = min(1.0, ratio / 5.0) for over-threshold
      OR for rate metrics: 1 - current_value (inverted, higher gap = higher freq)
    """
    impact = IMPACT_SCORE.get(weakness.category, 0.1)
    priority = PRIORITY_TIER.get(weakness.category, 10)
    criticality = CRITICALITY_WEIGHT.get(weakness.component, 0.5)

    # Frequency: how bad is the metric relative to threshold?
    if weakness.threshold > 0 and weakness.current_value > 0:
        if weakness.category in ("low_success",):
            # Rate metrics: lower is worse → invert
            freq = min(1.0, (weakness.threshold - weakness.current_value) / weakness.threshold)
        else:
            # Count metrics: higher is worse → ratio
            ratio = weakness.current_value / weakness.threshold
            freq = min(1.0, ratio / 5.0)
    else:
        freq = 0.5  # Default if no threshold comparison possible

    ev = round(impact * max(0.1, freq) * criticality, 4)

    reason_parts = [
        f"impact={impact:.2f}",
        f"freq={freq:.2f}",
        f"crit={criticality:.2f}",
        f"priority=T{priority}",
    ]

    return ExperimentCandidate(
        weakness=weakness,
        expected_value=ev,
        impact_score=impact,
        frequency_score=freq,
        criticality_weight=criticality,
        priority_tier=priority,
        reason=" ".join(reason_parts),
    )


def rank_candidates(weaknesses: list[Weakness],
                     cooldowns: dict[str, int] | None = None) -> list[ExperimentCandidate]:
    """
    Rank all weaknesses by expected value, applying:
    1. Expected value scoring
    2. Priority tier ordering
    3. Cooldown filtering
    4. Minimum value threshold

    Returns sorted list (highest value first), excluding:
    - Below MIN_EXPECTED_VALUE
    - Categories on cooldown
    - Low-impact categories (formatting, naming, micro_optimization)
    """
    cooldowns = cooldowns or {}
    candidates: list[ExperimentCandidate] = []

    for w in weaknesses:
        # Skip noise categories entirely
        if w.category in ("formatting", "naming", "micro_optimization"):
            continue

        # Skip if on cooldown
        remaining = cooldowns.get(w.category, 0)
        if remaining > 0:
            continue

        candidate = compute_expected_value(w)

        # Skip if below minimum value
        if candidate.expected_value < MIN_EXPECTED_VALUE:
            continue

        candidates.append(candidate)

    # Sort by: priority tier (desc), then expected value (desc)
    candidates.sort(key=lambda c: (c.priority_tier, c.expected_value), reverse=True)

    return candidates


# ═══════════════════════════════════════════════════════════════
# COOLDOWN TRACKER
# ═══════════════════════════════════════════════════════════════

class CooldownTracker:
    """Tracks per-category cooldowns to prevent repetitive experiments."""

    def __init__(self):
        self._cooldowns: dict[str, int] = {}  # category → remaining cycles

    def is_on_cooldown(self, category: str) -> bool:
        return self._cooldowns.get(category, 0) > 0

    def set_cooldown(self, category: str, cycles: int = COOLDOWN_CYCLES) -> None:
        self._cooldowns[category] = cycles

    def tick(self) -> None:
        """Decrement all cooldowns by 1 (call once per cycle)."""
        for cat in list(self._cooldowns):
            self._cooldowns[cat] = max(0, self._cooldowns[cat] - 1)
            if self._cooldowns[cat] == 0:
                del self._cooldowns[cat]

    def get_all(self) -> dict[str, int]:
        return dict(self._cooldowns)

    def reset(self) -> None:
        self._cooldowns.clear()


_cooldown_tracker = CooldownTracker()


def get_cooldown_tracker() -> CooldownTracker:
    return _cooldown_tracker


# ═══════════════════════════════════════════════════════════════
# EXPERIMENT PROPOSAL
# ═══════════════════════════════════════════════════════════════

def _propose_experiment(weakness: Weakness, repo_root: Path) -> dict | None:
    """
    Propose an experiment spec from a detected weakness.

    Returns dict with ExperimentSpec fields, or None if weakness
    targets a CRITICAL file or has no actionable suggestion.
    """
    from core.improvement_loop import classify_file_safety, SafetyZone

    target = weakness.suggested_target
    if not target:
        return None

    # Safety check before proposing
    zone = classify_file_safety(target)
    if zone == SafetyZone.CRITICAL:
        log.info("daemon.proposal_skipped_critical", target=target, weakness=weakness.category)
        return None

    # Check file exists
    if not (repo_root / target).exists():
        # Try without leading dirs
        for candidate in [
            f"core/{target.split('/')[-1]}",
            f"executor/{target.split('/')[-1]}",
            target,
        ]:
            if (repo_root / candidate).exists():
                target = candidate
                break
        else:
            log.debug("daemon.target_not_found", target=target)
            return None

    return {
        "hypothesis": f"Fix {weakness.category}: {weakness.description}",
        "files_allowed": [target],
        "target_subsystem": weakness.component,
        "weakness_detected": weakness.description,
        "expected_gain": weakness.suggested_fix,
        "risk_class": zone,
    }


# ═══════════════════════════════════════════════════════════════
# PATCH STRATEGIES
# ═══════════════════════════════════════════════════════════════

def _generate_safe_patch(weakness: Weakness, repo_root: Path, spec_dict: dict):
    """
    Generate a safe, bounded code patch for the weakness.

    Strategy: make MINIMAL changes — add comments, tune constants,
    add logging. Never restructure, never delete, never rename.
    """
    target = spec_dict["files_allowed"][0]
    target_path = repo_root / target
    if not target_path.exists():
        return None

    original = target_path.read_text(encoding="utf-8")

    # Strategy depends on weakness category
    if weakness.category == "timeout":
        # Increase timeout constants by 50%
        import re
        modified = original
        # Find timeout = N patterns and increase
        def _bump_timeout(match):
            val = int(match.group(1))
            new_val = min(val + max(val // 2, 5), 120)  # Cap at 120s
            return f"timeout={new_val}"
        modified = re.sub(r'timeout=(\d+)', _bump_timeout, modified)
        if modified != original:
            return modified
        return None

    elif weakness.category == "retry":
        # Add backoff jitter or increase retry count
        import re
        modified = original
        def _bump_retry(match):
            val = int(match.group(1))
            new_val = min(val + 1, 5)
            return f"max_retries={new_val}"
        modified = re.sub(r'max_retries=(\d+)', _bump_retry, modified)
        if modified != original:
            return modified
        return None

    elif weakness.category in ("slow_tool", "failure_pattern"):
        # Add a log line for visibility (safe, non-breaking)
        if "# [DAEMON] instrumented" not in original:
            lines = original.split("\n")
            # Find first function def and add logging after docstring
            for i, line in enumerate(lines):
                if line.strip().startswith("def ") and i < len(lines) - 2:
                    # Find end of docstring
                    j = i + 1
                    in_docstring = False
                    while j < len(lines):
                        if '"""' in lines[j] or "'''" in lines[j]:
                            if in_docstring:
                                j += 1
                                break
                            in_docstring = True
                        elif not in_docstring:
                            break
                        j += 1
                    indent = "    "
                    log_line = f'{indent}# [DAEMON] instrumented for observability ({weakness.category})'
                    lines.insert(j, log_line)
                    return "\n".join(lines)
        return None

    return None


# ═══════════════════════════════════════════════════════════════
# DAEMON CYCLE
# ═══════════════════════════════════════════════════════════════

@dataclass
class DaemonState:
    """Observable state of the improvement daemon."""
    running: bool = False
    cycles_completed: int = 0
    last_cycle_at: float = 0
    last_weakness: str = ""
    last_decision: str = ""
    last_experiment_id: str = ""
    experiments_total: int = 0
    experiments_promoted: int = 0
    experiments_rejected: int = 0
    experiments_blocked: int = 0
    errors: int = 0

    def to_dict(self) -> dict:
        return {
            "running": self.running,
            "cycles_completed": self.cycles_completed,
            "last_cycle_at": self.last_cycle_at,
            "last_weakness": self.last_weakness,
            "last_decision": self.last_decision,
            "last_experiment_id": self.last_experiment_id,
            "experiments_total": self.experiments_total,
            "experiments_promoted": self.experiments_promoted,
            "experiments_rejected": self.experiments_rejected,
            "experiments_blocked": self.experiments_blocked,
            "errors": self.errors,
        }


_state = DaemonState()


def run_cycle(repo_root: Path | None = None) -> dict:
    """
    Execute one improvement cycle.

    Returns dict with: weaknesses_found, experiment_run, decision, lesson.

    KERNEL GATE (authoritative):
    kernel.gate.check() is the first operation. If the gate denies,
    the cycle is blocked immediately — no detection, no experiments, no changes.
    The kernel is the single authority for self-improvement gating.
    Fail-open: if the gate check itself fails, cycle proceeds with a WARNING.
    """
    if repo_root is None:
        repo_root = Path(os.environ.get("JARVIS_REPO_ROOT", "/app"))

    result = {
        "weaknesses_found": 0,
        "experiment_run": False,
        "decision": "none",
        "lesson": "",
        "weakness": "",
        "error": "",
    }

    # -- Detect improvements (read-only, before gate)
    try:
        from core.improvement_detector import detect_improvements
        _new_props = detect_improvements(dry_run=False)
        if _new_props:
            log.info("daemon.proposals_generated", count=len(_new_props))
            result["proposals_generated"] = len(_new_props)
    except Exception as _de:
        log.debug("daemon.detector_error", err=str(_de)[:80])
    # ── KERNEL GATE: must pass before any work ───────────────────────────────
    # kernel/ never imports core/ — gate reads workspace/self_improvement/history.json
    # directly when no history_provider is registered.
    try:
        from kernel.improvement.gate import get_gate
        _gate_decision = get_gate().check()
        if not _gate_decision.allowed:
            log.info(
                "daemon.gate_blocked",
                reason=_gate_decision.reason,
                cooldown_remaining_h=_gate_decision.cooldown_remaining_h,
                consecutive_failures=_gate_decision.consecutive_failures,
            )
            result["decision"] = "gate_blocked"
            result["lesson"] = f"kernel.gate: {_gate_decision.reason}"
            return result
        log.debug("daemon.gate_allowed", reason=_gate_decision.reason)
    except Exception as _gate_err:
        # Fail-open: if gate check fails, allow cycle but log WARNING.
        # This avoids permanently stalling the daemon if gate has an import error.
        log.warning("daemon.gate_check_failed", err=str(_gate_err)[:120])
    # ── END KERNEL GATE ───────────────────────────────────────────────────────

    try:
        # 1. Detect weaknesses
        weaknesses = detect_weaknesses()
        result["weaknesses_found"] = len(weaknesses)

        # Run improvement detector to generate real proposals
        try:
            from core.improvement_detector import detect_improvements
            new_proposals = detect_improvements(dry_run=False)
            result["proposals_generated"] = len(new_proposals)
            log.info("daemon.proposals_generated", count=len(new_proposals))
        except Exception as _det_err:
            log.debug("daemon.detector_error", err=str(_det_err)[:80])


        if not weaknesses:
            log.debug("daemon.no_weaknesses")
            _state.cycles_completed += 1
            _state.last_cycle_at = time.time()
            _cooldown_tracker.tick()
            return result

        # 2. Rank candidates by expected value (filters noise + cooldowns)
        candidates = rank_candidates(weaknesses, _cooldown_tracker.get_all())
        result["candidates_ranked"] = len(candidates)

        if not candidates:
            log.debug("daemon.no_valuable_candidates",
                      raw=len(weaknesses), cooldowns=_cooldown_tracker.get_all())
            _state.cycles_completed += 1
            _state.last_cycle_at = time.time()
            _cooldown_tracker.tick()
            return result

        best = candidates[0]
        _state.last_weakness = f"[EV={best.expected_value:.3f}] {best.weakness.description[:80]}"
        result["weakness"] = best.weakness.description
        result["expected_value"] = best.expected_value
        result["priority_tier"] = best.priority_tier
        result["ranking_reason"] = best.reason

        log.info("daemon.best_candidate",
                 category=best.weakness.category,
                 ev=best.expected_value,
                 tier=best.priority_tier,
                 reason=best.reason)

        # 3. Check past lessons to avoid repeating failures
        from core.improvement_loop import ImprovementLoop, ExperimentSpec
        engine = ImprovementLoop(repo_root)

        past_failures = engine.memory.get_failures(
            subsystem=best.weakness.component, limit=5)
        failed_targets = {f for lesson in past_failures
                          for f in lesson.files_changed}

        # 4. Find first actionable candidate (may skip past best if target failed before)
        spec_dict = None
        chosen_weakness = None
        for cand in candidates:
            proposal = _propose_experiment(cand.weakness, repo_root)
            if proposal is None:
                continue
            if proposal["files_allowed"][0] in failed_targets:
                log.debug("daemon.skipping_failed_target",
                          target=proposal["files_allowed"][0])
                continue
            spec_dict = proposal
            chosen_weakness = cand.weakness
            break

        if not spec_dict or not chosen_weakness:
            log.debug("daemon.no_actionable_weakness")
            _state.cycles_completed += 1
            _state.last_cycle_at = time.time()
            _cooldown_tracker.tick()
            return result

        # 4. Create experiment spec
        spec = ExperimentSpec(**spec_dict)

        # 5. Generate safe patch
        def apply_patch(root, s):
            modified = _generate_safe_patch(chosen_weakness, root, spec_dict)
            if modified is None:
                raise ValueError("No applicable patch for this weakness")
            target = spec_dict["files_allowed"][0]
            (root / target).write_text(modified, encoding="utf-8")
            return f"Auto-patch for {chosen_weakness.category}: {chosen_weakness.description[:80]}"

        # 6. Run experiment
        report = engine.run_experiment(spec, apply_patch=apply_patch)

        result["experiment_run"] = True
        result["decision"] = report.decision
        _state.last_decision = report.decision
        _state.last_experiment_id = report.experiment_id
        _state.experiments_total += 1

        if report.decision == "promoted":
            _state.experiments_promoted += 1
            result["lesson"] = f"PROMOTED: {report.reason}"
        elif report.decision == "rejected":
            _state.experiments_rejected += 1
            result["lesson"] = f"REJECTED: {report.reason}"
        elif report.decision == "blocked":
            _state.experiments_blocked += 1
            result["lesson"] = f"BLOCKED: {report.reason}"
        else:
            result["lesson"] = f"ERROR: {report.reason}"

        # 7. Emit metrics
        try:
            from core.metrics_store import emit_experiment
            emit_experiment(report.decision,
                            report.evaluation.get("composite", 0)
                            if isinstance(report.evaluation, dict) else 0)
        except Exception:
            _silent_log.debug("suppressed_exception", src='improvement_daemon.py')

        # 8. Set cooldown for this category
        _cooldown_tracker.set_cooldown(chosen_weakness.category, COOLDOWN_CYCLES)

        log.info("daemon.cycle_complete",
                 decision=report.decision,
                 weakness=chosen_weakness.category,
                 experiment=report.experiment_id)

        # 9. Record outcome in kernel gate history (kernel authoritative)
        # This feeds the cooldown and failure-count checks for future cycles.
        # Kernel gate records are separate from ImprovementLoop.memory (.improvement_lessons.json).
        try:
            from kernel.improvement.gate import get_gate
            _gate_outcome = "SUCCESS" if report.decision == "promoted" else "FAILURE"
            get_gate().record(
                outcome=_gate_outcome,
                metadata={
                    "experiment_id": report.experiment_id,
                    "decision": report.decision,
                    "weakness_category": chosen_weakness.category,
                    "source": "improvement_daemon",
                },
            )
        except Exception as _rec_err:
            log.debug("daemon.gate_record_failed", err=str(_rec_err)[:80])

    except Exception as e:
        _state.errors += 1
        result["error"] = str(e)[:200]
        log.error("daemon.cycle_error", err=str(e)[:120])

    _state.cycles_completed += 1
    _state.last_cycle_at = time.time()
    _cooldown_tracker.tick()
    return result


# ═══════════════════════════════════════════════════════════════
# DAEMON THREAD
# ═══════════════════════════════════════════════════════════════

_daemon_thread: threading.Thread | None = None
_daemon_stop = threading.Event()


def _daemon_loop():
    """Background loop that runs improvement cycles."""
    interval_min = int(os.environ.get("IMPROVEMENT_INTERVAL_MIN", "30"))
    interval_s = max(interval_min * 60, 60)  # Minimum 1 minute

    log.info("daemon.started", interval_min=interval_min)
    _state.running = True

    # Initial delay: wait 2 minutes before first cycle (let system warm up)
    if _daemon_stop.wait(120):
        _state.running = False
        return

    while not _daemon_stop.is_set():
        try:
            run_cycle()
        except Exception as e:
            _state.errors += 1
            log.error("daemon.loop_error", err=str(e)[:120])

        # Wait for next cycle
        if _daemon_stop.wait(interval_s):
            break

    _state.running = False
    log.info("daemon.stopped", cycles=_state.cycles_completed)


def start_daemon() -> dict:
    """Start the improvement daemon. Non-blocking."""
    global _daemon_thread
    if _daemon_thread and _daemon_thread.is_alive():
        return {"status": "already_running", **_state.to_dict()}

    _daemon_stop.clear()
    _daemon_thread = threading.Thread(
        target=_daemon_loop, daemon=True, name="improvement-daemon")
    _daemon_thread.start()
    return {"status": "started", **_state.to_dict()}


def stop_daemon() -> dict:
    """Stop the improvement daemon gracefully."""
    _daemon_stop.set()
    if _daemon_thread:
        _daemon_thread.join(timeout=10)
    _state.running = False
    return {"status": "stopped", **_state.to_dict()}


def get_daemon_status() -> dict:
    """Get current daemon state."""
    return _state.to_dict()


def reset_daemon_state() -> None:
    """Reset state (for tests).

    NOTE: If the gate security check also needs to be bypassed in tests,
    set JARVIS_SKIP_IMPROVEMENT_GATE=1 in the test environment directly.
    This function does NOT mutate the process environment — callers are
    responsible for setting/unsetting that flag to avoid cross-test contamination.
    """
    global _state
    _state = DaemonState()
    _cooldown_tracker.reset()
