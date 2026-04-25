"""Unit tests for core.autonomy.event_bus."""
from __future__ import annotations

import asyncio
import time
import unittest

from core.autonomy.event_bus import EventBus, get_event_bus, reset_event_bus


class TestEventBusBasic(unittest.TestCase):
    def setUp(self):
        reset_event_bus()
        self.bus = EventBus()

    def test_singleton_returns_same_instance(self):
        a = get_event_bus()
        b = get_event_bus()
        self.assertIs(a, b)

    def test_publish_returns_event_with_id_and_ts(self):
        ev = self.bus.publish("x", {"k": "v"})
        self.assertEqual(ev.topic, "x")
        self.assertEqual(ev.payload, {"k": "v"})
        self.assertTrue(ev.id)
        self.assertGreater(ev.ts, 0)

    def test_sync_subscriber_receives(self):
        received = []
        self.bus.subscribe("mission.*", lambda e: received.append(e.topic))
        self.bus.publish("mission.completed")
        self.assertEqual(received, ["mission.completed"])

    def test_glob_pattern_matches(self):
        got = []
        self.bus.subscribe("metric.*", lambda e: got.append(e.topic))
        self.bus.publish("metric.cpu.high")
        self.bus.publish("mission.failed")  # should not match
        self.assertEqual(got, ["metric.cpu.high"])

    def test_unsubscribe_stops_delivery(self):
        got = []
        token = self.bus.subscribe("*", lambda e: got.append(e.topic))
        self.assertTrue(self.bus.unsubscribe(token))
        self.bus.publish("x")
        self.assertEqual(got, [])

    def test_unsubscribe_unknown_token_returns_false(self):
        self.assertFalse(self.bus.unsubscribe("does-not-exist"))

    def test_handler_error_is_isolated(self):
        good = []

        def bad(_):
            raise RuntimeError("nope")

        self.bus.subscribe("*", bad)
        self.bus.subscribe("*", lambda e: good.append(e.topic))
        self.bus.publish("z")
        # Good handler still fired despite bad one raising
        self.assertEqual(good, ["z"])
        stats = self.bus.stats()
        self.assertEqual(stats["errors"], 1)
        self.assertGreaterEqual(stats["delivered"], 1)

    def test_replay_returns_recent_events(self):
        for i in range(3):
            self.bus.publish("x", {"i": i})
        events = self.bus.replay("x", limit=10)
        self.assertEqual([e.payload["i"] for e in events], [0, 1, 2])

    def test_replay_pattern_filters(self):
        self.bus.publish("a")
        self.bus.publish("b")
        events = self.bus.replay("a", limit=10)
        self.assertEqual([e.topic for e in events], ["a"])

    def test_buffer_is_bounded(self):
        small = EventBus(buffer_size=3)
        for i in range(10):
            small.publish("x", {"i": i})
        events = small.replay("x", limit=100)
        self.assertEqual(len(events), 3)
        self.assertEqual([e.payload["i"] for e in events], [7, 8, 9])

    def test_stats_increment(self):
        for _ in range(5):
            self.bus.publish("x")
        self.assertEqual(self.bus.stats()["published"], 5)
        self.bus.reset_stats()
        self.assertEqual(self.bus.stats()["published"], 0)


class TestEventBusAsync(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        reset_event_bus()
        self.bus = EventBus()

    async def test_async_handler_runs_under_loop(self):
        got = []

        async def handler(e):
            await asyncio.sleep(0)
            got.append(e.topic)

        self.bus.subscribe("y", handler)
        self.bus.publish("y")
        # Yield to let the scheduled task run
        await asyncio.sleep(0.05)
        self.assertEqual(got, ["y"])


if __name__ == "__main__":
    unittest.main()
