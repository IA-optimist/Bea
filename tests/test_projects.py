"""
BeaMax - Project Model Tests
Tests for Phase 2.1 multi-project foundation.

NOTE: These are INTEGRATION tests requiring a live PostgreSQL instance
and psycopg2-binary installed. All tests are marked @pytest.mark.infra
and skipped by default. Run with --run-infra-tests to include them.
"""
import os
import pytest

# Mark all tests in this module as requiring infrastructure
pytestmark = pytest.mark.infra

# Set test environment — setdefault (pas d'assignation dure) pour que ces tests soient
# exécutables AUSSI hors conteneur : in-container "postgres" résout via le réseau compose ;
# depuis l'hôte on override (POSTGRES_HOST=127.0.0.1, POSTGRES_DB=beamax, etc.).
os.environ.setdefault("POSTGRES_HOST", "postgres")
os.environ.setdefault("POSTGRES_DB", "bea")
os.environ.setdefault("POSTGRES_USER", "bea")
os.environ.setdefault("POSTGRES_PASSWORD", "testpass123")

try:
    from models.project import (
        Project,
        create_project,
        get_project,
        get_project_by_name,
        list_projects,
        update_project,
        delete_project,
    )
except ImportError as e:
    pytest.skip(
        f"models.project not importable (missing psycopg2?): {e}",
        allow_module_level=True,
    )


@pytest.fixture(scope="module", autouse=True)
def _ensure_schema():
    """Applique les migrations (canonical_missions + vault_memory + projects & seeds) si la
    table `projects` est absente, pour rendre ces tests infra exécutables HORS conteneur
    (pas seulement dans le réseau compose pré-migré). Idempotent : no-op si le schéma existe."""
    import psycopg2
    from pathlib import Path

    conn = psycopg2.connect(
        host=os.environ["POSTGRES_HOST"],
        port=os.environ.get("POSTGRES_PORT", "5432"),
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
    )
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.projects')")
            if cur.fetchone()[0] is None:
                mig_dir = Path(__file__).resolve().parents[1] / "migrations"
                for fname in (
                    "001_init_schema.sql",
                    "002_memory_tables.sql",
                    "004_multi_project_foundation.sql",
                ):
                    cur.execute((mig_dir / fname).read_text(encoding="utf-8"))
    finally:
        conn.close()
    yield


class TestProjectCRUD:
    """Test project CRUD operations."""

    def test_create_project(self):
        """Test creating a new project."""
        project = create_project(
            name="test-project-crud",
            description="Test project for CRUD operations",
            config={"priority": "high"},
            metadata={"tags": ["test"]}
        )

        assert project is not None
        assert project.name == "test-project-crud"
        assert project.description == "Test project for CRUD operations"
        assert project.config.priority == "high"
        assert "test" in project.metadata.tags
        assert project.is_active is True

        # Cleanup
        delete_project(project.id, hard_delete=True)

    def test_create_duplicate_project_fails(self):
        """Test that creating a duplicate project fails."""
        project = create_project(name="test-duplicate")

        try:
            with pytest.raises(ValueError, match="already exists"):
                create_project(name="test-duplicate")
        finally:
            delete_project(project.id, hard_delete=True)

    def test_get_project_by_id(self):
        """Test retrieving a project by ID."""
        project = create_project(name="test-get-by-id")

        try:
            retrieved = get_project(project.id)
            assert retrieved is not None
            assert retrieved.id == project.id
            assert retrieved.name == "test-get-by-id"
        finally:
            delete_project(project.id, hard_delete=True)

    def test_get_project_by_name(self):
        """Test retrieving a project by name."""
        project = create_project(name="test-get-by-name")

        try:
            retrieved = get_project_by_name("test-get-by-name")
            assert retrieved is not None
            assert retrieved.name == "test-get-by-name"
        finally:
            delete_project(project.id, hard_delete=True)

    def test_list_projects(self):
        """Test listing all projects."""
        # Create test projects
        p1 = create_project(name="test-list-1")
        p2 = create_project(name="test-list-2")

        try:
            projects = list_projects(active_only=True)
            assert len(projects) >= 2

            project_names = [p.name for p in projects]
            assert "test-list-1" in project_names
            assert "test-list-2" in project_names
        finally:
            delete_project(p1.id, hard_delete=True)
            delete_project(p2.id, hard_delete=True)

    def test_update_project(self):
        """Test updating a project."""
        project = create_project(
            name="test-update",
            description="Original description"
        )

        try:
            updated = update_project(
                project.id,
                description="Updated description",
                config={"priority": "critical"}
            )

            assert updated is not None
            assert updated.description == "Updated description"
            assert updated.config.priority == "critical"
        finally:
            delete_project(project.id, hard_delete=True)

    def test_soft_delete_project(self):
        """Test soft deleting a project."""
        project = create_project(name="test-soft-delete")

        # Soft delete
        success = delete_project(project.id, hard_delete=False)
        assert success is True

        # Should still exist but not active
        retrieved = get_project(project.id)
        assert retrieved is not None
        assert retrieved.is_active is False

        # Should not appear in active-only list
        active_projects = list_projects(active_only=True)
        assert project.name not in [p.name for p in active_projects]

        # Cleanup
        delete_project(project.id, hard_delete=True)

    def test_hard_delete_project(self):
        """Test hard deleting a project."""
        project = create_project(name="test-hard-delete")

        # Hard delete
        success = delete_project(project.id, hard_delete=True)
        assert success is True

        # Should not exist
        retrieved = get_project(project.id)
        assert retrieved is None


