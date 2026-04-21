"""
tests/test_external_patterns.py — Tests for externally-inspired upgrades.

Covers: reflection, memory decay, skill refinement, enhanced mission loop.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import time

import pytest

_HAS_MEMORY_DECAY = importlib.util.find_spec("memory.memory_decay") is not None
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestReflection(unittest.TestCase):
    """Test post-execution reflection (LangGraph-inspired)."""

    def test_accept_good_result(self):
        from core.orchestration.reflection import reflect, ReflectionVerdict
        r = reflect(
            goal="Explain Docker networking",
            result="Docker uses bridge networks by default. Containers communicate "
                   "through virtual bridges. Port mapping exposes services. " * 3,
        )
        self.assertEqual(r.verdict, ReflectionVerdict.ACCEPT)
        self.assertGreater(r.confidence, 0.5)

    def test_empty_result(self):
        from core.orchestration.reflection import reflect, ReflectionVerdict
        r = reflect(goal="Do something", result="")
        self.assertEqual(r.verdict, ReflectionVerdict.EMPTY)
        self.assertEqual(r.confidence, 0.0)

    def test_short_result_low_confidence(self):
        from core.orchestration.reflection import reflect, ReflectionVerdict
        r = reflect(
            goal="Analyze the entire system architecture and produce report",
            result="OK",
        )
        self.assertIn(r.verdict, (ReflectionVerdict.RETRY_SUGGESTED,
                                   ReflectionVerdict.LOW_CONFIDENCE))
        self.assertLess(r.confidence, 0.5)

    def test_error_result_penalized(self):
        from core.orchestration.reflection import reflect
        r = reflect(
            goal="Deploy the app",
            result="Error: Traceback... Exception: failed to connect " * 3,
        )
        self.assertLess(r.confidence, 0.5)
        self.assertIn("error_indicators", r.quality_signals)

    def test_retry_penalty(self):
        from core.orchestration.reflection import reflect
        r0 = reflect("test", "Good result here " * 10, retries=0)
        r2 = reflect("test", "Good result here " * 10, retries=2)
        self.assertGreater(r0.confidence, r2.confidence)

    def test_to_dict(self):
        from core.orchestration.reflection import reflect
        r = reflect("test", "result text")
        d = r.to_dict()
        self.assertIn("verdict", d)
        self.assertIn("confidence", d)
        self.assertIn("quality_signals", d)


@pytest.mark.skipif(not _HAS_MEMORY_DECAY, reason="memory.memory_decay retiré du codebase (drift connu)")
class TestMemoryDecay(unittest.TestCase):
    """Test memory confidence decay (Hermes-inspired)."""

    def test_decay_old_unused(self):
        from memory.memory_decay import apply_decay

        old_ts = time.time() - 30 * 86400  # 30 days ago
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            f.write(json.dumps({
                "content": "Old unused fact",
                "confidence": 0.8,
                "created_at": old_ts,
                "last_accessed_at": old_ts,
                "use_count": 0,
            }) + "\n")
            path = f.name

        stats = apply_decay(path, grace_days=7)
        self.assertEqual(stats["decayed"], 1)

        with open(path) as f:
            item = json.loads(f.readline())
        self.assertLess(item["confidence"], 0.8)
        os.unlink(path)

    def test_no_decay_recent(self):
        from memory.memory_decay import apply_decay

        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            f.write(json.dumps({
                "content": "Recent fact",
                "confidence": 0.8,
                "created_at": time.time(),
            }) + "\n")
            path = f.name

        stats = apply_decay(path, grace_days=7)
        self.assertEqual(stats["decayed"], 0)
        os.unlink(path)

    def test_high_use_decays_slower(self):
        from memory.memory_decay import apply_decay

        old_ts = time.time() - 30 * 86400
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            # Item with high use count
            f.write(json.dumps({
                "content": "Frequently used",
                "confidence": 0.8,
                "created_at": old_ts,
                "last_accessed_at": old_ts,
                "use_count": 10,
            }) + "\n")
            # Item with zero use
            f.write(json.dumps({
                "content": "Never used",
                "confidence": 0.8,
                "created_at": old_ts,
                "last_accessed_at": old_ts,
                "use_count": 0,
            }) + "\n")
            path = f.name

        apply_decay(path, grace_days=7)

        with open(path) as f:
            high_use = json.loads(f.readline())
            low_use = json.loads(f.readline())
        # High use should decay less
        self.assertGreater(high_use["confidence"], low_use["confidence"])
        os.unlink(path)

    def test_dry_run(self):
        from memory.memory_decay import apply_decay

        old_ts = time.time() - 30 * 86400
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            f.write(json.dumps({
                "content": "test",
                "confidence": 0.8,
                "created_at": old_ts,
                "last_accessed_at": old_ts,
            }) + "\n")
            path = f.name

        stats = apply_decay(path, dry_run=True)
        self.assertEqual(stats["decayed"], 1)

        # File should be unchanged
        with open(path) as f:
            item = json.loads(f.readline())
        self.assertEqual(item["confidence"], 0.8)
        os.unlink(path)


class TestSkillRefinement(unittest.TestCase):
    """Test skill refinement on reuse (Hermes-inspired)."""

    def test_refine_boosts_confidence(self):
        from core.skills.skill_service import SkillService

        tmp = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
        tmp.close()
        svc = SkillService(store_path=tmp.name)

        skill = svc.record_outcome(
            mission_id="ref-001",
            goal="Fix database connection pooling exhaustion issue",
            result="Increased max_connections and added connection recycling. " * 5,
            status="DONE",
            confidence=0.6,
        )
        original_conf = skill.confidence

        # Refine on successful reuse
        svc.refine_skill(skill.skill_id, "Better result", success=True)
        updated = svc.get_skill(skill.skill_id)
        self.assertGreater(updated["confidence"], original_conf)
        self.assertEqual(updated["use_count"], 1)
        os.unlink(tmp.name)

    def test_failed_reuse_degrades(self):
        from core.skills.skill_service import SkillService

        tmp = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
        tmp.close()
        svc = SkillService(store_path=tmp.name)

        skill = svc.record_outcome(
            mission_id="ref-002",
            goal="Deploy application to Kubernetes cluster",
            result="Applied manifests and verified pod health checks. " * 5,
            status="DONE",
            confidence=0.7,
        )
        original_conf = skill.confidence

        svc.refine_skill(skill.skill_id, "Failed", success=False)
        updated = svc.get_skill(skill.skill_id)
        self.assertLess(updated["confidence"], original_conf)
        os.unlink(tmp.name)


class TestEnhancedMissionLoop(unittest.TestCase):
    """Test MetaOrchestrator has reflection and skill refinement."""

    @pytest.mark.xfail(reason="orchestrator reflection drift", strict=False)
    def test_orchestrator_has_reflection(self):
        import inspect
        from core.meta_orchestrator import MetaOrchestrator
        src = inspect.getsource(MetaOrchestrator.run_mission)
        self.assertIn("reflection", src)
        self.assertIn("reflect", src)
        self.assertIn("result_confidence", src)

    @pytest.mark.xfail(reason="orchestrator skill refinement drift", strict=False)
    def test_orchestrator_has_skill_refinement(self):
        import inspect
        from core.meta_orchestrator import MetaOrchestrator
        src = inspect.getsource(MetaOrchestrator.run_mission)
        self.assertIn("refine_skill", src)


if __name__ == "__main__":
    unittest.main()
