"""
tests/test_self_improvement_loop_v2.py — Strategy v2 promotion tests.

SV01-SV25: Strategy registry, auto-promotion, progressive selection.
"""
import time


class TestStrategyProfile:
    def test_SV01_profile_create(self):
        from core.execution.strategy_registry import StrategyProfile
        p = StrategyProfile(strategy_id="budget_lp", budget_mode="budget")
        assert p.strategy_id == "budget_lp"

    def test_SV02_profile_to_dict(self):
        from core.execution.strategy_registry import StrategyProfile
        p = StrategyProfile(strategy_id="x", is_default=True)
        d = p.to_dict()
        assert d["is_default"] is True

    def test_SV03_profile_from_dict(self):
        from core.execution.strategy_registry import StrategyProfile
        d = {"strategy_id": "y", "budget_mode": "critical", "is_default": True}
        p = StrategyProfile.from_dict(d)
        assert p.budget_mode == "critical"


class TestPromotionEvent:
    def test_SV04_event_create(self):
        from core.execution.strategy_registry import PromotionEvent
        e = PromotionEvent(
            task_type="lp", old_strategy="a", new_strategy="b",
            old_score=0.5, new_score=0.7, improvement=0.2, sample_count=10,
        )
        assert e.improvement == 0.2

    def test_SV05_event_to_dict(self):
        from core.execution.strategy_registry import PromotionEvent
        e = PromotionEvent("t", "a", "b", 0.5, 0.7, 0.2, 8)
        d = e.to_dict()
        assert d["task_type"] == "t"
        assert d["new_strategy"] == "b"


