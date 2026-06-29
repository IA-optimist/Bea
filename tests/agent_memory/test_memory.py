"""
tests/agent_memory/test_memory.py — Structured agent memory tests.
"""
from __future__ import annotations

import pytest

from agent_memory.models import MemoryType, StructuredMemory
from agent_memory.store import AgentMemoryStore
from agent_memory.learning import learn_from_failure, learn_from_success
from agent_memory.codebase import CodebaseMemoryService


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mem(**kwargs) -> StructuredMemory:
    defaults = dict(
        memory_type=MemoryType.FACT,
        realm="code",
        source="test-agent",
        confidence=0.9,
        content="This is a fact with enough length to pass validation.",
    )
    defaults.update(kwargs)
    return StructuredMemory(**defaults)


# ── StructuredMemory model tests ──────────────────────────────────────────────

class TestStructuredMemory:
    def test_requires_realm(self):
        with pytest.raises(Exception):
            StructuredMemory(
                memory_type=MemoryType.FACT,
                realm="",          # too short
                source="agent",
                confidence=0.9,
                content="enough content here",
            )

    def test_requires_source(self):
        with pytest.raises(Exception):
            StructuredMemory(
                memory_type=MemoryType.FACT,
                realm="code",
                source="x",        # too short (min_length=2)
                confidence=0.9,
                content="enough content here",
            )

    def test_confidence_bounds(self):
        with pytest.raises(Exception):
            _mem(confidence=1.5)
        with pytest.raises(Exception):
            _mem(confidence=-0.1)

    def test_is_uncertain_below_05(self):
        m = _mem(confidence=0.4)
        assert m.is_uncertain

    def test_is_not_uncertain_above_05(self):
        m = _mem(confidence=0.8)
        assert not m.is_uncertain

    def test_to_recall_context_uncertain_prefix(self):
        m = _mem(confidence=0.3)
        ctx = m.to_recall_context()
        assert "[UNCERTAIN]" in ctx

    def test_to_recall_context_normal(self):
        m = _mem(confidence=0.9)
        ctx = m.to_recall_context()
        assert "[UNCERTAIN]" not in ctx
        assert "FACT" in ctx

    def test_realm_lowercased(self):
        m = _mem(realm="CODE")
        assert m.realm == "code"

    def test_security_note_is_sensitive(self):
        m = _mem(memory_type=MemoryType.SECURITY_NOTE)
        assert m.is_security_sensitive

    def test_fact_not_sensitive(self):
        m = _mem(memory_type=MemoryType.FACT)
        assert not m.is_security_sensitive

    def test_superseded_by(self):
        m = _mem()
        assert not m.is_superseded
        m2 = m.model_copy(update={"superseded_by": "new-id-123"})
        assert m2.is_superseded


# ── AgentMemoryStore tests ────────────────────────────────────────────────────

