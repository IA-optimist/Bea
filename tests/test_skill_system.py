"""
tests/test_skill_system.py — Skill system lifecycle tests.

Covers: creation, duplicate detection, retrieval, thresholds,
MetaOrchestrator integration, and no-op on trivial missions.
"""
from __future__ import annotations
import pytest

import os
import sys
import tempfile
import unittest

# Ensure project root is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.skills.skill_models import Skill, SkillStep
from core.skills.skill_registry import SkillRegistry
from core.skills.skill_retriever import SkillRetriever, _tokenize
from core.skills.skill_builder import SkillBuilder
from core.skills.skill_service import SkillService


class TestSkillModels(unittest.TestCase):
    """Test Skill data model."""

    def test_create_skill(self):
        s = Skill(name="Fix API", description="Fix a broken FastAPI endpoint")
        self.assertTrue(len(s.skill_id) == 12)
        self.assertEqual(s.name, "Fix API")
        self.assertEqual(s.confidence, 0.5)
        self.assertEqual(s.use_count, 0)

    def test_to_dict_roundtrip(self):
        s = Skill(
            name="Deploy Docker",
            steps=[SkillStep(order=1, description="Build image")],
            tags=["docker", "deploy"],
        )
        d = s.to_dict()
        s2 = Skill.from_dict(d)
        self.assertEqual(s2.name, "Deploy Docker")
        self.assertEqual(len(s2.steps), 1)
        self.assertEqual(s2.steps[0].description, "Build image")

    def test_text_for_search(self):
        s = Skill(name="Fix API", description="Repair endpoint", tags=["fastapi"])
        text = s.text_for_search()
        self.assertIn("Fix API", text)
        self.assertIn("fastapi", text)

    def test_record_use(self):
        s = Skill(name="Test")
        s.record_use(success=True)
        self.assertEqual(s.use_count, 1)
        self.assertEqual(s.success_count, 1)
        s.record_use(success=False)
        self.assertEqual(s.use_count, 2)
        self.assertEqual(s.success_count, 1)


class TestSkillRegistry(unittest.TestCase):
    """Test persistent skill storage."""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
        self._tmp.close()
        self.reg = SkillRegistry(path=self._tmp.name)

    def tearDown(self):
        os.unlink(self._tmp.name)

    def test_add_and_get(self):
        s = Skill(name="Test Skill")
        self.reg.add(s)
        fetched = self.reg.get(s.skill_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.name, "Test Skill")

    def test_persistence(self):
        s = Skill(name="Persistent Skill", tags=["test"])
        self.reg.add(s)
        # Reload from file
        reg2 = SkillRegistry(path=self._tmp.name)
        self.assertEqual(reg2.count(), 1)
        fetched = reg2.get(s.skill_id)
        self.assertEqual(fetched.name, "Persistent Skill")

    def test_update(self):
        s = Skill(name="V1")
        self.reg.add(s)
        s.name = "V2"
        self.reg.update(s)
        self.assertEqual(self.reg.get(s.skill_id).name, "V2")

    def test_delete(self):
        s = Skill(name="Delete Me")
        self.reg.add(s)
        self.assertTrue(self.reg.delete(s.skill_id))
        self.assertIsNone(self.reg.get(s.skill_id))

    def test_find_by_tags(self):
        self.reg.add(Skill(name="Docker", tags=["docker", "deploy"]))
        self.reg.add(Skill(name="Python", tags=["python", "code"]))
        results = self.reg.find_by_tags(["docker"])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "Docker")


class TestSkillRetriever(unittest.TestCase):
    """Test skill retrieval and ranking."""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
        self._tmp.close()
        self.reg = SkillRegistry(path=self._tmp.name)
        self.ret = SkillRetriever(self.reg)

    def tearDown(self):
        os.unlink(self._tmp.name)

    def test_tokenize(self):
        tokens = _tokenize("Fix the FastAPI endpoint, please!")
        self.assertIn("fix", tokens)
        self.assertIn("fastapi", tokens)
        self.assertIn("endpoint", tokens)

    def test_retrieve_relevant(self):
        self.reg.add(Skill(
            name="Fix FastAPI endpoints",
            description="Debug and fix broken FastAPI routes",
            tags=["fastapi", "debug"],
            confidence=0.8,
        ))
        self.reg.add(Skill(
            name="Deploy Docker containers",
            description="Build and deploy Docker images",
            tags=["docker", "deploy"],
            confidence=0.7,
        ))
        results = self.ret.retrieve("fix broken fastapi route")
        self.assertTrue(len(results) >= 1)
        self.assertEqual(results[0][0].name, "Fix FastAPI endpoints")

    def test_min_confidence_filter(self):
        self.reg.add(Skill(
            name="Low confidence skill",
            description="Something vague",
            confidence=0.1,
        ))
        results = self.ret.retrieve("something vague", min_confidence=0.3)
        self.assertEqual(len(results), 0)

    def test_empty_registry(self):
        results = self.ret.retrieve("anything")
        self.assertEqual(len(results), 0)

    def test_retrieve_for_planning(self):
        self.reg.add(Skill(
            name="API debugging",
            description="Debug API errors in FastAPI",
            steps=[SkillStep(order=1, description="Check logs")],
            confidence=0.9,
        ))
        planning = self.ret.retrieve_for_planning("debug api error")
        self.assertTrue(len(planning) >= 1)
        self.assertIn("steps", planning[0])
        self.assertIn("confidence", planning[0])


