"""tests/test_skill_registry.py — Skill discovery and performance tracking tests."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class TestSkillPerformance:
    def test_score_new_skill(self):
        from core.skills.skill_discovery import SkillPerformance
        p = SkillPerformance(skill_id="test")
        assert p.score() > 0  # Default should give non-zero score

    def test_score_improves_with_success(self):
        from core.skills.skill_discovery import SkillPerformance
        p = SkillPerformance(skill_id="test")
        p.total_uses = 10
        p.successes = 9
        p.total_latency_ms = 1000  # 100ms avg
        p.total_cost_usd = 0.01
        assert p.score() > 0.7

    def test_score_degrades_with_failure(self):
        from core.skills.skill_discovery import SkillPerformance
        good = SkillPerformance(skill_id="good")
        good.total_uses = 10
        good.successes = 9
        good.total_latency_ms = 1000
        bad = SkillPerformance(skill_id="bad")
        bad.total_uses = 10
        bad.successes = 2
        bad.failures = 8
        bad.total_latency_ms = 5000
        assert bad.success_rate == 0.2
        assert bad.score() < good.score()  # Bad skill ranks lower

    def test_to_dict(self):
        from core.skills.skill_discovery import SkillPerformance
        p = SkillPerformance(skill_id="abc", total_uses=5, successes=4)
        d = p.to_dict()
        assert d["skill_id"] == "abc"
        assert d["success_rate"] == 0.8
        assert "score" in d


class TestSkillDiscovery:
    def test_import(self):
        from core.skills.skill_discovery import get_skill_discovery
        assert callable(get_skill_discovery)

    def test_record_use(self):
        from core.skills.skill_discovery import SkillDiscovery
        from core.skills.skill_registry import SkillRegistry
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            reg = SkillRegistry(path=path)
            sd = SkillDiscovery(registry=reg)
            sd.record_use("skill_1", success=True, latency_ms=100, cost_usd=0.01)
            p = sd.get_performance("skill_1")
            assert p is not None
            assert p.total_uses == 1
            assert p.successes == 1
        finally:
            os.unlink(path)

    def test_auto_disable(self):
        from core.skills.skill_discovery import SkillDiscovery, MIN_USES_FOR_DISABLE
        from core.skills.skill_registry import SkillRegistry
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            reg = SkillRegistry(path=path)
            sd = SkillDiscovery(registry=reg)
            # Record many failures
            for _ in range(MIN_USES_FOR_DISABLE + 1):
                sd.record_use("bad_skill", success=False, error="always fails")
            p = sd.get_performance("bad_skill")
            assert p.disabled is True
            assert "Auto-disabled" in p.disabled_reason
        finally:
            os.unlink(path)

    def test_is_enabled_unknown(self):
        from core.skills.skill_discovery import SkillDiscovery
        from core.skills.skill_registry import SkillRegistry
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            reg = SkillRegistry(path=path)
            sd = SkillDiscovery(registry=reg)
            assert sd.is_skill_enabled("nonexistent") is True
        finally:
            os.unlink(path)

    def test_ranked_skills(self):
        from core.skills.skill_discovery import SkillDiscovery
        from core.skills.skill_registry import SkillRegistry
        from core.skills.skill_models import Skill
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            reg = SkillRegistry(path=path)
            reg.add(Skill(name="good_skill", problem_type="test"))
            reg.add(Skill(name="bad_skill", problem_type="test"))
            sd = SkillDiscovery(registry=reg)
            for _ in range(5):
                sid = reg.all()[0].skill_id
                sd.record_use(sid, success=True, latency_ms=50)
            for _ in range(5):
                sid = reg.all()[1].skill_id
                sd.record_use(sid, success=False)
            ranked = sd.ranked_skills(limit=10)
            assert len(ranked) == 2
            assert ranked[0]["score"] > ranked[1]["score"]
        finally:
            os.unlink(path)

    def test_dashboard_stats(self):
        from core.skills.skill_discovery import SkillDiscovery
        from core.skills.skill_registry import SkillRegistry
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            reg = SkillRegistry(path=path)
            sd = SkillDiscovery(registry=reg)
            stats = sd.dashboard_stats()
            assert "total_skills" in stats
            assert "tracked" in stats
            assert "disabled" in stats
            assert "avg_score" in stats
        finally:
            os.unlink(path)

    def test_discover_from_mission(self):
        from core.skills.skill_discovery import SkillDiscovery
        from core.skills.skill_registry import SkillRegistry
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            reg = SkillRegistry(path=path)
            sd = SkillDiscovery(registry=reg)
            sid = sd.discover_from_mission(
                "m123", "Fix API endpoint",
                tools_used=["web_search", "file_write"],
                success=True,
            )
            assert sid is not None
            skill = reg.get(sid)
            assert skill.source_mission_id == "m123"
            assert skill.confidence == 0.4
        finally:
            os.unlink(path)

    def test_no_discover_on_failure(self):
        from core.skills.skill_discovery import SkillDiscovery
        from core.skills.skill_registry import SkillRegistry
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            reg = SkillRegistry(path=path)
            sd = SkillDiscovery(registry=reg)
            sid = sd.discover_from_mission("m456", "Fail", tools_used=[], success=False)
            assert sid is None
        finally:
            os.unlink(path)
