"""tests/test_tool_ecosystem.py — Tool ecosystem + memory schema tests."""
import os
import sys
import time
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import types
if 'structlog' not in sys.modules:
    _sl = types.ModuleType('structlog')
    class _ML:
        def info(self, *a, **k): pass
        def debug(self, *a, **k): pass
        def warning(self, *a, **k): pass
        def error(self, *a, **k): pass
        def bind(self, **k): return self
    _sl.get_logger = lambda *a, **k: _ML()
    sys.modules['structlog'] = _sl


# ── Skips pour modules retirés du codebase (drift connu) ───────────────────
import importlib.util
import pytest

_HAS_EMAIL_TOOL = importlib.util.find_spec("core.tools.email_tool") is not None
_HAS_HTTP_TOOL = importlib.util.find_spec("core.tools.http_tool") is not None


# ── Email Tool ───────────────────────────────────────────────────────────────

@pytest.mark.skipif(not _HAS_EMAIL_TOOL, reason="core.tools.email_tool retiré du codebase (drift connu)")
class TestEmailTool(unittest.TestCase):

    def test_missing_recipient(self):
        from core.tools.email_tool import EmailTool
        t = EmailTool()
        r = t.execute(to="", subject="test", body="hello")
        self.assertFalse(r.ok)
        self.assertIn("invalid_recipient", r.error)

    def test_invalid_recipient(self):
        from core.tools.email_tool import EmailTool
        t = EmailTool()
        r = t.execute(to="not-an-email", subject="test", body="hello")
        self.assertFalse(r.ok)

    def test_missing_subject(self):
        from core.tools.email_tool import EmailTool
        t = EmailTool()
        r = t.execute(to="test@example.com", subject="", body="hello")
        self.assertFalse(r.ok)
        self.assertIn("missing_subject", r.error)

    def test_body_too_large(self):
        from core.tools.email_tool import EmailTool
        t = EmailTool()
        r = t.execute(to="test@example.com", subject="test", body="x" * 20000)
        self.assertFalse(r.ok)
        self.assertIn("body_too_large", r.error)

    def test_smtp_not_configured(self):
        from core.tools.email_tool import EmailTool
        old = os.environ.get("JARVIS_SMTP_HOST")
        os.environ.pop("JARVIS_SMTP_HOST", None)
        t = EmailTool()
        r = t.execute(to="test@example.com", subject="test", body="hello")
        self.assertFalse(r.ok)
        self.assertIn("smtp_not_configured", r.error)
        if old:
            os.environ["JARVIS_SMTP_HOST"] = old

    def test_capability_schema(self):
        from core.tools.email_tool import EmailTool
        t = EmailTool()
        s = t.capability_schema()
        self.assertEqual(s["name"], "email_send")
        self.assertEqual(s["risk_level"], "MEDIUM")


# ── HTTP Tool ────────────────────────────────────────────────────────────────

@pytest.mark.skipif(not _HAS_HTTP_TOOL, reason="core.tools.http_tool retiré du codebase (drift connu)")
class TestHttpTool(unittest.TestCase):

    def test_missing_url(self):
        from core.tools.http_tool import HttpTool
        t = HttpTool()
        r = t.execute(url="")
        self.assertFalse(r.ok)
        self.assertIn("missing_url", r.error)

    def test_invalid_url(self):
        from core.tools.http_tool import HttpTool
        t = HttpTool()
        r = t.execute(url="ftp://example.com")
        self.assertFalse(r.ok)
        self.assertIn("invalid_url", r.error)

    def test_blocked_host(self):
        from core.tools.http_tool import HttpTool
        t = HttpTool()
        r = t.execute(url="http://localhost:8080/secret")
        self.assertFalse(r.ok)
        self.assertIn("blocked_host", r.error)

    def test_blocked_internal_network(self):
        from core.tools.http_tool import HttpTool
        t = HttpTool()
        r = t.execute(url="http://10.0.0.1:8080/")
        self.assertFalse(r.ok)
        self.assertIn("blocked_host", r.error)

    def test_unsupported_method(self):
        from core.tools.http_tool import HttpTool
        t = HttpTool()
        r = t.execute(url="https://example.com", method="TRACE")
        self.assertFalse(r.ok)
        self.assertIn("unsupported_method", r.error)

    def test_capability_schema(self):
        from core.tools.http_tool import HttpTool
        t = HttpTool()
        s = t.capability_schema()
        self.assertEqual(s["name"], "http_request")


# ── File Tool ────────────────────────────────────────────────────────────────

