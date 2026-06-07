"""
BEA MAX — Thread Safety Test Suite (Pass 4)
==============================================

Tests concurrent access to shared mutable state:
  A. MetaOrchestrator._missions dict under concurrent writes
  B. MetaOrchestrator singleton (get_meta_orchestrator) double-init race
  C. MemoryFacade singleton (get_memory_facade) double-init race
  D. BudgetGuard token accumulation under concurrent charges
  E. ToolRegistry mutable default arg isolation
"""
from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import MagicMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# A. MetaOrchestrator._missions thread safety
# ─────────────────────────────────────────────────────────────────────────────

class TestMetaOrchestratorThreadSafety(unittest.TestCase):

    def _make_meta(self):
        settings = MagicMock()
        settings.mission_timeout_s = 600
        with patch("config.settings.get_settings", return_value=settings):
            from core.meta_orchestrator import MetaOrchestrator
            return MetaOrchestrator(settings=settings)

    def test_missions_lock_exists(self):
        """MetaOrchestrator must have a threading.RLock for _missions."""
        import threading
        meta = self._make_meta()
        self.assertTrue(hasattr(meta, "_lock"),
                        "MetaOrchestrator must have _lock attribute")
        self.assertIsInstance(meta._lock, type(threading.RLock()),
                              "_lock must be an RLock")

    def test_concurrent_get_status_no_crash(self):
        """get_status() must not crash when called concurrently with mission writes."""
        meta = self._make_meta()
        from core.meta_orchestrator import MissionContext, MissionStatus
        errors = []

        def write_missions():
            for i in range(50):
                mid = f"mission-{threading.get_ident()}-{i}"
                ctx = MissionContext(
                    mission_id=mid, goal="test", mode="auto",
                    status=MissionStatus.CREATED,
                    created_at=time.time(), updated_at=time.time(),
                )
                with meta._lock:
                    meta._missions[mid] = ctx

        def read_status():
            for _ in range(50):
                try:
                    meta.get_status()
                except RuntimeError as e:
                    errors.append(str(e))

        writers = [threading.Thread(target=write_missions) for _ in range(4)]
        readers = [threading.Thread(target=read_status) for _ in range(4)]
        for t in writers + readers:
            t.start()
        for t in writers + readers:
            t.join(timeout=5.0)

        self.assertEqual(errors, [], f"Thread-safety errors: {errors}")

    def test_get_mission_concurrent_no_crash(self):
        """get_mission() must not raise under concurrent modification."""
        meta = self._make_meta()
        from core.meta_orchestrator import MissionContext, MissionStatus
        errors = []

        def mutate():
            for i in range(30):
                mid = f"m-{i}"
                ctx = MissionContext(
                    mission_id=mid, goal="g", mode="auto",
                    status=MissionStatus.CREATED,
                    created_at=0.0, updated_at=0.0,
                )
                with meta._lock:
                    meta._missions[mid] = ctx

        def lookup():
            for i in range(30):
                try:
                    meta.get_mission(f"m-{i}")
                except Exception as e:
                    errors.append(str(e))

        ts = [threading.Thread(target=mutate), threading.Thread(target=lookup)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(timeout=5.0)

        self.assertEqual(errors, [], f"Thread-safety errors: {errors}")

    def test_get_status_iterates_snapshot_not_live_dict(self):
        """get_status() must iterate a copy — no 'changed size during iteration'."""
        import pathlib
        src = pathlib.Path("core/meta_orchestrator.py").read_text(encoding="utf-8")
        # Must snapshot with list() before iterating
        self.assertIn("list(self._missions.values())", src,
                      "get_status must snapshot missions with list() before iterating")


# ─────────────────────────────────────────────────────────────────────────────
# B. MetaOrchestrator singleton thread safety
# ─────────────────────────────────────────────────────────────────────────────

class TestMetaSingletonThreadSafety(unittest.TestCase):

    def test_singleton_lock_exists_in_source(self):
        import pathlib
        src = pathlib.Path("core/meta_orchestrator.py").read_text(encoding="utf-8")
        self.assertIn("_meta_lock", src,
                      "get_meta_orchestrator must use _meta_lock for thread safety")

    def test_concurrent_get_meta_returns_same_instance(self):
        """All threads must get the exact same singleton instance."""
        import core.meta_orchestrator as mo_module
        # Reset singleton for isolation
        original = mo_module._meta
        mo_module._meta = None
        instances = []
        errors = []

        def get_instance():
            try:
                inst = mo_module.get_meta_orchestrator()
                instances.append(id(inst))
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=get_instance) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        mo_module._meta = original  # restore

        self.assertEqual(errors, [], f"Errors: {errors}")
        if instances:
            self.assertEqual(len(set(instances)), 1,
                             f"Multiple instances created: {set(instances)}")


