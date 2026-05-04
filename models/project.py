"""
JarvisMax - Project Model
Multi-project architecture foundation with CRUD operations.

Project isolation enables:
- Separate mission scopes per business domain
- Independent memory/knowledge per project
- Project-specific agent configurations
- Fine-grained resource budgeting
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Optional
from uuid import UUID, uuid4

import structlog
from pydantic import BaseModel, Field, field_validator

log = structlog.get_logger(__name__)

# Database connection helper
def _get_db_connection():
    """Get PostgreSQL connection using environment variables."""
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        
        conn = psycopg2.connect(
            host=os.getenv("POSTGRES_HOST", "postgres"),
            database=os.getenv("POSTGRES_DB", "jarvis"),
            user=os.getenv("POSTGRES_USER", "jarvis"),
            password=os.getenv("POSTGRES_PASSWORD", ""),
            cursor_factory=RealDictCursor
        )
        return conn
    except ImportError:
        log.error("psycopg2 not installed, cannot connect to PostgreSQL")
        raise
    except Exception as e:
        log.error("Failed to connect to PostgreSQL", error=str(e))
        raise


# Pydantic Models
class ProjectConfig(BaseModel):
    """Project-specific configuration schema."""
    priority: str = "medium"  # low, medium, high, critical
    auto_deploy: bool = False
    budget_daily_usd: Optional[float] = None
    auto_submit: Optional[bool] = None
    min_severity: Optional[str] = None
    alert_threshold: Optional[str] = None
    auto_respond: Optional[bool] = None
    auto_categorize: Optional[bool] = None
    tax_jurisdiction: Optional[str] = None
    scan_frequency_hours: Optional[int] = None
    min_opportunity_score: Optional[float] = None
    track_all_revenue: Optional[bool] = None
    reporting_frequency: Optional[str] = None
    
    class Config:
        extra = "allow"  # Allow additional fields


class ProjectMetadata(BaseModel):
    """Project metadata schema."""
    tags: list[str] = Field(default_factory=list)
    owner: Optional[str] = None
    
    class Config:
        extra = "allow"


class Project(BaseModel):
    """
    Project model representing an isolated mission scope.
    
    Examples:
    - saas-generator: Autonomous SaaS generation
    - bug-bounty-hunter: Automated vulnerability discovery
    - blue-team-defense: Security monitoring and IR
    """
    id: UUID = Field(default_factory=uuid4)
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    config: ProjectConfig = Field(default_factory=ProjectConfig)
    metadata: ProjectMetadata = Field(default_factory=ProjectMetadata)
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    
    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate project name format (lowercase, hyphens, alphanumeric)."""
        if not v.replace("-", "").replace("_", "").isalnum():
            raise ValueError("Project name must contain only alphanumeric characters, hyphens, and underscores")
        return v.lower().strip()
    
    class Config:
        json_encoders = {
            UUID: str,
            datetime: lambda v: v.isoformat()
        }


# CRUD Operations

def create_project(
    name: str,
    description: Optional[str] = None,
    config: Optional[dict[str, Any]] = None,
    metadata: Optional[dict[str, Any]] = None
) -> Project:
    """
    Create a new project.
    
    Args:
        name: Unique project identifier (lowercase-hyphenated)
        description: Human-readable description
        config: Project-specific configuration
        metadata: Extended metadata (tags, owner, etc.)
    
    Returns:
        Created Project instance
    
    Raises:
        ValueError: If project name already exists
        Exception: If database operation fails
    """
    # Validate and create Pydantic model
    project_data = {
        "name": name,
        "description": description,
        "config": ProjectConfig(**(config or {})),
        "metadata": ProjectMetadata(**(metadata or {}))
    }
    project = Project(**project_data)
    
    conn = None
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        
        # Check for duplicate name
        cur.execute("SELECT id FROM projects WHERE name = %s", (project.name,))
        if cur.fetchone():
            raise ValueError(f"Project with name '{project.name}' already exists")
        
        # Insert project
        cur.execute("""
            INSERT INTO projects (id, name, description, config, metadata, is_active, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
        """, (
            str(project.id),
            project.name,
            project.description,
            json.dumps(project.config.model_dump()),
            json.dumps(project.metadata.model_dump()),
            project.is_active,
            project.created_at,
            project.updated_at
        ))
        
        result = cur.fetchone()
        conn.commit()
        
        log.info("project_created", project_id=str(project.id), name=project.name)
        
        # Return fresh instance from DB
        return _row_to_project(result)
        
    except Exception as e:
        if conn:
            conn.rollback()
        log.error("project_creation_failed", name=name, error=str(e))
        raise
    finally:
        if conn:
            conn.close()


def get_project(project_id: str | UUID) -> Optional[Project]:
    """
    Retrieve a project by ID.
    
    Args:
        project_id: UUID of the project
    
    Returns:
        Project instance or None if not found
    """
    conn = None
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        
        cur.execute("SELECT * FROM projects WHERE id = %s", (str(project_id),))
        result = cur.fetchone()
        
        if not result:
            return None
        
        return _row_to_project(result)
        
    except Exception as e:
        log.error("get_project_failed", project_id=str(project_id), error=str(e))
        return None
    finally:
        if conn:
            conn.close()


