"""
tests/test_strategy_memory.py — Strategy comparison + learning tests.

SM01-SM15: StrategyRecord, StrategyComparison, StrategyMemory, persistence
"""


class TestStrategyRecord:
    def test_SM01_create_record(self):
        from core.execution.strategy_memory import StrategyRecord
        r = StrategyRecord(task_type="landing_page", strategy_id="budget_sonnet")
        assert r.task_type == "landing_page"
        assert r.timestamp > 0

    def test_SM02_record_to_dict(self):
        from core.execution.strategy_memory import StrategyRecord
        r = StrategyRecord(
            task_type="api_service", strategy_id="critical_opus",
            success=True, quality_score=0.85, cost_estimate=0.02,
        )
        d = r.to_dict()
        assert d["success"] is True
        assert d["quality_score"] == 0.85

    def test_SM03_model_truncated(self):
        from core.execution.strategy_memory import StrategyRecord
        r = StrategyRecord(model_used="x" * 100)
        d = r.to_dict()
        assert len(d["model_used"]) <= 50


class TestStrategyComparison:
    def test_SM04_empty_comparison(self):
        from core.execution.strategy_memory import StrategyMemory
        m = StrategyMemory()
        c = m.compare("nonexistent")
        assert c.sample_count == 0
        assert c.best_strategy == ""

    def test_SM05_single_strategy(self):
        from core.execution.strategy_memory import StrategyMemory, StrategyRecord
        m = StrategyMemory()
        m.record(StrategyRecord(task_type="test", strategy_id="a", success=True, quality_score=0.8))
        c = m.compare("test")
        assert c.best_strategy == "a"
        assert c.sample_count == 1

    def test_SM06_best_strategy_wins(self):
        from core.execution.strategy_memory import StrategyMemory, StrategyRecord
        m = StrategyMemory()
        for _ in range(5):
            m.record(StrategyRecord(task_type="lp", strategy_id="good", success=True, quality_score=0.9))
        for _ in range(5):
            m.record(StrategyRecord(task_type="lp", strategy_id="bad", success=False, quality_score=0.2))
        c = m.compare("lp")
        assert c.best_strategy == "good"
        assert c.best_score > 0.5

    def test_SM07_comparison_to_dict(self):
        from core.execution.strategy_memory import StrategyComparison
        c = StrategyComparison(task_type="test", best_strategy="a", best_score=0.8, sample_count=10)
        d = c.to_dict()
        assert d["task_type"] == "test"
        assert d["best_strategy"] == "a"


class TestStrategyMemory:
    def test_SM08_record_and_retrieve(self):
        from core.execution.strategy_memory import StrategyMemory, StrategyRecord
        m = StrategyMemory()
        m.record(StrategyRecord(task_type="test", strategy_id="a"))
        records = m.get_records(task_type="test")
        assert len(records) == 1

    def test_SM09_max_records_bounded(self):
        from core.execution.strategy_memory import StrategyMemory, StrategyRecord
        m = StrategyMemory()
        for i in range(600):
            m.record(StrategyRecord(task_type="test", strategy_id=f"s{i}"))
        assert len(m._records) <= m.MAX_RECORDS

    def test_SM10_get_best_strategy(self):
        from core.execution.strategy_memory import StrategyMemory, StrategyRecord
        m = StrategyMemory()
        m.record(StrategyRecord(task_type="lp", strategy_id="winner", success=True, quality_score=0.95))
        assert m.get_best_strategy("lp") == "winner"

    def test_SM11_get_best_unknown_returns_none(self):
        from core.execution.strategy_memory import StrategyMemory
        m = StrategyMemory()
        assert m.get_best_strategy("unknown") is None

    def test_SM12_all_comparisons(self):
        from core.execution.strategy_memory import StrategyMemory, StrategyRecord
        m = StrategyMemory()
        m.record(StrategyRecord(task_type="a", strategy_id="s1"))
        m.record(StrategyRecord(task_type="b", strategy_id="s2"))
        comps = m.get_all_comparisons()
        assert len(comps) == 2

    def test_SM13_persistence(self, tmp_path):
        from core.execution.strategy_memory import StrategyMemory, StrategyRecord
        p = tmp_path / "strategy.json"
        m = StrategyMemory(persist_path=p)
        m.record(StrategyRecord(task_type="test", strategy_id="a", success=True))
        assert p.exists()

        m2 = StrategyMemory(persist_path=p)
        m2.load()
        assert len(m2._records) == 1
        assert m2._records[0].task_type == "test"

    def test_SM14_cost_efficiency_matters(self):
        from core.execution.strategy_memory import StrategyMemory, StrategyRecord
        m = StrategyMemory()
        # Same quality, one cheap, one expensive
        for _ in range(5):
            m.record(StrategyRecord(task_type="t", strategy_id="cheap", success=True, quality_score=0.8, cost_estimate=0.001))
        for _ in range(5):
            m.record(StrategyRecord(task_type="t", strategy_id="expensive", success=True, quality_score=0.8, cost_estimate=0.1))
        c = m.compare("t")
        # Cheap should score higher due to cost efficiency
        strats = {s["strategy_id"]: s["composite_score"] for s in c.strategies}
        assert strats["cheap"] >= strats["expensive"]

    def test_SM15_singleton(self):
        from core.execution.strategy_memory import get_strategy_memory
        m1 = get_strategy_memory()
        m2 = get_strategy_memory()
        assert m1 is m2
