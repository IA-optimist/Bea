"""tests/test_multi_agent.py — Multi-agent coordination tests."""
import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class TestAgentMessage:
    def test_create(self):
        from core.agents.agent_registry import AgentMessage, MessagePriority
        msg = AgentMessage(sender="orchestrator", receiver="forge-builder",
                           task="Build module", priority=MessagePriority.HIGH)
        assert msg.sender == "orchestrator"
        assert msg.receiver == "forge-builder"
        assert msg.status == "pending"
        assert len(msg.message_id) == 12

    def test_to_dict(self):
        from core.agents.agent_registry import AgentMessage
        msg = AgentMessage(sender="a", receiver="b", task="test")
        d = msg.to_dict()
        assert d["sender"] == "a"
        assert d["receiver"] == "b"
        assert "timestamp" in d


class TestAgentStatus:
    def test_success_rate(self):
        from core.agents.agent_registry import AgentStatus
        s = AgentStatus(agent_name="test", role="operator",
                        tasks_completed=8, tasks_failed=2)
        assert s.success_rate == 0.8

    def test_success_rate_zero(self):
        from core.agents.agent_registry import AgentStatus
        s = AgentStatus(agent_name="test", role="operator")
        assert s.success_rate == 1.0  # No tasks = perfect


class TestAgentRegistry:
    def test_init_from_roles(self):
        from core.agents.agent_registry import AgentRegistry
        reg = AgentRegistry()
        agents = reg.list_agents()
        assert len(agents) >= 15  # 19 agents from role definitions

    def test_register_new_agent(self):
        from core.agents.agent_registry import AgentRegistry
        reg = AgentRegistry()
        before = len(reg.list_agents())
        reg.register("test-agent-xyz", role="operator")
        after = len(reg.list_agents())
        assert after == before + 1

    def test_best_agent_for_role(self):
        from core.agents.agent_registry import AgentRegistry
        reg = AgentRegistry()
        agent = reg.best_agent_for_role("planner")
        assert agent is not None
        assert agent in ("atlas-director", "map-planner", "jarvis-architect")

    def test_best_agent_prefers_success(self):
        from core.agents.agent_registry import AgentRegistry
        reg = AgentRegistry()
        # Simulate: atlas-director has good track record
        a = reg.get_agent("atlas-director")
        a.tasks_completed = 10
        a.last_active = time.time()
        # map-planner has failures
        b = reg.get_agent("map-planner")
        b.tasks_completed = 2
        b.tasks_failed = 8
        b.last_active = time.time()
        best = reg.best_agent_for_role("planner")
        assert best == "atlas-director"

    def test_route_task(self):
        from core.agents.agent_registry import AgentRegistry
        reg = AgentRegistry()
        msg = reg.route_task("Research AI frameworks", required_role="researcher")
        assert msg is not None
        assert msg.status == "delivered"
        assert msg.receiver in ("scout-research", "vault-memory")

    def test_route_infers_role(self):
        from core.agents.agent_registry import AgentRegistry
        reg = AgentRegistry()
        msg = reg.route_task("Plan the deployment strategy")
        assert msg is not None
        # Should route to planner
        role = reg.get_agent(msg.receiver).role
        assert role == "planner"

    def test_complete_message(self):
        from core.agents.agent_registry import AgentRegistry
        reg = AgentRegistry()
        msg = reg.route_task("test task", required_role="operator")
        assert msg is not None
        reg.complete_message(msg.message_id, success=True, result={"output": "done"})
        agent = reg.get_agent(msg.receiver)
        assert agent.tasks_completed >= 1

    def test_error_streak_disables(self):
        from core.agents.agent_registry import AgentRegistry, MAX_ERROR_STREAK
        reg = AgentRegistry()
        for _ in range(MAX_ERROR_STREAK):
            msg = reg.send_message("test", "forge-builder", "failing task")
            reg.complete_message(msg.message_id, success=False)
        agent = reg.get_agent("forge-builder")
        assert not agent.available

    def test_send_message(self):
        from core.agents.agent_registry import AgentRegistry, MessagePriority
        reg = AgentRegistry()
        msg = reg.send_message("atlas-director", "forge-builder", "Build X",
                               priority=MessagePriority.HIGH)
        assert msg.status == "delivered"
        assert msg.priority == MessagePriority.HIGH

    def test_get_messages(self):
        from core.agents.agent_registry import AgentRegistry
        reg = AgentRegistry()
        reg.send_message("a", "forge-builder", "task1")
        reg.send_message("b", "forge-builder", "task2")
        msgs = reg.get_messages(agent="forge-builder")
        assert len(msgs) >= 2

    def test_stats(self):
        from core.agents.agent_registry import AgentRegistry
        reg = AgentRegistry()
        stats = reg.stats()
        assert stats["total_agents"] >= 15
        assert "by_role" in stats
        assert "available" in stats


