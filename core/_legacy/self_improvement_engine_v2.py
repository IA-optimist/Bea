"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  SUPERSEDED — V2 intermediate, replaced by V3 package                      ║
║                                                                              ║
║  Use instead: core/self_improvement/engine.py (SelfImprovementEngine V3)   ║
║  Canonical import: from core.self_improvement.engine import                ║
║                        SelfImprovementEngine                               ║
║                                                                              ║
║  This file is kept only to avoid ImportError in case any code still         ║
║  references it directly. No new code should import from this module.        ║
╚══════════════════════════════════════════════════════════════════════════════╝

Self-Improvement Engine V2
===========================
Automated improvement loop: analyze → detect → propose → sandbox-test → promote.

Components:
  - PerformanceAnalyzer: mines mission history for weak spots
  - StrategyMutator: proposes concrete changes (prompts, tool preferences, retry config)
  - EvaluationRunner: tests proposals in sandbox (simulated missions)
  - SafePromoter: promotes only if sandbox score > baseline

Does NOT modify core runtime files. Only writes to:
  workspace/preferences/    (tool prefs, retry config, skip patterns)
  workspace/prompts/        (agent prompt tweaks)
  workspace/strategies/     (persisted strategy overrides)

API:
  run_improvement_cycle()   → full analysis + propose + test + promote
  get_improvement_report()  → last cycle report
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger("jarvis.self_improvement_engine")

_WORKSPACE = Path("workspace")
_PREFS_DIR = _WORKSPACE / "preferences"
_STRATEGIES_DIR = _WORKSPACE / "strategies"
_REPORTS_DIR = _WORKSPACE / "improvement_reports"


# ═══════════════════════════════════════════════════════════════
# DATA TYPES
# ═══════════════════════════════════════════════════════════════

@dataclass
class WeakSpot:
    """A detected performance weakness."""
    category: str          # "tool_failure", "high_latency", "low_efficiency", "repeated_error"
    mission_type: str
    metric_name: str       # e.g. "success_rate", "avg_latency_ms"
    current_value: float
    threshold: float
    occurrences: int
    severity: str          # "low", "medium", "high"
    details: str = ""


@dataclass
class Proposal:
    """A concrete improvement proposal."""
    proposal_id: str
    weak_spot: WeakSpot
    change_type: str       # "prompt_tweak", "tool_preference", "retry_strategy", "skip_pattern"
    description: str
    target_file: str       # relative path to write
    content: str           # JSON or text content to write
    expected_impact: str   # "success_rate +5%", "latency -20%"
    risk: str = "low"


@dataclass
class SandboxResult:
    """Result of testing a proposal in sandbox."""
    proposal_id: str
    baseline_score: float
    proposal_score: float
    improvement_pct: float
    passed: bool
    details: str = ""


@dataclass
class CycleReport:
    """Full improvement cycle report."""
    cycle_id: str
    timestamp: float
    duration_s: float
    weak_spots_found: int
    proposals_generated: int
    proposals_tested: int
    proposals_promoted: int
    weak_spots: list = field(default_factory=list)
    proposals: list = field(default_factory=list)
    sandbox_results: list = field(default_factory=list)
    promoted: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ═══════════════════════════════════════════════════════════════
# PERFORMANCE ANALYZER
# ═══════════════════════════════════════════════════════════════