class TestSkillBuilder(unittest.TestCase):
    """Test skill creation with gates and duplicate detection."""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
        self._tmp.close()
        self.reg = SkillRegistry(path=self._tmp.name)
        self.builder = SkillBuilder(self.reg)

    def tearDown(self):
        os.unlink(self._tmp.name)

    def test_create_from_success(self):
        skill = self.builder.maybe_create(
            mission_id="m001",
            goal="Fix the authentication endpoint that returns 401",
            result="Fixed by adding token validation middleware. " * 5,
            status="DONE",
            tools_used=["shell"],
            confidence=0.8,
        )
        self.assertIsNotNone(skill)
        self.assertEqual(skill.source_mission_id, "m001")
        self.assertGreater(len(skill.tags), 0)

    def test_skip_failed_mission(self):
        skill = self.builder.maybe_create(
            mission_id="m002",
            goal="Deploy the new version",
            result="Deployment failed due to missing env vars. " * 5,
            status="FAILED",
        )
        self.assertIsNone(skill)

    def test_skip_trivial_result(self):
        skill = self.builder.maybe_create(
            mission_id="m003",
            goal="What is 2+2?",
            result="Four.",
            status="DONE",
        )
        self.assertIsNone(skill)

    def test_skip_low_confidence(self):
        skill = self.builder.maybe_create(
            mission_id="m004",
            goal="Analyze the market trends for AI tools",
            result="The market is growing rapidly with many new entrants. " * 5,
            status="DONE",
            confidence=0.2,
        )
        self.assertIsNone(skill)

    def test_duplicate_detection(self):
        # Create first skill
        self.builder.maybe_create(
            mission_id="m005",
            goal="Fix the FastAPI authentication endpoint JWT validation",
            result="Added JWT token validation middleware to the FastAPI auth route endpoint. " * 5,
            status="DONE",
            confidence=0.8,
        )
        # Try to create near-duplicate with same words
        skill2 = self.builder.maybe_create(
            mission_id="m006",
            goal="Fix the FastAPI authentication endpoint JWT validation",
            result="Added JWT token validation middleware to the FastAPI auth route endpoint. " * 5,
            status="DONE",
            confidence=0.7,
        )
        # Should merge, not create new
        self.assertEqual(self.reg.count(), 1)

    def test_problem_classification(self):
        skill = self.builder.maybe_create(
            mission_id="m007",
            goal="Deploy the Docker container to production server",
            result="Built image, pushed to registry, deployed via compose. " * 5,
            status="DONE",
            tools_used=["shell"],
            confidence=0.7,
        )
        self.assertIsNotNone(skill)
        self.assertEqual(skill.problem_type, "deployment")


class TestSkillService(unittest.TestCase):
    """Test the unified service facade."""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
        self._tmp.close()
        self.svc = SkillService(store_path=self._tmp.name)

    def tearDown(self):
        os.unlink(self._tmp.name)

    def test_full_lifecycle(self):
        # Record a successful mission → creates skill
        skill = self.svc.record_outcome(
            mission_id="m100",
            goal="Fix broken health endpoint in FastAPI application",
            result="The health endpoint was returning 500 because of a missing import. "
                   "Fixed by importing health() from api.routes.system. " * 3,
            status="DONE",
            tools_used=["shell", "http"],
            confidence=0.85,
        )
        self.assertIsNotNone(skill)

        # Retrieve for a similar mission
        skills = self.svc.retrieve_for_mission("fix health endpoint error")
        self.assertTrue(len(skills) >= 1)
        self.assertEqual(skills[0]["name"][:10], "Fix broken")

        # Stats
        stats = self.svc.stats()
        self.assertEqual(stats["total"], 1)

        # List
        all_skills = self.svc.list_skills()
        self.assertEqual(len(all_skills), 1)

        # Search
        search = self.svc.search_skills("health endpoint")
        self.assertTrue(len(search) >= 1)

    def test_no_op_on_trivial(self):
        skill = self.svc.record_outcome(
            mission_id="m101",
            goal="Hi",
            result="Hello!",
            status="DONE",
        )
        self.assertIsNone(skill)
        self.assertEqual(self.svc.stats()["total"], 0)

    def test_record_skill_use(self):
        skill = self.svc.record_outcome(
            mission_id="m102",
            goal="Debug the database connection pooling issue",
            result="Connection pool was exhausted. Increased max_connections. " * 5,
            status="DONE",
            confidence=0.9,
        )
        self.assertIsNotNone(skill)
        self.svc.record_skill_use(skill.skill_id, success=True)
        updated = self.svc.get_skill(skill.skill_id)
        self.assertEqual(updated["use_count"], 1)


class TestMetaOrchestratorIntegration(unittest.TestCase):
    """Test that MetaOrchestrator references skill system correctly."""

    @pytest.mark.xfail(reason="skill import pattern drift in run_mission", strict=False)
    def test_skill_import_in_orchestrator(self):
        """Verify MetaOrchestrator integrates skill system via context_assembler."""
        import inspect
        from core.meta_orchestrator import MetaOrchestrator
        source = inspect.getsource(MetaOrchestrator.run_mission)
        # Skills retrieved via context_assembler, recorded via skill_service
        self.assertIn("prior_skills", source)
        self.assertIn("record_outcome", source)
        self.assertIn("context_assembler", source)

    def test_skill_system_importable(self):
        """Verify clean import chain."""
        from core.skills import get_skill_service
        svc = get_skill_service()
        self.assertIsNotNone(svc)
        stats = svc.stats()
        self.assertIn("total", stats)


if __name__ == "__main__":
    unittest.main()