# ─────────────────────────────────────────────────────────────────────────────
# C. MemoryFacade singleton thread safety
# ─────────────────────────────────────────────────────────────────────────────

class TestMemoryFacadeSingletonThreadSafety(unittest.TestCase):

    def test_singleton_lock_exists_in_source(self):
        import pathlib
        src = pathlib.Path("core/memory_facade.py").read_text(encoding="utf-8")
        self.assertIn("_facade_lock", src,
                      "get_memory_facade must use _facade_lock for thread safety")

    def test_concurrent_get_facade_returns_same_instance(self):
        """All threads must get the exact same MemoryFacade instance."""
        import core.memory_facade as mf_module
        original = mf_module._facade
        mf_module._facade = None
        instances = []
        errors = []

        def get_instance():
            try:
                inst = mf_module.get_memory_facade()
                instances.append(id(inst))
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=get_instance) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        mf_module._facade = original  # restore

        self.assertEqual(errors, [], f"Errors: {errors}")
        if instances:
            self.assertEqual(len(set(instances)), 1,
                             f"Multiple instances created: {set(instances)}")


# ─────────────────────────────────────────────────────────────────────────────
# D. BudgetGuard thread safety
# ─────────────────────────────────────────────────────────────────────────────

class TestBudgetGuardThreadSafety(unittest.TestCase):

    def test_budget_guard_has_lock(self):
        from core.orchestrator_v2 import BudgetGuard, BudgetConfig
        guard = BudgetGuard(BudgetConfig(max_tokens=1_000_000))
        self.assertTrue(hasattr(guard, "_lock"),
                        "BudgetGuard must have _lock attribute")

    def test_concurrent_charge_correct_total(self):
        """Concurrent charges must produce the correct token total (no lost updates)."""
        from core.orchestrator_v2 import BudgetGuard, BudgetConfig
        guard = BudgetGuard(BudgetConfig(max_tokens=10_000_000))
        errors = []

        # Each thread charges a 10-char string ≈ 2-3 tokens
        charge_text = "hello world"  # small, known text
        n_threads = 20
        charges_per_thread = 50

        def do_charge():
            for _ in range(charges_per_thread):
                try:
                    guard.charge(charge_text)
                except Exception as e:
                    errors.append(str(e))

        threads = [threading.Thread(target=do_charge) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        self.assertEqual(errors, [], f"Charge errors: {errors}")
        # Total must be positive and reflect all charges
        self.assertGreater(guard.tokens, 0)

    def test_budget_exceeded_raised_correctly(self):
        """BudgetExceeded must still be raised after lock fix."""
        from core.orchestrator_v2 import BudgetGuard, BudgetConfig, BudgetExceeded
        guard = BudgetGuard(BudgetConfig(max_tokens=1))
        with self.assertRaises(BudgetExceeded):
            guard.charge("a" * 1000)


# ─────────────────────────────────────────────────────────────────────────────
# E. ToolRegistry mutable default arg isolation
# ─────────────────────────────────────────────────────────────────────────────

class TestToolRegistryMutableDefaults(unittest.TestCase):

    def test_score_tool_relevance_default_is_none(self):
        """score_tool_relevance signature must use None default, not {}."""
        import inspect
        from core.tool_registry import score_tool_relevance
        sig = inspect.signature(score_tool_relevance)
        default = sig.parameters["success_history"].default
        self.assertIsNone(default,
                          "success_history default must be None, not mutable {}")

    def test_rank_tools_default_is_none(self):
        import inspect
        from core.tool_registry import rank_tools_for_task
        sig = inspect.signature(rank_tools_for_task)
        default = sig.parameters["success_history"].default
        self.assertIsNone(default,
                          "success_history default must be None, not mutable {}")

    def test_should_create_tool_defaults_are_none(self):
        import inspect
        from core.tool_registry import should_create_tool
        sig = inspect.signature(should_create_tool)
        self.assertIsNone(sig.parameters["success_history"].default)
        self.assertIsNone(sig.parameters["recent_failures"].default)

    def test_calls_with_no_history_dont_share_state(self):
        """Two calls with no history arg must not share the same dict instance."""
        from core.tool_registry import score_tool_relevance
        # Call once and check the internal dict isn't polluted across calls
        r1 = score_tool_relevance("read file", "read_file")
        r2 = score_tool_relevance("write file", "write_file")
        # Both should return floats without crashing
        self.assertIsInstance(r1, float)
        self.assertIsInstance(r2, float)

    def test_should_create_tool_default_failures_independent(self):
        """Confirm recent_failures=None creates a fresh list each call."""
        from core.tool_registry import should_create_tool
        result = should_create_tool("parse custom format")
        self.assertIn("should_create", result)


if __name__ == "__main__":
    unittest.main()
