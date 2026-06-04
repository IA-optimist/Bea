"""Unit tests for core.autonomy.multi_choice."""
from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path

from core.autonomy.event_bus import EventBus, get_event_bus, reset_event_bus
from core.autonomy.multi_choice import (
    Choice,
    MultiChoiceStore,
    ask,
    get_multi_choice_store,
    reset_multi_choice_store,
)


class TestMultiChoiceStore(unittest.TestCase):
    def setUp(self):
        reset_event_bus()
        reset_multi_choice_store()
        self._tmp = tempfile.TemporaryDirectory()
        self.store = MultiChoiceStore(path=Path(self._tmp.name) / "decisions.json")

    def tearDown(self):
        self._tmp.cleanup()

    def _ch(self, *labels):
        return [Choice(index=i, label=l) for i, l in enumerate(labels)]

    def test_create_returns_pending(self):
        d = self.store.create("test", "?", self._ch("a", "b"))
        self.assertEqual(d.status, "pending")
        self.assertIsNone(d.selected_index)

    def test_create_with_empty_choices_raises(self):
        with self.assertRaises(ValueError):
            self.store.create("test", "?", [])

    def test_get_returns_decision(self):
        d = self.store.create("t", "?", self._ch("a", "b"))
        self.assertIs(self.store.get(d.decision_id), d)

    def test_pending_filters_resolved(self):
        d1 = self.store.create("a", "?", self._ch("x"))
        d2 = self.store.create("b", "?", self._ch("y"))
        self.store.answer(d1.decision_id, 0)
        pending = self.store.pending()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].decision_id, d2.decision_id)

    def test_answer_resolves_decision(self):
        d = self.store.create("test", "?", self._ch("a", "b", "c"))
        result = self.store.answer(d.decision_id, 1, answered_by="alice")
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "answered")
        self.assertEqual(result.selected_index, 1)
        self.assertEqual(result.answered_by, "alice")

    def test_answer_invalid_index_raises(self):
        d = self.store.create("test", "?", self._ch("a"))
        with self.assertRaises(ValueError):
            self.store.answer(d.decision_id, 99)

    def test_answer_unknown_returns_none(self):
        self.assertIsNone(self.store.answer("nope", 0))

    def test_cancel_marks_decision(self):
        d = self.store.create("test", "?", self._ch("a"))
        self.assertTrue(self.store.cancel(d.decision_id, reason="superseded"))
        d2 = self.store.get(d.decision_id)
        self.assertEqual(d2.status, "cancelled")
        self.assertEqual(d2.metadata["cancel_reason"], "superseded")

    def test_cancel_already_resolved_returns_false(self):
        d = self.store.create("test", "?", self._ch("a"))
        self.store.answer(d.decision_id, 0)
        self.assertFalse(self.store.cancel(d.decision_id))

    def test_persistence_across_instances(self):
        path = Path(self._tmp.name) / "decisions.json"
        d = self.store.create("test", "?", self._ch("a", "b"))
        self.store.answer(d.decision_id, 1)

        # New instance reads from disk
        store2 = MultiChoiceStore(path=path)
        d2 = store2.get(d.decision_id)
        self.assertIsNotNone(d2)
        self.assertEqual(d2.selected_index, 1)

    def test_publishes_lifecycle_events(self):
        bus = get_event_bus()
        topics = []
        bus.subscribe("decision.*", lambda e: topics.append(e.topic))
        d = self.store.create("test", "?", self._ch("a"))
        self.store.answer(d.decision_id, 0)
        self.assertIn("decision.created", topics)
        self.assertIn("decision.answered", topics)


class TestMultiChoiceWait(unittest.TestCase):
    def setUp(self):
        reset_event_bus()
        reset_multi_choice_store()
        # ignore_cleanup_errors : sur Windows la suppression du tempdir peut courir
        # avec la fin d'écriture/threads du store -> WinError 145 (dir non vide).
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.store = MultiChoiceStore(path=Path(self._tmp.name) / "d.json")

    def tearDown(self):
        self._tmp.cleanup()

    def _ch(self, *labels):
        return [Choice(index=i, label=l) for i, l in enumerate(labels)]

    def test_wait_returns_immediately_if_resolved(self):
        d = self.store.create("test", "?", self._ch("a"))
        self.store.answer(d.decision_id, 0)
        resolved = self.store.wait(d.decision_id, max_wait_s=0.1)
        self.assertEqual(resolved.status, "answered")

    def test_wait_unblocks_on_answer(self):
        d = self.store.create("test", "?", self._ch("a", "b"))

        def answer_after_delay():
            time.sleep(0.05)
            self.store.answer(d.decision_id, 1)

        threading.Thread(target=answer_after_delay, daemon=True).start()
        resolved = self.store.wait(d.decision_id, max_wait_s=2.0)
        self.assertEqual(resolved.selected_index, 1)

    def test_wait_timeout_with_default_choice(self):
        d = self.store.create("test", "?", self._ch("safe", "risky"), default_choice=0)
        resolved = self.store.wait(d.decision_id, max_wait_s=0.05)
        self.assertEqual(resolved.status, "timeout")
        self.assertEqual(resolved.selected_index, 0)

    def test_wait_timeout_without_default_raises(self):
        d = self.store.create("test", "?", self._ch("a"))
        with self.assertRaises(TimeoutError):
            self.store.wait(d.decision_id, max_wait_s=0.05)


class TestAskHelper(unittest.TestCase):
    def setUp(self):
        reset_event_bus()
        reset_multi_choice_store()

    def test_ask_non_blocking_returns_pending(self):
        d = ask(
            "test",
            "Pick one",
            [Choice(index=0, label="a"), Choice(index=1, label="b")],
            blocking=False,
        )
        self.assertEqual(d.status, "pending")

    def test_ask_blocking_with_default_returns_resolved(self):
        d = ask(
            "test",
            "?",
            [Choice(index=0, label="default-pick")],
            timeout_s=0.05,
            default_choice=0,
            blocking=True,
        )
        self.assertEqual(d.status, "timeout")
        self.assertEqual(d.selected_index, 0)


if __name__ == "__main__":
    unittest.main()
