"""
Unit tests for core.event_stream.

Covers append-only semantics, bounded deque, time-travel rewind,
and the mission-stream registry.
"""
from __future__ import annotations

import asyncio
import unittest

from core.event_stream import (
    ACTIVE_WS_STREAMS,
    EventStream,
    deregister_mission_stream,
    deregister_ws_stream,
    get_mission_stream,
    register_mission_stream,
    register_ws_stream,
)
from core.events import Action


def _make_event(source: str = "agent", action: str = "run", reasoning: str = "test") -> Action:
    """Build a minimal Action event for tests."""
    return Action(source=source, action_type=action, reasoning=reasoning)


class TestEventStreamAppend(unittest.IsolatedAsyncioTestCase):
    async def test_append_stores_event(self):
        stream = EventStream("mid-001")
        ev = _make_event()
        await stream.append(ev)
        events = stream.get_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].id, ev.id)

    async def test_append_preserves_order(self):
        stream = EventStream("mid-002")
        for i in range(5):
            await stream.append(_make_event(reasoning=f"step-{i}"))
        events = stream.get_events()
        self.assertEqual([e.reasoning for e in events], [f"step-{i}" for i in range(5)])

    async def test_get_events_with_start_and_limit(self):
        stream = EventStream("mid-003")
        for i in range(10):
            await stream.append(_make_event(reasoning=f"{i}"))
        sliced = stream.get_events(start=2, limit=3)
        self.assertEqual([e.reasoning for e in sliced], ["2", "3", "4"])

    async def test_bounded_deque_caps_at_500(self):
        """_MAX_EVENTS = 500 ; older events are dropped on overflow."""
        stream = EventStream("mid-004")
        # Append 520 events
        for i in range(520):
            await stream.append(_make_event(reasoning=f"{i}"))
        events = stream.get_events()
        self.assertEqual(len(events), 500)
        # First 20 should be dropped
        self.assertEqual(events[0].reasoning, "20")


class TestSubscribers(unittest.IsolatedAsyncioTestCase):
    async def test_subscriber_receives_events(self):
        stream = EventStream("sub-001")
        received = []

        async def listener(ev):
            received.append(ev.id)

        stream.subscribe(listener)
        ev = _make_event()
        await stream.append(ev)
        self.assertEqual(received, [ev.id])

    async def test_unsubscribe_stops_delivery(self):
        stream = EventStream("sub-002")
        received = []

        async def listener(ev):
            received.append(ev.id)

        stream.subscribe(listener)
        stream.unsubscribe(listener)
        await stream.append(_make_event())
        self.assertEqual(received, [])

    async def test_duplicate_subscribe_is_idempotent(self):
        stream = EventStream("sub-003")
        received = []

        async def listener(ev):
            received.append(ev.id)

        stream.subscribe(listener)
        stream.subscribe(listener)  # Should NOT double-register
        ev = _make_event()
        await stream.append(ev)
        self.assertEqual(len(received), 1)

    async def test_subscriber_error_doesnt_break_append(self):
        stream = EventStream("sub-004")

        async def bad_listener(ev):
            raise RuntimeError("listener broken")

        stream.subscribe(bad_listener)
        # Should not raise — subscriber errors are logged and swallowed
        await stream.append(_make_event())


class TestRewind(unittest.IsolatedAsyncioTestCase):
    async def test_rewind_drops_events_after_target(self):
        stream = EventStream("rwd-001")
        events = [_make_event(reasoning=str(i)) for i in range(5)]
        for e in events:
            await stream.append(e)

        # Rewind to event index 2
        target_id = events[2].id
        ok = await stream.rewind_to(target_id)
        self.assertTrue(ok)

        kept = stream.get_events()
        self.assertEqual(len(kept), 3)  # 0, 1, 2
        self.assertEqual(kept[-1].id, target_id)

    async def test_rewind_missing_id_returns_false(self):
        stream = EventStream("rwd-002")
        await stream.append(_make_event())
        ok = await stream.rewind_to("non-existent-id")
        self.assertFalse(ok)


class TestMissionRegistry(unittest.TestCase):
    def setUp(self):
        self._mid = "reg-test-001"
        deregister_mission_stream(self._mid)  # clean state

    def tearDown(self):
        deregister_mission_stream(self._mid)

    def test_register_and_get(self):
        s = EventStream(self._mid)
        register_mission_stream(self._mid, s)
        self.assertIs(get_mission_stream(self._mid), s)

    def test_deregister_makes_get_return_none(self):
        s = EventStream(self._mid)
        register_mission_stream(self._mid, s)
        deregister_mission_stream(self._mid)
        self.assertIsNone(get_mission_stream(self._mid))

    def test_get_unknown_is_none(self):
        self.assertIsNone(get_mission_stream("never-registered-xyz"))


class TestWsRegistry(unittest.TestCase):
    def setUp(self):
        self._mid = "ws-test-001"
        deregister_ws_stream(self._mid)

    def tearDown(self):
        deregister_ws_stream(self._mid)

    def test_register_ws_populates_active(self):
        s = EventStream(self._mid)
        register_ws_stream(self._mid, s)
        self.assertIn(self._mid, ACTIVE_WS_STREAMS)

    def test_deregister_ws_removes_from_active(self):
        s = EventStream(self._mid)
        register_ws_stream(self._mid, s)
        deregister_ws_stream(self._mid)
        self.assertNotIn(self._mid, ACTIVE_WS_STREAMS)


if __name__ == "__main__":
    unittest.main()