def get_project_by_name(name: str) -> Optional[Project]:
    """
    Retrieve a project by name.
    
    Args:
        name: Project name
    
    Returns:
        Project instance or None if not found
    """
    conn = None
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        
        cur.execute("SELECT * FROM projects WHERE name = %s", (name.lower(),))
        result = cur.fetchone()
        
        if not result:
            return None
        
        return _row_to_project(result)
        
    except Exception as e:
        log.error("get_project_by_name_failed", name=name, error=str(e))
        return None
    finally:
        if conn:
            conn.close()


def list_projects(active_only: bool = True) -> list[Project]:
    """
    List all projects.
    
    Args:
        active_only: If True, only return active projects
    
    Returns:
        List of Project instances
    """
    conn = None
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        
        query = "SELECT * FROM projects"
        if active_only:
            query += " WHERE is_active = true"
        query += " ORDER BY created_at DESC"
        
        cur.execute(query)
        results = cur.fetchall()
        
        return [_row_to_project(row) for row in results]
        
    except Exception as e:
        log.error("list_projects_failed", error=str(e))
        return []
    finally:
        if conn:
            conn.close()


def update_project(
    project_id: str | UUID,
    name: Optional[str] = None,
    description: Optional[str] = None,
    config: Optional[dict[str, Any]] = None,
    metadata: Optional[dict[str, Any]] = None,
    is_active: Optional[bool] = None
) -> Optional[Project]:
    """
    Update a project.
    
    Args:
        project_id: UUID of the project
        name: New name (must be unique)
        description: New description
        config: New configuration (merged with existing)
        metadata: New metadata (merged with existing)
        is_active: New active status
    
    Returns:
        Updated Project instance or None if not found
    
    Raises:
        ValueError: If new name conflicts with existing project
    """
    conn = None
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        
        # Fetch current project
        cur.execute("SELECT * FROM projects WHERE id = %s", (str(project_id),))
        current = cur.fetchone()
        if not current:
            return None
        
        # Build update dict
        updates = {}
        if name is not None:
            # Check for name conflict
            cur.execute("SELECT id FROM projects WHERE name = %s AND id != %s", (name.lower(), str(project_id)))
            if cur.fetchone():
                raise ValueError(f"Project name '{name}' already exists")
            updates["name"] = name.lower()
        
        if description is not None:
            updates["description"] = description
        
        if config is not None:
            # Merge with existing config
            current_config = current.get("config", {})
            merged_config = {**current_config, **config}
            updates["config"] = json.dumps(merged_config)
        
        if metadata is not None:
            # Merge with existing metadata
            current_metadata = current.get("metadata", {})
            merged_metadata = {**current_metadata, **metadata}
            updates["metadata"] = json.dumps(merged_metadata)
        
        if is_active is not None:
            updates["is_active"] = is_active
        
        if not updates:
            # No changes, return current
            return _row_to_project(current)
        
        # Build UPDATE query
        set_clauses = [f"{k} = %s" for k in updates.keys()]
        set_clauses.append("updated_at = NOW()")
        query = f"UPDATE projects SET {', '.join(set_clauses)} WHERE id = %s RETURNING *"
        
        cur.execute(query, list(updates.values()) + [str(project_id)])
        result = cur.fetchone()
        conn.commit()
        
        log.info("project_updated", project_id=str(project_id), updates=list(updates.keys()))
        
        return _row_to_project(result)
        
    except Exception as e:
        if conn:
            conn.rollback()
        log.error("update_project_failed", project_id=str(project_id), error=str(e))
        raise
    finally:
        if conn:
            conn.close()


def delete_project(project_id: str | UUID, hard_delete: bool = False) -> bool:
    """
    Delete a project (soft or hard delete).
    
    Args:
        project_id: UUID of the project
        hard_delete: If True, permanently delete; if False, set is_active=False
    
    Returns:
        True if deleted, False if not found
    """
    conn = None
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        
        if hard_delete:
            cur.execute("DELETE FROM projects WHERE id = %s RETURNING id", (str(project_id),))
        else:
            cur.execute(
                "UPDATE projects SET is_active = false, updated_at = NOW() WHERE id = %s RETURNING id",
                (str(project_id),)
            )
        
        result = cur.fetchone()
        conn.commit()
        
        if result:
            log.info("project_deleted", project_id=str(project_id), hard_delete=hard_delete)
            return True
        return False
        
    except Exception as e:
        if conn:
            conn.rollback()
        log.error("delete_project_failed", project_id=str(project_id), error=str(e))
        return False
    finally:
        if conn:
            conn.close()


# Helper functions

def _row_to_project(row: dict) -> Project:
    """Convert database row to Project instance."""
    return Project(
        id=UUID(row["id"]),
        name=row["name"],
        description=row.get("description"),
        config=ProjectConfig(**row.get("config", {})),
        metadata=ProjectMetadata(**row.get("metadata", {})),
        is_active=row.get("is_active", True),
        created_at=row["created_at"],
        updated_at=row["updated_at"]
    )
