"""
BeaMax - Project CRUD Operations
Async PostgreSQL operations for projects table.
"""
from __future__ import annotations
from typing import Optional, List, Dict, Any
from uuid import UUID
import asyncpg
import structlog

log = structlog.get_logger(__name__)

# Connection pool (initialized on startup)
_pool: Optional[asyncpg.Pool] = None


async def init_pool(dsn: str) -> None:
    """Initialize connection pool.

    Configuration robuste (aligné sur FIX 3 de la branche master) :
      - min_size=5, max_size=20 : capacité pour charge mixte
      - max_queries=50 000 : recyclage pour éviter la dérive mémoire
      - max_inactive_connection_lifetime=300s : ferme les conn. idle
      - command_timeout=60s : évite les queries runaway
      - timeout=30s : limite le temps d'attente d'une conn.
    """
    global _pool
    _pool = await asyncpg.create_pool(
        dsn,
        min_size=5,
        max_size=20,
        max_queries=50_000,
        max_inactive_connection_lifetime=300,
        command_timeout=60,
        timeout=30,
    )
    log.info("project_crud_pool_initialized", min_size=5, max_size=20)


async def get_project(project_id: str) -> Optional[Dict[str, Any]]:
    """Get project by ID."""
    if not _pool:
        log.error("pool_not_initialized")
        return None

    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM projects WHERE id = $1 AND deleted_at IS NULL",
            UUID(project_id)
        )

        if not row:
            return None

        return {
            "id": str(row["id"]),
            "name": row["name"],
            "description": row["description"],
            "config": row["config"],
            "created_at": row["created_at"].isoformat(),
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None
        }


async def list_projects(
    active_only: bool = True,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """List all projects."""
    if not _pool:
        log.error("pool_not_initialized")
        return []

    async with _pool.acquire() as conn:
        if active_only:
            rows = await conn.fetch(
                "SELECT * FROM projects WHERE deleted_at IS NULL ORDER BY created_at DESC LIMIT $1",
                limit
            )
        else:
            rows = await conn.fetch(
                "SELECT * FROM projects ORDER BY created_at DESC LIMIT $1",
                limit
            )

        projects = []
        for row in rows:
            projects.append({
                "id": str(row["id"]),
                "name": row["name"],
                "description": row["description"],
                "config": row["config"],
                "created_at": row["created_at"].isoformat(),
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
                "deleted_at": row["deleted_at"].isoformat() if row["deleted_at"] else None
            })

        return projects


async def create_project(
    name: str,
    description: str,
    config: Dict[str, Any]
) -> Dict[str, Any]:
    """Create new project."""
    if not _pool:
        log.error("pool_not_initialized")
        raise RuntimeError("Database pool not initialized")

    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO projects (name, description, config)
            VALUES ($1, $2, $3)
            RETURNING *
            """,
            name, description, config
        )

        return {
            "id": str(row["id"]),
            "name": row["name"],
            "description": row["description"],
            "config": row["config"],
            "created_at": row["created_at"].isoformat()
        }


async def update_project(
    project_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None
) -> Optional[Dict[str, Any]]:
    """Update project."""
    if not _pool:
        return None

    # Build dynamic UPDATE
    updates: list[str] = []
    params: list[Any] = []
    param_idx = 1

    if name is not None:
        updates.append(f"name = ${param_idx}")
        params.append(name)
        param_idx += 1

    if description is not None:
        updates.append(f"description = ${param_idx}")
        params.append(description)
        param_idx += 1

    if config is not None:
        updates.append(f"config = ${param_idx}")
        params.append(config)
        param_idx += 1

    if not updates:
        return await get_project(project_id)

    updates.append("updated_at = NOW()")
    params.append(UUID(project_id))

    # `updates` only contains literal column-name fragments built by this
    # function (`"name = $1"`, etc.); values flow via `params` through
    # asyncpg's $N placeholders. No user input reaches the f-string.
    query = f"""UPDATE projects SET {', '.join(updates)} WHERE id = ${param_idx} AND deleted_at IS NULL RETURNING *"""  # nosec B608  # noqa: S608

    async with _pool.acquire() as conn:
        row = await conn.fetchrow(query, *params)

        if not row:
            return None

        return {
            "id": str(row["id"]),
            "name": row["name"],
            "description": row["description"],
            "config": row["config"],
            "updated_at": row["updated_at"].isoformat()
        }


async def delete_project(project_id: str, soft: bool = True) -> bool:
    """Delete project (soft delete by default)."""
    if not _pool:
        return False

    async with _pool.acquire() as conn:
        result: str
        if soft:
            result = await conn.execute(
                "UPDATE projects SET deleted_at = NOW() WHERE id = $1",
                UUID(project_id)
            )
        else:
            result = await conn.execute(
                "DELETE FROM projects WHERE id = $1",
                UUID(project_id)
            )

        return result != "UPDATE 0" and result != "DELETE 0"