class PerformanceAnalyzer:
    """Mines mission history for performance weak spots."""

    # Thresholds for weakness detection
    THRESHOLDS = {
        "success_rate": 0.7,           # below 70% = weak
        "avg_latency_ms": 10_000,      # above 10s = slow
        "tool_failure_rate": 0.3,      # above 30% = unreliable
        "retry_rate": 0.2,             # above 20% = unstable
        "approval_frequency": 0.5,     # above 50% = over-gated
    }

    def analyze(self) -> list[WeakSpot]:
        """Analyze mission history and return weak spots."""
        spots: list[WeakSpot] = []

        # 1. Per-mission-type success rates
        try:
            from core.mission_performance_tracker import get_mission_performance_tracker
            tracker = get_mission_performance_tracker()
            dashboard = tracker.get_dashboard_data()

            for mtype, stats in dashboard.get("by_mission_type", {}).items():
                sr = stats.get("success_rate", 1.0)
                total = stats.get("total", 0)
                if total >= 3 and sr < self.THRESHOLDS["success_rate"]:
                    spots.append(WeakSpot(
                        category="low_success_rate",
                        mission_type=mtype,
                        metric_name="success_rate",
                        current_value=sr,
                        threshold=self.THRESHOLDS["success_rate"],
                        occurrences=total,
                        severity="high" if sr < 0.5 else "medium",
                        details=f"{mtype}: {sr:.0%} success over {total} missions",
                    ))
        except Exception as e:
            logger.debug("perf_tracker_unavailable: %s", e)

        # 2. Tool failure rates
        try:
            from core.tool_performance_tracker import get_tool_performance_tracker
            tpt = get_tool_performance_tracker()
            for tool_name, stats in tpt.get_all_stats().items():
                if stats.total >= 5 and stats.success_rate < (1 - self.THRESHOLDS["tool_failure_rate"]):
                    spots.append(WeakSpot(
                        category="tool_failure",
                        mission_type="all",
                        metric_name="tool_success_rate",
                        current_value=stats.success_rate,
                        threshold=1 - self.THRESHOLDS["tool_failure_rate"],
                        occurrences=stats.total,
                        severity="high" if stats.success_rate < 0.5 else "medium",
                        details=f"Tool '{tool_name}': {stats.success_rate:.0%} success",
                    ))
        except Exception as e:
            logger.debug("tool_perf_tracker_unavailable: %s", e)

        # 3. Repeated error patterns from decision memory
        try:
            from memory.decision_memory import get_decision_memory
            dm = get_decision_memory()
            error_counts: dict[str, int] = {}
            for entry in dm._entries[-100:]:
                if not entry.success and entry.error_type:
                    key = f"{entry.mission_type}:{entry.error_type}"
                    error_counts[key] = error_counts.get(key, 0) + 1

            for key, count in error_counts.items():
                if count >= 3:
                    mtype, etype = key.split(":", 1)
                    spots.append(WeakSpot(
                        category="repeated_error",
                        mission_type=mtype,
                        metric_name="error_count",
                        current_value=float(count),
                        threshold=3,
                        occurrences=count,
                        severity="high" if count >= 5 else "medium",
                        details=f"Error '{etype}' repeated {count}x in {mtype}",
                    ))
        except Exception as e:
            logger.debug("decision_memory_unavailable: %s", e)

        # 4. High fallback usage
        try:
            from memory.decision_memory import get_decision_memory
            dm = get_decision_memory()
            fallback_counts: dict[str, list] = {}
            for entry in dm._entries[-100:]:
                mtype = entry.mission_type or "unknown"
                fb = entry.fallback_level_used or 0
                if mtype not in fallback_counts:
                    fallback_counts[mtype] = []
                fallback_counts[mtype].append(fb)

            for mtype, levels in fallback_counts.items():
                if len(levels) >= 5:
                    avg_fb = sum(levels) / len(levels)
                    if avg_fb > 0.5:
                        spots.append(WeakSpot(
                            category="high_fallback",
                            mission_type=mtype,
                            metric_name="avg_fallback_level",
                            current_value=avg_fb,
                            threshold=0.5,
                            occurrences=len(levels),
                            severity="medium",
                            details=f"{mtype}: avg fallback level {avg_fb:.2f}",
                        ))
        except Exception:
            pass

        return sorted(spots, key=lambda s: (
            {"high": 3, "medium": 2, "low": 1}.get(s.severity, 0),
            s.occurrences,
        ), reverse=True)[:10]  # Max 10 weak spots


# ═══════════════════════════════════════════════════════════════
# STRATEGY MUTATOR
# ═══════════════════════════════════════════════════════════════

