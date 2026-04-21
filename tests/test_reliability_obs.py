"""tests/test_reliability_obs.py — Reliability + observability tests."""
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import types
if 'structlog' not in sys.modules:
    _sl = types.ModuleType('structlog')
    class _ML:
        def info(self, *a, **k): pass
        def debug(self, *a, **k): pass
        def warning(self, *a, **k): pass
        def error(self, *a, **k): pass
        def bind(self, **k): return self
    _sl.get_logger = lambda *a, **k: _ML()
    sys.modules['structlog'] = _sl


class TestMemoryEnforceLimits(unittest.TestCase):

    def test_enforce_no_excess(self):
        from core.memory.memory_schema import MemoryStore, MemoryEntry

        store = MemoryStore(db_path=":memory:")
        store.store(MemoryEntry(tier="SHORT_TERM", content="a"))
        result = store.enforce_limits()
        self.assertEqual(result["removed"], 0)

    def test_enforce_removes_excess(self):
        from core.memory.memory_schema import MemoryStore, MemoryEntry, TIER_DEFAULTS
        store = MemoryStore(db_path=":memory:")
        # Override limit for test
        old_limit = TIER_DEFAULTS["SHORT_TERM"]["max_entries"]
        TIER_DEFAULTS["SHORT_TERM"]["max_entries"] = 3
        try:
            for i in range(5):
                store.store(MemoryEntry(tier="SHORT_TERM", content=f"item-{i}"))
            result = store.enforce_limits()
            self.assertEqual(result["removed"], 2)
            self.assertEqual(result["by_tier"]["SHORT_TERM"]["count"], 3)
        finally:
            TIER_DEFAULTS["SHORT_TERM"]["max_entries"] = old_limit

    def test_enforce_preserves_other_tiers(self):
        from core.memory.memory_schema import MemoryStore, MemoryEntry, TIER_DEFAULTS
        store = MemoryStore(db_path=":memory:")
        TIER_DEFAULTS["SHORT_TERM"]["max_entries"] = 2
        try:
            store.store(MemoryEntry(tier="SHORT_TERM", content="a"))
            store.store(MemoryEntry(tier="SHORT_TERM", content="b"))
            store.store(MemoryEntry(tier="SHORT_TERM", content="c"))
            store.store(MemoryEntry(tier="LONG_TERM", content="permanent"))
            result = store.enforce_limits()
            self.assertEqual(result["by_tier"]["SHORT_TERM"]["removed"], 1)
            self.assertEqual(result["by_tier"]["LONG_TERM"]["removed"], 0)
        finally:
            TIER_DEFAULTS["SHORT_TERM"]["max_entries"] = 100


class TestProtectedPaths(unittest.TestCase):

    def test_env_protected(self):
        from core.self_improvement.protected_paths import PROTECTED_FILES
        self.assertIn(".env", PROTECTED_FILES)

    def test_docker_compose_protected(self):
        from core.self_improvement.protected_paths import PROTECTED_FILES
        self.assertIn("docker-compose.yml", PROTECTED_FILES)

    def test_settings_protected(self):
        from core.self_improvement.protected_paths import PROTECTED_FILES
        self.assertIn("config/settings.py", PROTECTED_FILES)

    def test_policy_engine_protected(self):
        from core.self_improvement.protected_paths import PROTECTED_FILES
        self.assertIn("core/policy/policy_engine.py", PROTECTED_FILES)

    def test_meta_orchestrator_protected(self):
        from core.self_improvement.protected_paths import PROTECTED_FILES
        self.assertIn("core/meta_orchestrator.py", PROTECTED_FILES)

    def test_minimum_protected_count(self):
        from core.self_improvement.protected_paths import PROTECTED_FILES
        self.assertGreaterEqual(len(PROTECTED_FILES), 20)


class TestCapabilityRegistryStats(unittest.TestCase):

    def test_stats_structure(self):
        from core.capabilities.registry import get_capability_registry
        r = get_capability_registry()
        stats = r.stats()
        self.assertIn("total", stats)
        self.assertIn("by_risk", stats)
        self.assertIn("requiring_approval", stats)

    def test_minimum_tools(self):
        from core.capabilities.registry import get_capability_registry
        r = get_capability_registry()
        self.assertGreaterEqual(r.stats()["total"], 16)


if __name__ == "__main__":
    unittest.main()