class TestProjectIntegration:
    """Test project integration with missions and memory."""

    def test_mission_project_association(self):
        """Test that missions can be associated with projects."""
        import psycopg2
        from psycopg2.extras import RealDictCursor

        # Create a test project
        project = create_project(name="test-mission-project")

        try:
            # Create a test mission with project_id
            conn = psycopg2.connect(
                host=os.getenv("POSTGRES_HOST", "postgres"),
                database=os.getenv("POSTGRES_DB", "bea"),
                user=os.getenv("POSTGRES_USER", "bea"),
                password=os.getenv("POSTGRES_PASSWORD", "testpass123"),
                cursor_factory=RealDictCursor
            )
            cur = conn.cursor()

            cur.execute("""
                INSERT INTO canonical_missions 
                (mission_id, goal, status, risk_level, created_at, updated_at, context_json, project_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                "test-mission-123",
                "Test mission goal",
                "CREATED",
                "WRITE_LOW",
                1.0,
                1.0,
                "{}",
                str(project.id)
            ))
            conn.commit()

            # Verify mission has project_id
            cur.execute("""
                SELECT project_id FROM canonical_missions 
                WHERE mission_id = %s
            """, ("test-mission-123",))
            result = cur.fetchone()

            assert result is not None
            assert result["project_id"] == str(project.id)

            # Cleanup
            cur.execute("DELETE FROM canonical_missions WHERE mission_id = %s", ("test-mission-123",))
            conn.commit()
            conn.close()

        finally:
            delete_project(project.id, hard_delete=True)

    @pytest.mark.stale
    @pytest.mark.skip(
        reason="memory.legacy.project_memory est un module MORT (utilisé nulle part en prod) "
        "et son store_memory insère une chaîne brute, incompatible avec le schéma JSONB actuel "
        "de vault_memory.value. L'isolation mémoire par projet est désormais portée par MemoryBus."
    )
    def test_memory_project_isolation(self):
        """Test that memory entries can be isolated by project."""
        from memory.legacy.project_memory import store_memory, search_memories

        # Create two test projects
        p1 = create_project(name="test-memory-project-1")
        p2 = create_project(name="test-memory-project-2")

        try:
            # Store memories for each project
            store_memory("test-key-p1", "Memory for project 1", project_id=p1.id)
            store_memory("test-key-p2", "Memory for project 2", project_id=p2.id)

            # Search project 1 memories
            p1_memories = search_memories(project_id=p1.id)
            p1_keys = [m["key"] for m in p1_memories]

            assert "test-key-p1" in p1_keys
            assert "test-key-p2" not in p1_keys

            # Search project 2 memories
            p2_memories = search_memories(project_id=p2.id)
            p2_keys = [m["key"] for m in p2_memories]

            assert "test-key-p2" in p2_keys
            assert "test-key-p1" not in p2_keys

            # Cleanup memories
            import psycopg2
            conn = psycopg2.connect(
                host=os.getenv("POSTGRES_HOST", "postgres"),
                database=os.getenv("POSTGRES_DB", "bea"),
                user=os.getenv("POSTGRES_USER", "bea"),
                password=os.getenv("POSTGRES_PASSWORD", "testpass123")
            )
            cur = conn.cursor()
            cur.execute("DELETE FROM vault_memory WHERE key IN ('test-key-p1', 'test-key-p2')")
            conn.commit()
            conn.close()

        finally:
            delete_project(p1.id, hard_delete=True)
            delete_project(p2.id, hard_delete=True)


class TestDefaultProjects:
    """Test that default projects were seeded correctly."""

    def test_default_projects_exist(self):
        """Test that 6 default projects were seeded."""
        projects = list_projects(active_only=True)
        project_names = [p.name for p in projects]

        expected_projects = [
            "saas-generator",
            "bug-bounty-hunter",
            "blue-team-defense",
            "comptabilite-fiscale",
            "bizgen-intelligence",
            "cash-machine-ops"
        ]

        for expected in expected_projects:
            assert expected in project_names, f"Default project '{expected}' not found"

    def test_default_project_config(self):
        """Test that default projects have correct configuration."""
        saas = get_project_by_name("saas-generator")
        assert saas is not None
        assert saas.config.priority == "high"
        assert saas.config.auto_deploy is True

        bug_bounty = get_project_by_name("bug-bounty-hunter")
        assert bug_bounty is not None
        assert bug_bounty.config.auto_submit is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
