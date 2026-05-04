"""
tests/test_graph_persistence.py — Execution graph persistence tests.

GP01-GP20: Save, load, resume, list, index, history, stats.
"""


class TestGraphRepository:
    def _make_repo(self, tmp_path):
        from core.execution.graph_repository import GraphRepository
        return GraphRepository(base_dir=tmp_path / "graphs")

    def _make_graph(self, schema="VenturePlan", goal="Test goal"):
        from core.execution.execution_graph import build_execution_graph
        return build_execution_graph(schema, goal)

    def test_GP01_repo_creates_dir(self, tmp_path):
        self._make_repo(tmp_path)
        assert (tmp_path / "graphs").is_dir()

    def test_GP02_save_graph(self, tmp_path):
        repo = self._make_repo(tmp_path)
        g = self._make_graph()
        assert repo.save(g)
        assert (tmp_path / "graphs" / f"{g.graph_id}.json").exists()

    def test_GP03_load_graph(self, tmp_path):
        repo = self._make_repo(tmp_path)
        g = self._make_graph()
        repo.save(g)
        loaded = repo.load(g.graph_id)
        assert loaded is not None
        assert loaded.graph_id == g.graph_id
        assert loaded.source_schema == g.source_schema
        assert len(loaded.nodes) == len(g.nodes)

    def test_GP04_load_nonexistent(self, tmp_path):
        repo = self._make_repo(tmp_path)
        assert repo.load("nonexistent") is None

    def test_GP05_delete_graph(self, tmp_path):
        repo = self._make_repo(tmp_path)
        g = self._make_graph()
        repo.save(g)
        assert repo.delete(g.graph_id)
        assert repo.load(g.graph_id) is None

    def test_GP06_list_all(self, tmp_path):
        repo = self._make_repo(tmp_path)
        repo.save(self._make_graph("VenturePlan", "Goal A"))
        repo.save(self._make_graph("OpportunityReport", "Goal B"))
        items = repo.list_graphs()
        assert len(items) == 2

    def test_GP07_list_by_schema(self, tmp_path):
        repo = self._make_repo(tmp_path)
        repo.save(self._make_graph("VenturePlan"))
        repo.save(self._make_graph("OpportunityReport"))
        items = repo.list_graphs(schema="VenturePlan")
        assert len(items) == 1

    def test_GP08_list_by_mission(self, tmp_path):
        from core.execution.execution_graph import build_execution_graph
        repo = self._make_repo(tmp_path)
        g = build_execution_graph("VenturePlan", "test", mission_id="m-123")
        repo.save(g)
        repo.save(self._make_graph("VenturePlan"))
        items = repo.list_graphs(mission_id="m-123")
        assert len(items) == 1

    def test_GP09_get_stats(self, tmp_path):
        repo = self._make_repo(tmp_path)
        repo.save(self._make_graph("VenturePlan"))
        repo.save(self._make_graph("OpportunityReport"))
        stats = repo.get_stats()
        assert stats["total"] == 2
        assert "VenturePlan" in stats["by_schema"]

    def test_GP10_resumable_empty(self, tmp_path):
        repo = self._make_repo(tmp_path)
        repo.save(self._make_graph())
        # New graphs have progress 0 → not resumable
        assert len(repo.get_resumable()) == 0

    def test_GP11_index_persists(self, tmp_path):
        from core.execution.graph_repository import GraphRepository
        repo = self._make_repo(tmp_path)
        g = self._make_graph()
        repo.save(g)
        # Reload from disk
        repo2 = GraphRepository(base_dir=tmp_path / "graphs")
        items = repo2.list_graphs()
        assert len(items) == 1
        assert items[0]["graph_id"] == g.graph_id

    def test_GP12_graph_roundtrip_nodes(self, tmp_path):
        repo = self._make_repo(tmp_path)
        g = self._make_graph("VenturePlan")
        repo.save(g)
        loaded = repo.load(g.graph_id)
        assert len(loaded.nodes) == 4  # VenturePlan has 4 nodes
        for node in loaded.nodes:
            assert node.node_id
            assert node.artifact_template

    def test_GP13_graph_roundtrip_goal(self, tmp_path):
        repo = self._make_repo(tmp_path)
        g = self._make_graph(goal="Build a SaaS product for freelancers")
        repo.save(g)
        loaded = repo.load(g.graph_id)
        assert "freelancers" in loaded.goal

    def test_GP14_multiple_saves_update(self, tmp_path):
        repo = self._make_repo(tmp_path)
        g = self._make_graph()
        repo.save(g)
        g.goal = "Updated goal"
        repo.save(g)
        loaded = repo.load(g.graph_id)
        assert loaded.goal == "Updated goal"
        assert len(repo.list_graphs()) == 1  # Not duplicated

    def test_GP15_limit_works(self, tmp_path):
        repo = self._make_repo(tmp_path)
        for i in range(10):
            repo.save(self._make_graph(goal=f"Goal {i}"))
        items = repo.list_graphs(limit=3)
        assert len(items) == 3

    def test_GP16_ordered_by_created(self, tmp_path):
        import time
        repo = self._make_repo(tmp_path)
        repo.save(self._make_graph(goal="Old"))
        time.sleep(0.01)
        repo.save(self._make_graph(goal="New"))
        items = repo.list_graphs()
        assert items[0]["goal"][:3] == "New"

    def test_GP17_delete_nonexistent(self, tmp_path):
        repo = self._make_repo(tmp_path)
        assert repo.delete("nonexistent")

    def test_GP18_graph_from_dict_roundtrip(self):
        from core.execution.execution_graph import ExecutionGraph, build_execution_graph
        g = build_execution_graph("BusinessConcept", "Test")
        d = g.to_dict()
        g2 = ExecutionGraph.from_dict(d)
        assert g2.graph_id == g.graph_id
        assert len(g2.nodes) == len(g.nodes)

    def test_GP19_graph_summary_to_dict(self):
        from core.execution.graph_repository import GraphSummary
        s = GraphSummary(
            graph_id="eg-123", source_schema="VenturePlan",
            goal="x" * 300, mission_id="m-1",
            node_count=4, progress=0.5, created_at=1000.0,
        )
        d = s.to_dict()
        assert len(d["goal"]) <= 200  # Truncated

    def test_GP20_singleton(self):
        from core.execution.graph_repository import get_graph_repository
        r1 = get_graph_repository()
        r2 = get_graph_repository()
        assert r1 is r2