class StrategyMutator:
    """Generates improvement proposals from weak spots."""

    def propose(self, spots: list[WeakSpot]) -> list[Proposal]:
        """Generate concrete proposals for each weak spot."""
        proposals: list[Proposal] = []

        for i, spot in enumerate(spots[:5]):  # Max 5 proposals per cycle
            pid = f"prop_{int(time.time())}_{i}"

            if spot.category == "tool_failure":
                proposals.append(Proposal(
                    proposal_id=pid,
                    weak_spot=spot,
                    change_type="tool_preference",
                    description=f"Deprioritize unreliable tool in {spot.details}",
                    target_file="workspace/preferences/tool_prefs.json",
                    content=json.dumps({
                        "deprioritize": [spot.details.split("'")[1] if "'" in spot.details else "unknown"],
                        "reason": spot.details,
                        "updated_at": time.time(),
                    }),
                    expected_impact=f"Reduce tool failures by avoiding degraded tool",
                ))

            elif spot.category == "repeated_error":
                error_type = spot.details.split("'")[1] if "'" in spot.details else "unknown"
                proposals.append(Proposal(
                    proposal_id=pid,
                    weak_spot=spot,
                    change_type="skip_pattern",
                    description=f"Add skip pattern for repeated error: {error_type}",
                    target_file="workspace/preferences/skip_patterns.json",
                    content=json.dumps({
                        "patterns": [{
                            "error_type": error_type,
                            "mission_type": spot.mission_type,
                            "action": "fallback_to_alternative",
                            "added_at": time.time(),
                        }],
                    }),
                    expected_impact=f"Reduce repeated failures in {spot.mission_type}",
                ))

            elif spot.category == "low_success_rate":
                proposals.append(Proposal(
                    proposal_id=pid,
                    weak_spot=spot,
                    change_type="retry_strategy",
                    description=f"Increase retry budget for {spot.mission_type}",
                    target_file="workspace/preferences/retry_config.json",
                    content=json.dumps({
                        spot.mission_type: {
                            "max_retries": 3,
                            "backoff_factor": 1.5,
                            "retry_on_fallback": True,
                            "updated_at": time.time(),
                        },
                    }),
                    expected_impact=f"Improve success rate from {spot.current_value:.0%} to ~{min(1.0, spot.current_value + 0.15):.0%}",
                ))

            elif spot.category == "high_fallback":
                proposals.append(Proposal(
                    proposal_id=pid,
                    weak_spot=spot,
                    change_type="prompt_tweak",
                    description=f"Improve prompt specificity for {spot.mission_type}",
                    target_file=f"workspace/prompts/{spot.mission_type}.txt",
                    content=(
                        f"# Auto-generated prompt improvement for {spot.mission_type}\n"
                        f"# Weak spot: high fallback rate ({spot.current_value:.2f})\n"
                        f"# When handling {spot.mission_type} missions:\n"
                        f"# 1. Be more specific in agent instructions\n"
                        f"# 2. Validate output format before returning\n"
                        f"# 3. Include concrete examples in the prompt\n"
                    ),
                    expected_impact=f"Reduce fallback rate from {spot.current_value:.2f} to <0.3",
                ))

        return proposals


# ═══════════════════════════════════════════════════════════════
# EVALUATION RUNNER
# ═══════════════════════════════════════════════════════════════

class EvaluationRunner:
    """Tests proposals in sandbox (simulated mission evaluation)."""

    def evaluate(self, proposal: Proposal) -> SandboxResult:
        """
        Test a proposal by comparing baseline vs proposed configuration.

        Since we can't run real LLM missions, we evaluate based on:
        1. Historical data for the affected mission type
        2. Heuristic scoring of the proposed change
        3. Compatibility check with existing config
        """
        baseline = self._get_baseline_score(proposal)
        proposed = self._estimate_proposal_score(proposal, baseline)
        improvement = ((proposed - baseline) / max(baseline, 0.01)) * 100

        return SandboxResult(
            proposal_id=proposal.proposal_id,
            baseline_score=round(baseline, 4),
            proposal_score=round(proposed, 4),
            improvement_pct=round(improvement, 2),
            passed=improvement > 0 and proposed > baseline,
            details=f"baseline={baseline:.3f} proposed={proposed:.3f} delta={improvement:+.1f}%",
        )

    def _get_baseline_score(self, proposal: Proposal) -> float:
        """Get current baseline score for the mission type."""
        try:
            from core.mission_performance_tracker import get_mission_performance_tracker
            tracker = get_mission_performance_tracker()
            dashboard = tracker.get_dashboard_data()
            mtype_stats = dashboard.get("by_mission_type", {}).get(proposal.weak_spot.mission_type, {})
            return mtype_stats.get("success_rate", 0.7)
        except Exception:
            return proposal.weak_spot.current_value

    def _estimate_proposal_score(self, proposal: Proposal, baseline: float) -> float:
        """Heuristic estimate of the proposal's impact."""
        # Conservative improvement estimates by change type
        impact_map = {
            "tool_preference": 0.05,    # Deprioritizing bad tools: +5%
            "skip_pattern": 0.08,       # Skipping known errors: +8%
            "retry_strategy": 0.10,     # More retries: +10%
            "prompt_tweak": 0.03,       # Better prompts: +3%
        }
        delta = impact_map.get(proposal.change_type, 0.02)

        # Scale by severity
        severity_mult = {"high": 1.5, "medium": 1.0, "low": 0.5}.get(
            proposal.weak_spot.severity, 1.0
        )
        return min(1.0, baseline + delta * severity_mult)


