"""
tests/test_full_upgrade.py — Tests for Steps 4-9 upgrades.

Covers: memory linking, capability health, skill retriever upgrade,
end-to-end pipeline integration.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Skip si module memory.memory_linker retiré (drift connu) ──────────────
_HAS_MEMORY_LINKER = importlib.util.find_spec("memory.memory_linker") is not None


@pytest.mark.skipif(not _HAS_MEMORY_LINKER, reason="memory.memory_linker retiré du codebase (drift connu)")
class TestMemoryLinker(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
        self.tmp.close()
        from memory.memory_linker import MemoryLinker
        self.linker = MemoryLinker(path=self.tmp.name)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_create_link(self):
        from memory.memory_linker import LinkType
        link = self.linker.link(
            "mission", "m-001", "skill", "sk-001",
            LinkType.MISSION_CREATED_SKILL,
        )
        self.assertEqual(link.source_id, "m-001")
        self.assertEqual(link.target_id, "sk-001")

    def test_find_links_by_entity(self):
        from memory.memory_linker import LinkType
        self.linker.link("mission", "m-002", "skill", "sk-002",
                         LinkType.MISSION_CREATED_SKILL)
        self.linker.link("mission", "m-002", "failure", "f-001",
                         LinkType.MISSION_HAD_FAILURE)
        links = self.linker.find_links("m-002")
        self.assertEqual(len(links), 2)

    def test_find_links_by_type(self):
        from memory.memory_linker import LinkType
        self.linker.link("mission", "m-003", "skill", "sk-003",
                         LinkType.MISSION_CREATED_SKILL)
        self.linker.link("mission", "m-003", "failure", "f-002",
                         LinkType.MISSION_HAD_FAILURE)
        links = self.linker.find_links("m-003",
                                        link_type=LinkType.MISSION_CREATED_SKILL)
        self.assertEqual(len(links), 1)

    def test_mission_graph(self):
        from memory.memory_linker import LinkType
        self.linker.link("mission", "m-004", "skill", "sk-004",
                         LinkType.MISSION_CREATED_SKILL)
        graph = self.linker.get_mission_graph("m-004")
        self.assertEqual(graph["mission_id"], "m-004")
        self.assertEqual(len(graph["skills_created"]), 1)

    def test_find_links_direction_filter(self):
        from memory.memory_linker import LinkType
        self.linker.link("mission", "m-005", "skill", "sk-005",
                         LinkType.MISSION_CREATED_SKILL)
        source_only = self.linker.find_links("m-005", direction="source")
        self.assertEqual(len(source_only), 1)
        target_only = self.linker.find_links("m-005", direction="target")
        self.assertEqual(len(target_only), 0)

    def test_stats(self):
        from memory.memory_linker import LinkType
        self.linker.link("mission", "m-006", "skill", "sk-006",
                         LinkType.MISSION_CREATED_SKILL)
        self.linker.link("mission", "m-006", "failure", "f-003",
                         LinkType.MISSION_HAD_FAILURE)
        s = self.linker.stats()
        self.assertEqual(s["total"], 2)
        self.assertIn("mission_created_skill", s["by_type"])


class TestCapabilityHealth(unittest.TestCase):

    def setUp(self):
        from executor.capability_health import CapabilityHealthTracker
        self.tracker = CapabilityHealthTracker()
        self.tracker.reset()

    def test_record_success(self):
        self.tracker.record_success("shell", duration_ms=100)
        h = self.tracker.get_health("shell")
        self.assertIsNotNone(h)
        self.assertEqual(h.successes, 1)
        self.assertEqual(h.success_rate, 1.0)

    def test_record_failure(self):
        self.tracker.record_failure("browser", error="timeout")
        h = self.tracker.get_health("browser")
        self.assertEqual(h.failures, 1)
        self.assertEqual(h.last_error, "timeout")

    def test_unhealthy_detection(self):
        for _ in range(5):
            self.tracker.record_failure("bad_tool", error="broken")
        self.assertFalse(self.tracker.is_healthy("bad_tool"))
        self.assertIn("bad_tool", self.tracker.unhealthy_capabilities())

    def test_unknown_is_healthy(self):
        self.assertTrue(self.tracker.is_healthy("nonexistent_tool"))

    def test_mixed_health(self):
        self.tracker.record_success("mixed", duration_ms=50)
        self.tracker.record_success("mixed", duration_ms=50)
        self.tracker.record_failure("mixed", error="oops")
        h = self.tracker.get_health("mixed")
        self.assertAlmostEqual(h.success_rate, 0.667, places=2)
        self.assertTrue(h.is_healthy())  # 66% > 50%

    def test_all_stats(self):
        self.tracker.record_success("tool_a")
        self.tracker.record_failure("tool_b", error="err")
        stats = self.tracker.all_stats()
        self.assertEqual(len(stats), 2)
        self.assertIn("success_rate", stats[0])


class TestSkillRetrieverUpgrade(unittest.TestCase):

    def test_problem_type_boost(self):
        from core.skills.skill_service import SkillService
        import tempfile
        tmp = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
        tmp.close()
        svc = SkillService(store_path=tmp.name)

        # Create a skill with problem_type
        svc.record_outcome(
            mission_id="pt-001",
            goal="Fix database connection pooling exhaustion with reconnect logic",
            result="Implemented connection pool recycling and health checks. " * 5,
            status="DONE",
            risk_level="write_low",
            confidence=0.7,
        )

        # Retrieve with matching problem_type (via classification)
        skills = svc.search_skills("Fix database timeout issue", top_k=3)
        # Should find the skill due to word overlap
        self.assertGreater(len(skills), 0)
        os.unlink(tmp.name)


@pytest.mark.skipif(not _HAS_MEMORY_LINKER, reason="memory.memory_linker retiré du codebase (drift connu)")
class TestLinkTypes(unittest.TestCase):
    """Verify all link types are valid."""

    def test_all_link_types(self):
        from memory.memory_linker import LinkType
        expected = {
            "mission_created_skill", "mission_had_failure",
            "failure_led_to_lesson", "skill_used_in_mission",
            "skill_refined_by_mission", "decision_in_mission",
            "mission_similar_to",
        }
        actual = {lt.value for lt in LinkType}
        self.assertEqual(expected, actual)


class TestDecisionTraceCost(unittest.TestCase):

    def test_cost_summary_format(self):
        from core.orchestration.decision_trace import DecisionTrace
        trace = DecisionTrace(mission_id="fmt-test")
        trace.record_cost(tokens_in=500, tokens_out=200, cost_usd=0.003)
        cs = trace.cost_summary()
        self.assertEqual(cs["tokens_in"], 500)
        self.assertEqual(cs["tokens_out"], 200)
        self.assertAlmostEqual(cs["total_cost_usd"], 0.003, places=4)
        self.assertIn("duration_s", cs)
        self.assertIn("phases", cs)


class TestArchitectureRules(unittest.TestCase):
    """Verify no architecture violations."""

    def test_no_second_orchestrator(self):
        import os
        orch_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                "core", "orchestration")
        for f in os.listdir(orch_dir):
            if f.endswith(".py"):
                with open(os.path.join(orch_dir, f), encoding="utf-8", errors="replace") as fh:
                    content = fh.read()
                self.assertNotIn("class MetaOrchestrator2", content)
                self.assertNotIn("class AlternateOrchestrator", content)

    def test_no_second_executor(self):
        import os
        exec_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                "executor")
        for f in os.listdir(exec_dir):
            if f.endswith(".py") and not f.startswith("__"):
                with open(os.path.join(exec_dir, f), encoding="utf-8", errors="replace") as fh:
                    content = fh.read()
                self.assertNotIn("class ExecutionResult2", content)


if __name__ == "__main__":
    unittest.main()