class TestConnectorFramework:
    def test_import(self):
        from core.connectors.connector_framework import get_connector_framework
        cf = get_connector_framework()
        assert cf is not None

    def test_list_connectors(self):
        from core.connectors.connector_framework import get_connector_framework
        cf = get_connector_framework()
        connectors = cf.list_connectors()
        assert len(connectors) >= 10

    def test_by_domain(self):
        from core.connectors.connector_framework import get_connector_framework
        cf = get_connector_framework()
        domains = cf.by_domain()
        assert len(domains) >= 3
        # Should have filesystem, network, communication at minimum

    def test_stats(self):
        from core.connectors.connector_framework import get_connector_framework
        cf = get_connector_framework()
        stats = cf.stats()
        assert stats["total_connectors"] >= 10
        assert "domains" in stats

    def test_validate_unknown(self):
        from core.connectors.connector_framework import get_connector_framework
        cf = get_connector_framework()
        ok, msg = cf.validate("nonexistent_xyz", {})
        assert not ok

    def test_disable_enable(self):
        from core.connectors.connector_framework import get_connector_framework
        cf = get_connector_framework()
        cf.disable("json_storage")
        connectors = cf.list_connectors(enabled_only=True)
        names = [c["name"] for c in connectors]
        assert "json_storage" not in names
        cf.enable("json_storage")

    def test_register_custom(self):
        from core.connectors.connector_framework import (
            get_connector_framework, ConnectorDomain
        )
        cf = get_connector_framework()
        cf.register("test_connector", ConnectorDomain.API,
                     description="Test connector",
                     execute_fn=lambda p: {"ok": True, "data": "test"})
        result = cf.execute("test_connector", {})
        assert result["ok"] is True


class TestKnowledgeIngest:
    def test_chunk_text(self):
        from core.knowledge.ingest_pipeline import chunk_text
        text = "A" * 3000
        chunks = chunk_text(text, max_chars=1000, overlap=100)
        assert len(chunks) >= 3
        assert all(len(c) <= 1100 for c in chunks)

    def test_chunk_short_text(self):
        from core.knowledge.ingest_pipeline import chunk_text
        chunks = chunk_text("short text")
        assert len(chunks) == 1
        assert chunks[0] == "short text"

    def test_read_markdown(self, tmp_path):
        from core.knowledge.ingest_pipeline import read_markdown
        md = tmp_path / "test.md"
        md.write_text("# Title\n\nSome content here.\n\n## Section\n\nMore content.")
        entries = read_markdown(str(md))
        assert len(entries) >= 1
        assert entries[0].source_type == "documentation"

    def test_read_python(self, tmp_path):
        from core.knowledge.ingest_pipeline import read_python_file
        py = tmp_path / "test.py"
        py.write_text('"""Module docstring."""\n\nclass Foo:\n    """Class."""\n    pass\n\ndef bar():\n    return 1\n')
        entries = read_python_file(str(py))
        assert len(entries) >= 1
        assert entries[0].source_type == "code"

    def test_ingest_text(self):
        from core.knowledge.ingest_pipeline import IngestPipeline
        pipeline = IngestPipeline()
        stored = pipeline.ingest_text("Test knowledge about Python programming",
                                       source_type="documentation",
                                       source_label="test")
        # May be 0 if vector memory unavailable, but should not crash
        assert isinstance(stored, int)

    def test_dedup(self):
        from core.knowledge.ingest_pipeline import IngestPipeline
        pipeline = IngestPipeline()
        pipeline.ingest_text("Duplicate content test", source_label="test1")
        stats1 = pipeline.stats()
        pipeline.ingest_text("Duplicate content test", source_label="test2")
        stats2 = pipeline.stats()
        # Second ingest should be deduped (same hash)
        assert stats2["unique_hashes"] == stats1["unique_hashes"]

    def test_stats(self):
        from core.knowledge.ingest_pipeline import IngestPipeline
        pipeline = IngestPipeline()
        stats = pipeline.stats()
        assert "total_files_ingested" in stats
        assert "supported_extensions" in stats
        assert ".md" in stats["supported_extensions"]

    def test_knowledge_entry(self):
        from core.knowledge.ingest_pipeline import KnowledgeEntry
        e = KnowledgeEntry(content="test", source_type="code", source_path="test.py")
        assert len(e.content_hash) == 16
        assert e.source_type == "code"