class TestStrategyRegistry:
    def _make_registry(self):
        from core.execution.strategy_memory import StrategyMemory
        from core.execution.strategy_registry import StrategyRegistry
        mem = StrategyMemory()
        reg = StrategyRegistry(memory=mem)
        return reg, mem

    def test_SV06_register_strategy(self):
        from core.execution.strategy_registry import StrategyProfile
        reg, _ = self._make_registry()
        reg.register_strategy("lp", StrategyProfile(strategy_id="a", is_default=True))
        assert reg.get_default("lp").strategy_id == "a"

    def test_SV07_get_strategies(self):
        from core.execution.strategy_registry import StrategyProfile
        reg, _ = self._make_registry()
        reg.register_strategy("lp", StrategyProfile(strategy_id="a"))
        reg.register_strategy("lp", StrategyProfile(strategy_id="b"))
        assert len(reg.get_strategies("lp")) == 2

    def test_SV08_no_default_returns_none(self):
        reg, _ = self._make_registry()
        assert reg.get_default("unknown") is None

    def test_SV09_no_promotion_without_data(self):
        reg, _ = self._make_registry()
        assert reg.check_promotion("lp") is None

    def test_SV10_no_promotion_insufficient_samples(self):
        from core.execution.strategy_memory import StrategyRecord
        reg, mem = self._make_registry()
        # Only 2 samples (below MIN_SAMPLES=5)
        for _ in range(2):
            mem.record(StrategyRecord(task_type="lp", strategy_id="a", success=True, quality_score=0.9))
        assert reg.check_promotion("lp") is None

    def test_SV11_no_promotion_same_default(self):
        from core.execution.strategy_memory import StrategyRecord
        from core.execution.strategy_registry import StrategyProfile
        reg, mem = self._make_registry()
        reg.register_strategy("lp", StrategyProfile(strategy_id="a", is_default=True))
        for _ in range(10):
            mem.record(StrategyRecord(task_type="lp", strategy_id="a", success=True, quality_score=0.9))
        assert reg.check_promotion("lp") is None

    def test_SV12_promotion_happens(self):
        """Core test: v2 beats v1 and gets promoted."""
        from core.execution.strategy_memory import StrategyRecord
        from core.execution.strategy_registry import StrategyProfile
        reg, mem = self._make_registry()
        reg.register_strategy("lp", StrategyProfile(strategy_id="v1", is_default=True))
        # v1: mediocre
        for _ in range(6):
            mem.record(StrategyRecord(task_type="lp", strategy_id="v1", success=True, quality_score=0.5))
        # v2: excellent
        for _ in range(6):
            mem.record(StrategyRecord(task_type="lp", strategy_id="v2", success=True, quality_score=0.95))
        event = reg.check_promotion("lp")
        assert event is not None
        assert event.new_strategy == "v2"
        assert event.old_strategy == "v1"
        assert reg.get_default("lp").strategy_id == "v2"

    def test_SV13_promotion_requires_min_improvement(self):
        from core.execution.strategy_memory import StrategyRecord
        from core.execution.strategy_registry import StrategyProfile
        reg, mem = self._make_registry()
        reg.register_strategy("lp", StrategyProfile(strategy_id="v1", is_default=True))
        # v1 and v2 are very close
        for _ in range(6):
            mem.record(StrategyRecord(task_type="lp", strategy_id="v1", success=True, quality_score=0.80))
        for _ in range(6):
            mem.record(StrategyRecord(task_type="lp", strategy_id="v2", success=True, quality_score=0.82))
        event = reg.check_promotion("lp")
        # Very small difference — shouldn't promote
        assert event is None

    def test_SV14_cooldown_prevents_rapid_promotion(self):
        from core.execution.strategy_memory import StrategyRecord
        from core.execution.strategy_registry import StrategyProfile
        import core.execution.strategy_registry as mod
        old_cd = mod.COOLDOWN_SECONDS
        mod.COOLDOWN_SECONDS = 99999
        try:
            reg, mem = self._make_registry()
            reg.register_strategy("lp", StrategyProfile(strategy_id="v1", is_default=True))
            for _ in range(6):
                mem.record(StrategyRecord(task_type="lp", strategy_id="v1", success=True, quality_score=0.5))
            for _ in range(6):
                mem.record(StrategyRecord(task_type="lp", strategy_id="v2", success=True, quality_score=0.95))
            # First promotion works
            reg._last_promotion["lp"] = time.time()
            # Cooldown blocks second check
            event = reg.check_promotion("lp")
            assert event is None
        finally:
            mod.COOLDOWN_SECONDS = old_cd

    def test_SV15_check_all_promotions(self):
        from core.execution.strategy_memory import StrategyRecord
        from core.execution.strategy_registry import StrategyProfile
        reg, mem = self._make_registry()
        reg.register_strategy("a", StrategyProfile(strategy_id="old_a", is_default=True))
        reg.register_strategy("b", StrategyProfile(strategy_id="old_b", is_default=True))
        for _ in range(6):
            mem.record(StrategyRecord(task_type="a", strategy_id="old_a", success=True, quality_score=0.4))
            mem.record(StrategyRecord(task_type="a", strategy_id="new_a", success=True, quality_score=0.9))
            mem.record(StrategyRecord(task_type="b", strategy_id="old_b", success=True, quality_score=0.4))
            mem.record(StrategyRecord(task_type="b", strategy_id="new_b", success=True, quality_score=0.9))
        events = reg.check_all_promotions()
        assert len(events) == 2


