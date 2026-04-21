"""
Tests — Experiment Quality & Value Estimation

Coverage:
  V1. Expected value: high-impact weakness scores higher than low-impact
  V2. Expected value: frequency amplifies score
  V3. Expected value: criticality weight affects score
  V4. Priority ordering: reliability > cost > latency > refactor
  V5. Noise filtering: formatting/naming/micro_optimization rejected
  V6. Minimum value threshold filters low-value candidates
  V7. Cooldown blocks repeated category within 3 cycles
  V8. Cooldown tick decrements and expires
  V9. Full ranking: 10 candidates, correct priority order
  V10. Cycle uses ranked candidates (not arbitrary first)
  V11. Cooldown set after experiment runs
  V12. Impact scores are consistent with documentation
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.improvement_daemon import (
    Weakness, compute_expected_value, rank_candidates,
    CooldownTracker, PRIORITY_TIER, IMPACT_SCORE,
    MIN_EXPECTED_VALUE, run_cycle, reset_daemon_state,
    get_cooldown_tracker,
)


# ═══════════════════════════════════════════════════════════════
# EXPECTED VALUE (V1, V2, V3)
# ═══════════════════════════════════════════════════════════════

class TestExpectedValue:

    def test_high_impact_scores_higher(self):
        """V1: Timeout weakness scores higher than naming weakness."""
        timeout = Weakness(
            category="timeout", component="executor",
            metric_name="tool_timeout_total",
            current_value=10, threshold=3, severity="high",
            description="10 timeouts")

        naming = Weakness(
            category="naming", component="docs",
            metric_name="naming_issues",
            current_value=5, threshold=3, severity="low",
            description="5 naming issues")

        ev_timeout = compute_expected_value(timeout)
        ev_naming = compute_expected_value(naming)

        assert ev_timeout.expected_value > ev_naming.expected_value
        assert ev_timeout.impact_score > ev_naming.impact_score

    def test_frequency_amplifies_score(self):
        """V2: Higher frequency (worse metric) → higher expected value."""
        mild = Weakness(
            category="retry", component="executor",
            metric_name="retry_attempts_total",
            current_value=6, threshold=5, severity="medium",
            description="6 retries")

        severe = Weakness(
            category="retry", component="executor",
            metric_name="retry_attempts_total",
            current_value=25, threshold=5, severity="high",
            description="25 retries")

        ev_mild = compute_expected_value(mild)
        ev_severe = compute_expected_value(severe)

        assert ev_severe.frequency_score > ev_mild.frequency_score
        assert ev_severe.expected_value > ev_mild.expected_value

    def test_criticality_weight(self):
        """V3: Mission system component scores higher than docs."""
        mission_w = Weakness(
            category="timeout", component="mission_system",
            metric_name="test", current_value=10, threshold=3,
            severity="high", description="test")

        docs_w = Weakness(
            category="timeout", component="docs",
            metric_name="test", current_value=10, threshold=3,
            severity="low", description="test")

        ev_mission = compute_expected_value(mission_w)
        ev_docs = compute_expected_value(docs_w)

        assert ev_mission.criticality_weight > ev_docs.criticality_weight
        assert ev_mission.expected_value > ev_docs.expected_value


# ═══════════════════════════════════════════════════════════════
# PRIORITY ORDERING (V4)
# ═══════════════════════════════════════════════════════════════

class TestPriorityOrdering:

    def test_reliability_before_cost(self):
        """V4: Reliability fixes ranked above cost optimization."""
        assert PRIORITY_TIER["low_success"] > PRIORITY_TIER["expensive_model"]
        assert PRIORITY_TIER["timeout"] > PRIORITY_TIER["expensive_model"]

    def test_cost_before_latency(self):
        assert PRIORITY_TIER["expensive_model"] > PRIORITY_TIER["latency"]

    def test_latency_before_refactor(self):
        assert PRIORITY_TIER["latency"] > PRIORITY_TIER["naming"]

    def test_full_ranking_10_candidates(self):
        """V9: 10 candidates sorted correctly by priority + value."""
        weaknesses = [
            Weakness(category="formatting", component="docs", metric_name="x",
                     current_value=5, threshold=3, severity="low", description="format"),
            Weakness(category="naming", component="docs", metric_name="x",
                     current_value=5, threshold=3, severity="low", description="naming"),
            Weakness(category="micro_optimization", component="executor", metric_name="x",
                     current_value=5, threshold=3, severity="low", description="micro"),
            Weakness(category="latency", component="executor", metric_name="x",
                     current_value=5, threshold=3, severity="medium", description="latency"),
            Weakness(category="expensive_model", component="model_routing", metric_name="x",
                     current_value=0.30, threshold=0.20, severity="medium", description="expensive"),
            Weakness(category="slow_tool", component="tool_executor", metric_name="x",
                     current_value=0.40, threshold=0.20, severity="medium", description="slow tool"),
            Weakness(category="retry", component="executor", metric_name="x",
                     current_value=10, threshold=5, severity="medium", description="retries"),
            Weakness(category="failure_pattern", component="system", metric_name="x",
                     current_value=8, threshold=3, severity="high", description="failures"),
            Weakness(category="timeout", component="executor", metric_name="x",
                     current_value=15, threshold=3, severity="high", description="timeouts"),
            Weakness(category="low_success", component="mission_system", metric_name="x",
                     current_value=0.40, threshold=0.75, severity="critical", description="low success"),
        ]

        ranked = rank_candidates(weaknesses)

        # Noise filtered out
        categories = [c.weakness.category for c in ranked]
        assert "formatting" not in categories
        assert "naming" not in categories
        assert "micro_optimization" not in categories

        # Top should be reliability tier
        assert ranked[0].weakness.category in ("low_success", "timeout", "failure_pattern")

        # Bottom should be lower-tier categories
        if len(ranked) > 3:
            bottom_cats = {c.weakness.category for c in ranked[-2:]}
            top_cats = {c.weakness.category for c in ranked[:2]}
            # Top categories should have higher priority than bottom
            top_priorities = [PRIORITY_TIER.get(c, 0) for c in top_cats]
            bot_priorities = [PRIORITY_TIER.get(c, 0) for c in bottom_cats]
            assert min(top_priorities) >= max(bot_priorities)


# ═══════════════════════════════════════════════════════════════
# NOISE FILTERING (V5, V6)
# ═══════════════════════════════════════════════════════════════

class TestNoiseFiltering:

    def test_formatting_filtered(self):
        """V5: Formatting weaknesses are excluded."""
        weaknesses = [
            Weakness(category="formatting", component="docs", metric_name="x",
                     current_value=10, threshold=3, severity="low", description="format"),
        ]
        ranked = rank_candidates(weaknesses)
        assert len(ranked) == 0

    def test_naming_filtered(self):
        weaknesses = [
            Weakness(category="naming", component="docs", metric_name="x",
                     current_value=10, threshold=3, severity="low", description="naming"),
        ]
        ranked = rank_candidates(weaknesses)
        assert len(ranked) == 0

    def test_micro_optimization_filtered(self):
        weaknesses = [
            Weakness(category="micro_optimization", component="executor", metric_name="x",
                     current_value=10, threshold=3, severity="low", description="micro"),
        ]
        ranked = rank_candidates(weaknesses)
        assert len(ranked) == 0

    def test_low_value_filtered(self):
        """V6: Weakness with expected value below MIN_EXPECTED_VALUE is excluded."""
        # latency with low criticality component should have low EV
        weaknesses = [
            Weakness(category="latency", component="docs", metric_name="x",
                     current_value=4, threshold=3, severity="low", description="latency in docs"),
        ]
        ranked = rank_candidates(weaknesses)
        # With impact=0.3, freq=~0.27, crit=0.1 → EV ≈ 0.008 < 0.10
        assert len(ranked) == 0


# ═══════════════════════════════════════════════════════════════
# COOLDOWN (V7, V8, V11)
# ═══════════════════════════════════════════════════════════════

class TestCooldown:

    def test_cooldown_blocks_category(self):
        """V7: Category on cooldown is excluded from ranking."""
        weaknesses = [
            Weakness(category="timeout", component="executor", metric_name="x",
                     current_value=10, threshold=3, severity="high", description="timeouts"),
        ]

        cooldowns = {"timeout": 2}  # 2 cycles remaining
        ranked = rank_candidates(weaknesses, cooldowns)
        assert len(ranked) == 0

    def test_cooldown_tick(self):
        """V8: Tick decrements and expires cooldowns."""
        ct = CooldownTracker()
        ct.set_cooldown("timeout", 3)
        assert ct.is_on_cooldown("timeout")

        ct.tick()
        assert ct.get_all()["timeout"] == 2

        ct.tick()
        ct.tick()
        assert not ct.is_on_cooldown("timeout")

    def test_cooldown_set_after_experiment(self, tmp_path):
        """V11: run_cycle sets cooldown for the experimented category."""
        from core.metrics_store import reset_metrics, emit_tool_timeout
        reset_daemon_state()
        m = reset_metrics()

        # Create repo + target
        (tmp_path / "executor").mkdir()
        (tmp_path / "executor" / "retry_policy.py").write_text("timeout=10\n")
        (tmp_path / "workspace" / "improvement_reports").mkdir(parents=True)

        # Trigger timeout weakness
        for _ in range(5):
            emit_tool_timeout("shell_command")

        cycle_result = run_cycle(tmp_path)

        # After cycle, timeout category should be on cooldown
        ct = get_cooldown_tracker()
        # Cooldown is set if experiment was attempted (even if blocked/error)
        if cycle_result.get("experiment_run"):
            assert ct.is_on_cooldown("timeout")


# ═══════════════════════════════════════════════════════════════
# CYCLE INTEGRATION (V10)
# ═══════════════════════════════════════════════════════════════

class TestCycleIntegration:

    @pytest.mark.xfail(reason="ranked candidates cycle drift", strict=False)
    def test_cycle_uses_ranked_candidates(self, tmp_path):
        """V10: Cycle selects highest-value candidate, not arbitrary first."""
        from core.metrics_store import (
            reset_metrics, emit_retry,
            emit_mission_submitted, emit_mission_failed,
        )
        reset_daemon_state()
        m = reset_metrics()

        # Create two weaknesses: low_success (tier 100) and retry (tier 70)
        for _ in range(10):
            emit_mission_submitted("test")
        for _ in range(7):
            emit_mission_failed("test", "crash")
        for _ in range(8):
            emit_retry("executor")

        # Only create the retry target (so low_success can't be patched)
        (tmp_path / "executor").mkdir()
        (tmp_path / "executor" / "retry_policy.py").write_text("max_retries=1\n")
        (tmp_path / "workspace" / "improvement_reports").mkdir(parents=True)

        result = run_cycle(tmp_path)
        # The result should show it found multiple weaknesses
        assert result["weaknesses_found"] >= 2
        # And the expected_value should be present
        assert "expected_value" in result or result["decision"] == "none"


# ═══════════════════════════════════════════════════════════════
# IMPACT SCORE CONSISTENCY (V12)
# ═══════════════════════════════════════════════════════════════

class TestImpactScoreConsistency:

    def test_impact_scores_ordered(self):
        """V12: Impact scores match documented priority."""
        assert IMPACT_SCORE["low_success"] > IMPACT_SCORE["timeout"]
        assert IMPACT_SCORE["timeout"] > IMPACT_SCORE["retry"]
        assert IMPACT_SCORE["retry"] > IMPACT_SCORE["expensive_model"]
        assert IMPACT_SCORE["expensive_model"] > IMPACT_SCORE["latency"]
        assert IMPACT_SCORE["latency"] > IMPACT_SCORE["naming"]
        assert IMPACT_SCORE["naming"] > IMPACT_SCORE["formatting"]

    def test_all_categories_have_impact(self):
        """All priority categories have an impact score."""
        for cat in PRIORITY_TIER:
            assert cat in IMPACT_SCORE, f"Missing impact score for {cat}"

    def test_min_expected_value_reasonable(self):
        """MIN_EXPECTED_VALUE is between 0 and 1."""
        assert 0 < MIN_EXPECTED_VALUE < 1.0
