"""Tests for core.llm_response_cache."""
from __future__ import annotations

import time
import unittest

from core.llm_response_cache import (
    _MAX_TEMP,
    _compute_cache_key,
    cached_llm_call,
    get_cache_stats,
    reset_cache_stats,
)


class TestCacheKey(unittest.TestCase):
    def test_stable_key_for_same_inputs(self):
        k1 = _compute_cache_key("m", 0.0, [{"role": "user", "content": "x"}])
        k2 = _compute_cache_key("m", 0.0, [{"role": "user", "content": "x"}])
        self.assertEqual(k1, k2)

    def test_different_model_diff_key(self):
        k1 = _compute_cache_key("m1", 0.0, [{"role": "user", "content": "x"}])
        k2 = _compute_cache_key("m2", 0.0, [{"role": "user", "content": "x"}])
        self.assertNotEqual(k1, k2)

    def test_different_temperature_diff_key(self):
        k1 = _compute_cache_key("m", 0.0, [{"role": "user", "content": "x"}])
        k2 = _compute_cache_key("m", 0.01, [{"role": "user", "content": "x"}])
        self.assertNotEqual(k1, k2)

    def test_different_messages_diff_key(self):
        k1 = _compute_cache_key("m", 0.0, [{"role": "user", "content": "x"}])
        k2 = _compute_cache_key("m", 0.0, [{"role": "user", "content": "y"}])
        self.assertNotEqual(k1, k2)


class TestCachedCall(unittest.TestCase):
    def setUp(self):
        reset_cache_stats()

    def test_miss_then_hit(self):
        calls = {"n": 0}

        def call_fn():
            calls["n"] += 1
            return {"ok": True, "value": calls["n"]}

        args = {
            "model": "m",
            "temperature": 0.0,
            "messages": [{"role": "user", "content": "x"}],
            "call_fn": call_fn,
        }

        r1 = cached_llm_call(**args)
        r2 = cached_llm_call(**args)

        self.assertEqual(r1, r2)
        self.assertEqual(calls["n"], 1)  # second call served from cache
        stats = get_cache_stats()
        self.assertEqual(stats["misses"], 1)
        self.assertEqual(stats["hits"], 1)

    def test_high_temperature_bypasses_cache(self):
        calls = {"n": 0}

        def call_fn():
            calls["n"] += 1
            return {"v": calls["n"]}

        args = {
            "model": "m",
            "temperature": 0.7,  # > _MAX_TEMP
            "messages": [{"role": "user", "content": "x"}],
            "call_fn": call_fn,
        }
        cached_llm_call(**args)
        cached_llm_call(**args)
        self.assertEqual(calls["n"], 2)  # both executed
        stats = get_cache_stats()
        self.assertEqual(stats["skips"], 2)

    def test_force_skip(self):
        calls = {"n": 0}
        cached_llm_call(
            model="m",
            temperature=0.0,
            messages=[{"role": "user", "content": "x"}],
            call_fn=lambda: calls.__setitem__("n", calls["n"] + 1) or {"v": calls["n"]},
            force_skip=True,
        )
        cached_llm_call(
            model="m",
            temperature=0.0,
            messages=[{"role": "user", "content": "x"}],
            call_fn=lambda: calls.__setitem__("n", calls["n"] + 1) or {"v": calls["n"]},
            force_skip=True,
        )
        self.assertEqual(calls["n"], 2)

    def test_max_temp_boundary(self):
        """Exactly at _MAX_TEMP is cached ; above is not."""
        calls = {"n": 0}

        def call_fn():
            calls["n"] += 1
            return {"v": calls["n"]}

        # At threshold → cached
        cached_llm_call(
            model="m",
            temperature=_MAX_TEMP,
            messages=[{"role": "user", "content": "t"}],
            call_fn=call_fn,
        )
        cached_llm_call(
            model="m",
            temperature=_MAX_TEMP,
            messages=[{"role": "user", "content": "t"}],
            call_fn=call_fn,
        )
        self.assertEqual(calls["n"], 1)


if __name__ == "__main__":
    unittest.main()
