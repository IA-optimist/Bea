"""Unit tests for core.autonomy.skills + builtin_skills."""
from __future__ import annotations

import unittest

from core.autonomy.event_bus import EventBus, reset_event_bus
from core.autonomy.skills import (
    Skill,
    SkillContext,
    SkillResult,
    get_skill_registry,
    register_skill,
    reset_skill_registry,
)


class TestSkillRegistry(unittest.TestCase):
    def setUp(self):
        reset_skill_registry()
        reset_event_bus()

    def test_register_and_get(self):
        s = Skill(name="echo", fn=lambda c: SkillResult(success=True, output=c.params))
        get_skill_registry().register(s)
        self.assertIs(get_skill_registry().get("echo"), s)

    def test_unregister(self):
        s = Skill(name="x", fn=lambda c: SkillResult(success=True))
        reg = get_skill_registry()
        reg.register(s)
        self.assertTrue(reg.unregister("x"))
        self.assertIsNone(reg.get("x"))

    def test_decorator_registers(self):
        @register_skill(name="d", tags=["t"])
        def my_skill(ctx):
            return SkillResult(success=True, output="ok")

        reg = get_skill_registry()
        self.assertIs(reg.get("d"), my_skill)
        self.assertEqual(reg.find_by_tag("t"), [my_skill])

    def test_run_publishes_lifecycle_events(self):
        bus = EventBus()
        topics = []
        bus.subscribe("skill.*", lambda e: topics.append(e.topic))

        s = Skill(name="ok", fn=lambda c: SkillResult(success=True))
        s.run(SkillContext(), bus=bus)
        self.assertIn("skill.invoked", topics)
        self.assertIn("skill.completed", topics)

    def test_run_failure_publishes_failed_event(self):
        bus = EventBus()
        topics = []
        bus.subscribe("skill.*", lambda e: topics.append(e.topic))

        s = Skill(name="bad", fn=lambda c: SkillResult(success=False, error="x"))
        s.run(SkillContext(), bus=bus)
        self.assertIn("skill.failed", topics)
        self.assertNotIn("skill.completed", topics)

    def test_run_exception_is_caught(self):
        bus = EventBus()

        def boom(_):
            raise RuntimeError("nope")

        s = Skill(name="b", fn=boom)
        result = s.run(SkillContext(), bus=bus)
        self.assertFalse(result.success)
        self.assertIn("nope", result.error)

    def test_find_by_tag(self):
        reg = get_skill_registry()
        reg.register(Skill(name="a", fn=lambda c: SkillResult(success=True), tags=["x"]))
        reg.register(Skill(name="b", fn=lambda c: SkillResult(success=True), tags=["x", "y"]))
        reg.register(Skill(name="c", fn=lambda c: SkillResult(success=True), tags=["y"]))
        names = sorted([s.name for s in reg.find_by_tag("x")])
        self.assertEqual(names, ["a", "b"])

    def test_names_sorted(self):
        reg = get_skill_registry()
        reg.register(Skill(name="z", fn=lambda c: SkillResult(success=True)))
        reg.register(Skill(name="a", fn=lambda c: SkillResult(success=True)))
        self.assertEqual(reg.names()[:2], ["a", "z"])


class TestBuiltinSkills(unittest.TestCase):
    def setUp(self):
        reset_skill_registry()
        reset_event_bus()
        # Trigger registration
        import importlib
        import core.autonomy.builtin_skills as bs
        importlib.reload(bs)

    def test_noop_skill_succeeds(self):
        s = get_skill_registry().get("noop")
        self.assertIsNotNone(s)
        r = s.run(SkillContext(params={"a": 1}))
        self.assertTrue(r.success)
        self.assertEqual(r.output, {"a": 1})

    def test_health_snapshot_skill(self):
        s = get_skill_registry().get("health.snapshot")
        r = s.run(SkillContext())
        self.assertTrue(r.success)
        self.assertIn("event_bus", r.output)
        self.assertIn("budget", r.output)

    def test_events_recent_skill(self):
        bus = __import__("core.autonomy.event_bus", fromlist=["get_event_bus"]).get_event_bus()
        bus.publish("autonomy.test", {"k": 1})
        s = get_skill_registry().get("events.recent")
        r = s.run(SkillContext(params={"pattern": "autonomy.*", "limit": 10}))
        self.assertTrue(r.success)
        topics = [e["topic"] for e in r.output]
        self.assertIn("autonomy.test", topics)


if __name__ == "__main__":
    unittest.main()
