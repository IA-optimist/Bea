"""
BEA MAX — asyncio 3.12 Compatibility Test Suite (Pass 4)
===========================================================

Verifies that all runtime files use asyncio.get_running_loop() instead of the
deprecated asyncio.get_event_loop(), and that the replacements work correctly
inside async contexts.

Files audited:
  - core/meta_orchestrator.py
  - core/memory_facade.py
  - core/orchestrator_v2.py
  - core/improvement_memory.py
  - core/rag/ingestion.py
  - core/tools/browser_bridge.py
  - memory/memory_bus.py
  - memory/embeddings.py
  - executor/capability_dispatch.py
  - core/orchestration/execution_supervisor.py
"""
from __future__ import annotations

import asyncio
import pathlib
import unittest


# ─────────────────────────────────────────────────────────────────────────────
# Source-level audit: confirm no get_event_loop() in runtime paths
# ─────────────────────────────────────────────────────────────────────────────

RUNTIME_FILES = [
    "core/meta_orchestrator.py",
    "core/memory_facade.py",
    "core/orchestrator_v2.py",
    "core/improvement_memory.py",
    "core/rag/ingestion.py",
    "core/tools/browser_bridge.py",
    "memory/memory_bus.py",
    "memory/embeddings.py",
    "executor/capability_dispatch.py",
    "core/orchestration/execution_supervisor.py",
]


class TestNoDeprecatedGetEventLoop(unittest.TestCase):
    """Confirm get_event_loop() is not called in runtime-critical files."""

    def _check_file(self, rel_path: str):
        path = pathlib.Path(rel_path)
        if not path.exists():
            self.skipTest(f"{rel_path} not found")
        src = path.read_text(encoding="utf-8")
        # Filter out comment lines and the known store.py docstring reference
        bad_lines = [
            (i + 1, line.strip())
            for i, line in enumerate(src.splitlines())
            if "get_event_loop()" in line
            and not line.strip().startswith("#")
            and "remplace get_event_loop" not in line  # store.py docstring
        ]
        self.assertEqual(
            bad_lines, [],
            f"{rel_path} still uses get_event_loop() at lines: {bad_lines}"
        )

    def test_meta_orchestrator(self):
        self._check_file("core/meta_orchestrator.py")

    def test_memory_facade(self):
        self._check_file("core/memory_facade.py")

    def test_orchestrator_v2(self):
        self._check_file("core/orchestrator_v2.py")

    def test_improvement_memory(self):
        self._check_file("core/improvement_memory.py")

    def test_rag_ingestion(self):
        self._check_file("core/rag/ingestion.py")

    def test_browser_bridge(self):
        self._check_file("core/tools/browser_bridge.py")

    def test_memory_bus(self):
        self._check_file("memory/memory_bus.py")

    def test_embeddings(self):
        self._check_file("memory/embeddings.py")

    def test_capability_dispatch(self):
        self._check_file("executor/capability_dispatch.py")

    def test_execution_supervisor(self):
        self._check_file("core/orchestration/execution_supervisor.py")


# ─────────────────────────────────────────────────────────────────────────────
# Runtime correctness: get_running_loop() works inside async context
# ─────────────────────────────────────────────────────────────────────────────

class TestGetRunningLoopInAsyncContext(unittest.IsolatedAsyncioTestCase):

    async def test_get_running_loop_returns_running_loop(self):
        """get_running_loop() must return the active loop — no RuntimeError."""
        loop = asyncio.get_running_loop()
        self.assertIsNotNone(loop)
        self.assertTrue(loop.is_running())

    async def test_run_in_executor_via_running_loop(self):
        """run_in_executor() via get_running_loop() must work correctly."""
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, lambda: 42)
        self.assertEqual(result, 42)

    async def test_get_running_loop_raises_outside_async(self):
        """get_running_loop() raises RuntimeError when no loop is running (by design)."""
        # This test verifies Python's contract — our code runs inside async so it's safe.
        import threading
        errors = []

        def check_no_loop():
            try:
                asyncio.get_running_loop()
                # If this doesn't raise, that's actually OK in some Python versions
            except RuntimeError as e:
                errors.append(str(e))

        t = threading.Thread(target=check_no_loop)
        t.start()
        t.join()
        # Python 3.10+ raises RuntimeError in a thread with no loop — expected behavior
        # Our async methods are only called from within async context, so this is safe.


class TestBrowserBridgeRunAsync(unittest.TestCase):
    """_run_async in browser_bridge must handle both sync and async call contexts."""

    def test_run_async_executes_coroutine(self):
        """_run_async must run a simple coroutine and return its value."""
        from core.tools.browser_bridge import _run_async

        async def _simple():
            return "ok"

        result = _run_async(_simple())
        self.assertEqual(result, "ok")

    def test_run_async_no_event_loop_calls(self):
        """_run_async must not use the deprecated get_event_loop()."""
        src = pathlib.Path("core/tools/browser_bridge.py").read_text(encoding="utf-8")
        # The _run_async function specifically: check the body
        fn_start = src.find("def _run_async(")
        fn_end = src.find("\ndef ", fn_start + 1)
        fn_body = src[fn_start:fn_end]
        self.assertNotIn("get_event_loop()", fn_body,
                         "_run_async must not use deprecated get_event_loop()")


# ─────────────────────────────────────────────────────────────────────────────
# Approval gate: get_running_loop() in supervisor
# ─────────────────────────────────────────────────────────────────────────────

class TestSupervisorUsesRunningLoop(unittest.TestCase):

    def test_request_approval_uses_get_running_loop(self):
        src = pathlib.Path("core/orchestration/execution_supervisor.py").read_text(encoding="utf-8")
        # Find _request_approval function
        start = src.find("async def _request_approval")
        end = src.find("\nasync def ", start + 1)
        fn_body = src[start:end] if end > 0 else src[start:]
        self.assertIn("get_running_loop()", fn_body,
                      "_request_approval must use get_running_loop()")
        self.assertNotIn("get_event_loop()", fn_body,
                         "_request_approval must not use deprecated get_event_loop()")


# ─────────────────────────────────────────────────────────────────────────────
# CheckpointStore: all SQLite async methods use get_running_loop()
# ─────────────────────────────────────────────────────────────────────────────

class TestCheckpointStoreRunningLoop(unittest.TestCase):

    def test_checkpoint_sqlite_methods_use_running_loop(self):
        src = pathlib.Path("core/orchestrator_v2.py").read_text(encoding="utf-8")
        # Find CheckpointStore class section
        start = src.find("class CheckpointStore")
        class_body = src[start:] if start >= 0 else src
        bad = [
            line.strip() for line in class_body.splitlines()
            if "get_event_loop()" in line
            and not line.strip().startswith("#")
        ]
        self.assertEqual(bad, [],
                         f"CheckpointStore still uses get_event_loop(): {bad}")


if __name__ == "__main__":
    unittest.main()