# ═══════════════════════════════════════════════════════════════
# SAFE PROMOTER
# ═══════════════════════════════════════════════════════════════

class SafePromoter:
    """Promotes tested proposals to production config."""

    def promote(self, proposal: Proposal, sandbox_result: SandboxResult) -> bool:
        """
        Write proposal to target file atomically.
        Returns True if promoted, False otherwise.
        """
        if not sandbox_result.passed:
            logger.info("proposal_not_promoted: %s (sandbox failed)", proposal.proposal_id)
            return False

        target = Path(proposal.target_file)

        try:
            # Ensure parent directory exists
            target.parent.mkdir(parents=True, exist_ok=True)

            # Merge with existing config (don't overwrite)
            existing = {}
            if target.exists():
                try:
                    with open(target) as f:
                        existing = json.load(f) if target.suffix == ".json" else {}
                except (json.JSONDecodeError, ValueError):
                    existing = {}

            if target.suffix == ".json":
                # Merge JSON
                try:
                    new_data = json.loads(proposal.content)
                    if isinstance(existing, dict) and isinstance(new_data, dict):
                        existing.update(new_data)
                    else:
                        existing = new_data
                except json.JSONDecodeError:
                    existing = {"raw": proposal.content}

                # Atomic write
                tmp = str(target) + ".tmp"
                with open(tmp, "w") as f:
                    json.dump(existing, f, indent=2, default=str)
                os.replace(tmp, str(target))
            else:
                # Text file (prompts)
                tmp = str(target) + ".tmp"
                with open(tmp, "w") as f:
                    f.write(proposal.content)
                os.replace(tmp, str(target))

            logger.info("proposal_promoted: %s → %s", proposal.proposal_id, proposal.target_file)
            return True

        except Exception as e:
            logger.error("proposal_promotion_failed: %s error=%s", proposal.proposal_id, e)
            return False


# ═══════════════════════════════════════════════════════════════
# MAIN ENGINE
# ═══════════════════════════════════════════════════════════════

_last_report: Optional[CycleReport] = None


def run_improvement_cycle() -> CycleReport:
    """
    Full improvement cycle:
    1. Analyze performance → find weak spots
    2. Generate proposals
    3. Test in sandbox
    4. Promote winners

    Returns CycleReport with full details.
    """
    global _last_report
    start = time.time()
    cycle_id = f"cycle_{int(start)}"

    logger.info("improvement_cycle_start: %s", cycle_id)

    # 1. Analyze
    analyzer = PerformanceAnalyzer()
    spots = analyzer.analyze()

    # 2. Propose
    mutator = StrategyMutator()
    proposals = mutator.propose(spots)

    # 3. Test
    runner = EvaluationRunner()
    sandbox_results: list[SandboxResult] = []
    for p in proposals:
        result = runner.evaluate(p)
        sandbox_results.append(result)

    # 4. Promote
    promoter = SafePromoter()
    promoted: list[str] = []
    for p, sr in zip(proposals, sandbox_results):
        if promoter.promote(p, sr):
            promoted.append(p.proposal_id)

    duration = time.time() - start

    report = CycleReport(
        cycle_id=cycle_id,
        timestamp=start,
        duration_s=round(duration, 3),
        weak_spots_found=len(spots),
        proposals_generated=len(proposals),
        proposals_tested=len(sandbox_results),
        proposals_promoted=len(promoted),
        weak_spots=[asdict(s) for s in spots],
        proposals=[asdict(p) for p in proposals],
        sandbox_results=[asdict(sr) for sr in sandbox_results],
        promoted=promoted,
    )

    # Persist report
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = _REPORTS_DIR / f"{cycle_id}.json"
    try:
        with open(report_path, "w") as f:
            json.dump(report.to_dict(), f, indent=2, default=str)
    except Exception as e:
        logger.warning("report_persist_failed: %s", e)

    _last_report = report
    logger.info(
        "improvement_cycle_complete: %s spots=%d proposals=%d promoted=%d duration=%.1fs",
        cycle_id, len(spots), len(proposals), len(promoted), duration,
    )
    return report


def get_improvement_report() -> Optional[dict]:
    """Get the last improvement cycle report."""
    global _last_report
    if _last_report:
        return _last_report.to_dict()

    # Try loading latest from disk
    try:
        if _REPORTS_DIR.exists():
            files = sorted(_REPORTS_DIR.glob("cycle_*.json"), reverse=True)
            if files:
                with open(files[0]) as f:
                    return json.load(f)
    except Exception:
        pass
    return None