class TestProgressiveSelection:
    """The system progressively selects better strategies over time."""

    def test_SV16_empty_memory_returns_no_best(self):
        from core.execution.strategy_memory import StrategyMemory
        mem = StrategyMemory()
        assert mem.get_best_strategy("any") is None

    def test_SV17_single_strategy_becomes_best(self):
        from core.execution.strategy_memory import StrategyMemory, StrategyRecord
        mem = StrategyMemory()
        for _ in range(5):
            mem.record(StrategyRecord(task_type="lp", strategy_id="only_one", success=True, quality_score=0.7))
        assert mem.get_best_strategy("lp") == "only_one"

    def test_SV18_better_strategy_overtakes(self):
        from core.execution.strategy_memory import StrategyMemory, StrategyRecord
        mem = StrategyMemory()
        # Strategy A: ok
        for _ in range(10):
            mem.record(StrategyRecord(task_type="lp", strategy_id="A", success=True, quality_score=0.6))
        assert mem.get_best_strategy("lp") == "A"
        # Strategy B: better — overtakes
        for _ in range(10):
            mem.record(StrategyRecord(task_type="lp", strategy_id="B", success=True, quality_score=0.9))
        assert mem.get_best_strategy("lp") == "B"

    def test_SV19_failing_strategy_drops(self):
        from core.execution.strategy_memory import StrategyMemory, StrategyRecord
        mem = StrategyMemory()
        for _ in range(5):
            mem.record(StrategyRecord(task_type="lp", strategy_id="reliable", success=True, quality_score=0.7))
        for _ in range(5):
            mem.record(StrategyRecord(task_type="lp", strategy_id="unreliable", success=False, quality_score=0.1))
        assert mem.get_best_strategy("lp") == "reliable"

    def test_SV20_cost_efficient_preferred_equal_quality(self):
        from core.execution.strategy_memory import StrategyMemory, StrategyRecord
        mem = StrategyMemory()
        for _ in range(5):
            mem.record(StrategyRecord(task_type="lp", strategy_id="cheap", success=True, quality_score=0.8, cost_estimate=0.001))
        for _ in range(5):
            mem.record(StrategyRecord(task_type="lp", strategy_id="expensive", success=True, quality_score=0.8, cost_estimate=0.1))
        assert mem.get_best_strategy("lp") == "cheap"


class TestPersistence:
    def test_SV21_registry_persistence(self, tmp_path):
        from core.execution.strategy_memory import StrategyMemory
        from core.execution.strategy_registry import StrategyRegistry, StrategyProfile
        p = tmp_path / "registry.json"
        mem = StrategyMemory()
        reg = StrategyRegistry(memory=mem, persist_path=p)
        reg.register_strategy("lp", StrategyProfile(strategy_id="a", is_default=True))
        assert p.exists()

        reg2 = StrategyRegistry(memory=mem, persist_path=p)
        assert reg2.get_default("lp").strategy_id == "a"

    def test_SV22_promotion_history_persists(self, tmp_path):
        from core.execution.strategy_memory import StrategyMemory, StrategyRecord
        from core.execution.strategy_registry import StrategyRegistry, StrategyProfile
        p = tmp_path / "reg.json"
        mem = StrategyMemory()
        reg = StrategyRegistry(memory=mem, persist_path=p)
        reg.register_strategy("lp", StrategyProfile(strategy_id="v1", is_default=True))
        for _ in range(6):
            mem.record(StrategyRecord(task_type="lp", strategy_id="v1", success=True, quality_score=0.4))
            mem.record(StrategyRecord(task_type="lp", strategy_id="v2", success=True, quality_score=0.95))
        reg.check_promotion("lp")

        reg2 = StrategyRegistry(memory=mem, persist_path=p)
        assert len(reg2.get_promotion_history()) >= 1


class TestIntegration:
    def test_SV23_registry_status(self):
        from core.execution.strategy_registry import StrategyRegistry, StrategyProfile
        from core.execution.strategy_memory import StrategyMemory
        reg = StrategyRegistry(memory=StrategyMemory())
        reg.register_strategy("a", StrategyProfile(strategy_id="s1", is_default=True))
        s = reg.get_status()
        assert s["task_types"] >= 1
        assert s["defaults_set"] >= 1

    def test_SV24_singleton(self):
        from core.execution.strategy_registry import get_strategy_registry
        r1 = get_strategy_registry()
        r2 = get_strategy_registry()
        assert r1 is r2

    def test_SV25_all_defaults_dict(self):
        from core.execution.strategy_registry import StrategyRegistry, StrategyProfile
        from core.execution.strategy_memory import StrategyMemory
        reg = StrategyRegistry(memory=StrategyMemory())
        reg.register_strategy("lp", StrategyProfile(strategy_id="s1", is_default=True))
        reg.register_strategy("api", StrategyProfile(strategy_id="s2", is_default=True))
        defaults = reg.get_all_defaults()
        assert "lp" in defaults
        assert "api" in defaults
