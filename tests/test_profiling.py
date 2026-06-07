"""Tests for core.profiling."""
from __future__ import annotations

import asyncio
import os
import unittest

# Ensure profiling is enabled for these tests regardless of host env
os.environ["BEA_PROFILING"] = "1"

from core.profiling import profile_fn, profile_span  # noqa: E402


class TestProfileSpan(unittest.TestCase):
    def test_yields_without_error(self):
        with profile_span("test.ok"):
            x = 1 + 1
        self.assertEqual(x, 2)

    def test_reraises_exception(self):
        with self.assertRaises(ValueError):
            with profile_span("test.err"):
                raise ValueError("boom")

    def test_disabled_mode_is_noop(self):
        import importlib
        os.environ["BEA_PROFILING"] = "0"
        import core.profiling as prof
        importlib.reload(prof)
        try:
            with prof.profile_span("test.disabled"):
                x = 42
            self.assertEqual(x, 42)
        finally:
            os.environ["BEA_PROFILING"] = "1"
            importlib.reload(prof)


class TestProfileFnSync(unittest.TestCase):
    def test_sync_wrapped(self):
        @profile_fn("test.sync")
        def add(a: int, b: int) -> int:
            return a + b

        self.assertEqual(add(2, 3), 5)

    def test_preserves_return_value_and_args(self):
        @profile_fn()
        def greet(name: str, excl: bool = False) -> str:
            return f"hi {name}" + ("!" if excl else "")

        self.assertEqual(greet("alice"), "hi alice")
        self.assertEqual(greet("bob", excl=True), "hi bob!")


class TestProfileFnAsync(unittest.IsolatedAsyncioTestCase):
    async def test_async_wrapped(self):
        @profile_fn("test.async")
        async def async_add(a: int, b: int) -> int:
            await asyncio.sleep(0)
            return a + b

        self.assertEqual(await async_add(10, 20), 30)

    async def test_async_reraises(self):
        @profile_fn("test.async.err")
        async def boom():
            raise RuntimeError("nope")

        with self.assertRaises(RuntimeError):
            await boom()


if __name__ == "__main__":
    unittest.main()