class TestAgentMemoryStore:
    def test_add_and_get(self):
        store = AgentMemoryStore()
        m = _mem()
        mid = store.add(m)
        assert store.get(mid) is not None

    def test_recall_by_type(self):
        store = AgentMemoryStore()
        store.add(_mem(memory_type=MemoryType.BUG, content="a bug was found here in module X"))
        store.add(_mem(memory_type=MemoryType.FACT, content="this is a known fact about the API"))
        bugs = store.recall(memory_type=MemoryType.BUG)
        assert len(bugs) == 1
        assert bugs[0].memory_type == MemoryType.BUG

    def test_recall_by_realm(self):
        store = AgentMemoryStore()
        store.add(_mem(realm="security", content="a security observation about the auth module"))
        store.add(_mem(realm="code", content="code fact about the main module"))
        sec = store.recall(realm="security")
        assert len(sec) == 1 and sec[0].realm == "security"

    def test_recall_by_tags(self):
        store = AgentMemoryStore()
        store.add(_mem(tags=["qdrant", "vector"], content="vector DB observation for testing"))
        store.add(_mem(tags=["api"], content="API observation about the main endpoint"))
        q = store.recall(tags=["qdrant"])
        assert len(q) == 1

    def test_recall_min_confidence(self):
        store = AgentMemoryStore()
        store.add(_mem(confidence=0.3, content="uncertain observation with low confidence"))
        store.add(_mem(confidence=0.9, content="certain observation with high confidence"))
        high = store.recall(min_confidence=0.7)
        assert len(high) == 1

    def test_supersede(self):
        store = AgentMemoryStore()
        old_id = store.add(_mem(content="old fact about the module"))
        new_m = _mem(content="updated fact about the module with correction")
        store.supersede(old_id, new_m)
        # Old should be excluded by default
        result = store.recall()
        old_ids = [m.memory_id for m in result]
        assert old_id not in old_ids

    def test_context_for_agent(self):
        store = AgentMemoryStore()
        store.add(_mem(realm="code", content="fact about the code structure and modules"))
        ctx = store.context_for_agent("code")
        assert "FACT" in ctx
        assert "confidence" in ctx.lower()

    def test_stats(self):
        store = AgentMemoryStore()
        store.add(_mem(memory_type=MemoryType.BUG, content="bug in the parsing module"))
        store.add(_mem(memory_type=MemoryType.FACT, content="fact about the data structure"))
        stats = store.stats()
        assert stats["total"] == 2
        assert stats["active"] == 2
        assert stats["by_type"].get("bug") == 1


# ── Learning helpers tests ────────────────────────────────────────────────────

class TestLearning:
    def test_learn_from_failure(self):
        store = AgentMemoryStore()
        mid = learn_from_failure(
            store,
            agent_id="coder-1",
            mission_id="m-001",
            what_failed="apply_patch raised FileNotFoundError",
            why_it_failed="target file path was relative, not absolute",
            how_to_avoid="always resolve paths relative to workspace root before patching",
        )
        m = store.get(mid)
        assert m is not None
        assert m.memory_type == MemoryType.LESSON
        assert "failure" in m.tags

    def test_learn_from_success(self):
        store = AgentMemoryStore()
        mid = learn_from_success(
            store,
            agent_id="tester-1",
            mission_id="m-002",
            what_worked="using pytest --tb=short reduces noise in CI output",
        )
        m = store.get(mid)
        assert m is not None
        assert "success" in m.tags


# ── CodebaseMemoryService tests ───────────────────────────────────────────────

class TestCodebaseMemoryService:
    def test_snapshot_returns_something(self, tmp_path):
        # Write a trivial Python file
        (tmp_path / "mod.py").write_text("def foo(): pass\nclass Bar: pass\n")
        svc = CodebaseMemoryService(root=tmp_path)
        snap = svc.snapshot()
        assert snap.file_count >= 1
        names = [s.name for s in snap.symbols]
        assert "foo" in names or "Bar" in names

    def test_find_symbol(self, tmp_path):
        (tmp_path / "mod.py").write_text("def my_special_function(): pass\n")
        svc = CodebaseMemoryService(root=tmp_path)
        results = svc.find_symbol("my_special")
        assert any("my_special_function" in r.name for r in results)

    def test_grep(self, tmp_path):
        (tmp_path / "mod.py").write_text("x = 42\ny = x + 1\n")
        svc = CodebaseMemoryService(root=tmp_path)
        hits = svc.grep(r"x = \d+")
        assert any(h["content"].startswith("x = 42") for h in hits)

    def test_symbols_in_file(self, tmp_path):
        (tmp_path / "utils.py").write_text("def helper(): pass\n")
        svc = CodebaseMemoryService(root=tmp_path)
        results = svc.symbols_in_file("utils.py")
        assert any(s.name == "helper" for s in results)

    def test_invalidate_refreshes(self, tmp_path):
        (tmp_path / "mod.py").write_text("def foo(): pass\n")
        svc = CodebaseMemoryService(root=tmp_path)
        snap1 = svc.snapshot()
        (tmp_path / "new_mod.py").write_text("def bar(): pass\n")
        svc.invalidate()
        snap2 = svc.snapshot()
        assert snap2.file_count >= snap1.file_count