class TestFileTool(unittest.TestCase):

    def test_read_missing_path(self):
        from core.tools.file_tool import FileReadTool
        t = FileReadTool()
        r = t.execute(path="")
        self.assertFalse(r.ok)
        self.assertIn("missing_path", r.error)

    def test_read_path_escape(self):
        from core.tools.file_tool import FileReadTool
        t = FileReadTool()
        r = t.execute(path="../../etc/passwd")
        self.assertFalse(r.ok)
        self.assertIn("path_escape", r.error)

    def test_write_missing_content(self):
        from core.tools.file_tool import FileWriteTool
        t = FileWriteTool()
        r = t.execute(path="test.txt", content="")
        self.assertFalse(r.ok)
        self.assertIn("missing_content", r.error)

    def test_write_content_too_large(self):
        from core.tools.file_tool import FileWriteTool
        t = FileWriteTool()
        r = t.execute(path="test.txt", content="x" * 60000)
        self.assertFalse(r.ok)
        self.assertIn("content_too_large", r.error)

    def test_write_path_escape(self):
        from core.tools.file_tool import FileWriteTool
        t = FileWriteTool()
        r = t.execute(path="../../../etc/malicious", content="bad")
        self.assertFalse(r.ok)
        self.assertIn("path_escape", r.error)


# ── Memory Schema ────────────────────────────────────────────────────────────

class TestMemorySchema(unittest.TestCase):

    def test_entry_creation(self):
        from core.memory.memory_schema import MemoryEntry
        e = MemoryEntry(tier="EPISODIC", memory_type="mission_result", content="test")
        self.assertEqual(e.tier, "EPISODIC")
        self.assertFalse(e.is_expired)

    def test_ttl_expiry(self):
        from core.memory.memory_schema import MemoryEntry
        e = MemoryEntry(tier="SHORT_TERM", ttl_seconds=0.1, content="temp")
        self.assertFalse(e.is_expired)
        time.sleep(0.15)
        self.assertTrue(e.is_expired)

    def test_permanent_never_expires(self):
        from core.memory.memory_schema import MemoryEntry
        e = MemoryEntry(tier="LONG_TERM", ttl_seconds=None, content="permanent")
        self.assertFalse(e.is_expired)

    def test_store_and_retrieve(self):
        from core.memory.memory_schema import MemoryStore, MemoryEntry
        store = MemoryStore(db_path=":memory:")
        eid = store.store(MemoryEntry(content="hello", tier="EPISODIC"))
        entry = store.retrieve(eid)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.content, "hello")

    def test_retrieve_expired_returns_none(self):
        from core.memory.memory_schema import MemoryStore, MemoryEntry
        store = MemoryStore(db_path=":memory:")
        eid = store.store(MemoryEntry(content="temp", ttl_seconds=0.1))
        time.sleep(0.15)
        self.assertIsNone(store.retrieve(eid))

    def test_search_by_type(self):
        from core.memory.memory_schema import MemoryStore, MemoryEntry
        store = MemoryStore(db_path=":memory:")
        store.store(MemoryEntry(memory_type="skill", content="python"))
        store.store(MemoryEntry(memory_type="lesson", content="retry works"))
        store.store(MemoryEntry(memory_type="skill", content="docker"))
        results = store.search(memory_type="skill")
        self.assertEqual(len(results), 2)

    def test_search_by_mission(self):
        from core.memory.memory_schema import MemoryStore, MemoryEntry
        store = MemoryStore(db_path=":memory:")
        store.store(MemoryEntry(mission_id="m-1", content="a"))
        store.store(MemoryEntry(mission_id="m-2", content="b"))
        results = store.search(mission_id="m-1")
        self.assertEqual(len(results), 1)

    def test_cleanup(self):
        from core.memory.memory_schema import MemoryStore, MemoryEntry
        store = MemoryStore(db_path=":memory:")
        store.store(MemoryEntry(content="old", ttl_seconds=0.1))
        store.store(MemoryEntry(content="new", ttl_seconds=3600))
        time.sleep(0.15)
        removed = store.cleanup()
        self.assertEqual(removed, 1)

    def test_stats(self):
        from core.memory.memory_schema import MemoryStore, MemoryEntry
        store = MemoryStore(db_path=":memory:")
        store.store(MemoryEntry(tier="SHORT_TERM", content="a"))
        store.store(MemoryEntry(tier="LONG_TERM", content="b"))
        stats = store.stats()
        self.assertEqual(stats["total"], 2)
        self.assertIn("by_tier", stats)

    def test_to_dict(self):
        from core.memory.memory_schema import MemoryEntry
        e = MemoryEntry(content="test")
        d = e.to_dict()
        self.assertIn("entry_id", d)
        self.assertIn("is_expired", d)


if __name__ == "__main__":
    unittest.main()
