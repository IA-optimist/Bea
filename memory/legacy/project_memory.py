"""
BeaMax - Project-Scoped Memory Facade
Wraps vault_memory operations with project_id filtering.

This module provides project-aware memory operations that ensure:
- Memories are isolated per project
- Cross-project queries respect boundaries
- Backward compatibility with non-project memories (project_id=NULL)
"""
from __future__ import annotations

import os
from typing import Any, Optional
from uuid import UUID

import structlog

log = structlog.get_logger(__name__)


def _get_db_connection() -> Any:
    """Get PostgreSQL connection."""
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        
        conn = psycopg2.connect(
            host=os.getenv("POSTGRES_HOST", "postgres"),
            database=os.getenv("POSTGRES_DB", "bea"),
            user=os.getenv("POSTGRES_USER", "bea"),
            password=os.getenv("POSTGRES_PASSWORD", ""),
            cursor_factory=RealDictCursor
        )
        return conn
    except Exception as e:
        log.error("db_connection_failed", error=str(e))
        raise


def store_memory(
    key: str,
    value: str,
    tags: list[str] | None = None,
    project_id: Optional[str | UUID] = None
) -> bool:
    """
    Store a memory entry with optional project isolation.
    
    Args:
        key: Unique memory key
        value: Memory content
        tags: Optional tags for categorization
        project_id: Optional project UUID for isolation
    
    Returns:
        True if stored successfully
    """
    conn = None
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        
        # Convert UUID to string if needed
        proj_id_str = str(project_id) if project_id else None
        
        cur.execute("""
            INSERT INTO vault_memory (key, value, tags, project_id, created_at, updated_at)
            VALUES (%s, %s, %s, %s, NOW(), NOW())
            ON CONFLICT (key) DO UPDATE
            SET value = EXCLUDED.value,
                tags = EXCLUDED.tags,
                project_id = EXCLUDED.project_id,
                updated_at = NOW()
        """, (key, value, tags or [], proj_id_str))
        
        conn.commit()
        log.debug("memory_stored", key=key, project_id=proj_id_str)
        return True
        
    except Exception as e:
        if conn:
            conn.rollback()
        log.error("store_memory_failed", key=key, error=str(e))
        return False
    finally:
        if conn:
            conn.close()


def get_memory(
    key: str,
    project_id: Optional[str | UUID] = None
) -> dict[str, Any] | None:
    """
    Retrieve a memory entry by key, optionally filtered by project.
    
    Args:
        key: Memory key
        project_id: Optional project UUID for isolation
    
    Returns:
        Memory dict or None if not found
    """
    conn = None
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        
        proj_id_str = str(project_id) if project_id else None
        
        if proj_id_str:
            # Project-scoped lookup
            cur.execute("""
                SELECT * FROM vault_memory 
                WHERE key = %s AND project_id = %s
            """, (key, proj_id_str))
        else:
            # Global lookup (includes project_id=NULL entries)
            cur.execute("SELECT * FROM vault_memory WHERE key = %s", (key,))
        
        result = cur.fetchone()
        return dict(result) if result else None
        
    except Exception as e:
        log.error("get_memory_failed", key=key, error=str(e))
        return None
    finally:
        if conn:
            conn.close()


def search_memories(
    query: Optional[str] = None,
    tags: list[str] | None = None,
    project_id: Optional[str | UUID] = None,
    limit: int = 10
) -> list[dict[str, Any]]:
    """
    Search memories with optional filters.
    
    Args:
        query: Optional text search query (uses PostgreSQL full-text search)
        tags: Optional tags to filter by (ANY match)
        project_id: Optional project UUID for isolation
        limit: Maximum number of results
    
    Returns:
        List of memory dicts
    """
    conn = None
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        
        proj_id_str = str(project_id) if project_id else None
        
        # Build query dynamically
        conditions: list[str] = []
        params: list[Any] = []
        
        if proj_id_str:
            conditions.append("project_id = %s")
            params.append(proj_id_str)
        
        if query:
            conditions.append("value ILIKE %s")
            params.append(f"%{query}%")
        
        if tags:
            conditions.append("tags && %s")
            params.append(tags)
        
        where_clause = " AND ".join(conditions) if conditions else "TRUE"
        
        sql = f"""
            SELECT * FROM vault_memory
            WHERE {where_clause}
            ORDER BY updated_at DESC
            LIMIT %s
        """
        params.append(limit)
        
        cur.execute(sql, params)
        results = cur.fetchall()
        
        return [dict(row) for row in results]
        
    except Exception as e:
        log.error("search_memories_failed", error=str(e))
        return []
    finally:
        if conn:
            conn.close()


def delete_memory(
    key: str,
    project_id: Optional[str | UUID] = None
) -> bool:
    """
    Delete a memory entry.
    
    Args:
        key: Memory key
        project_id: Optional project UUID for scoped deletion
    
    Returns:
        True if deleted
    """
    conn = None
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        
        proj_id_str = str(project_id) if project_id else None
        
        if proj_id_str:
            cur.execute("""
                DELETE FROM vault_memory 
                WHERE key = %s AND project_id = %s
                RETURNING id
            """, (key, proj_id_str))
        else:
            cur.execute("""
                DELETE FROM vault_memory 
                WHERE key = %s
                RETURNING id
            """, (key,))
        
        result = cur.fetchone()
        conn.commit()
        
        if result:
            log.debug("memory_deleted", key=key, project_id=proj_id_str)
            return True
        return False
        
    except Exception as e:
        if conn:
            conn.rollback()
        log.error("delete_memory_failed", key=key, error=str(e))
        return False
    finally:
        if conn:
            conn.close()


def get_project_memory_stats(project_id: str | UUID) -> dict[str, Any]:
    """
    Get memory statistics for a project.
    
    Args:
        project_id: Project UUID
    
    Returns:
        Dict with memory stats (total_entries, unique_tags, etc.)
    """
    conn = None
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        
        proj_id_str = str(project_id)
        
        # Get counts
        cur.execute("""
            SELECT 
                COUNT(*) as total_entries,
                COUNT(DISTINCT unnest(tags)) as unique_tags
            FROM vault_memory
            WHERE project_id = %s
        """, (proj_id_str,))
        
        result = cur.fetchone()
        
        if result:
            return dict(result)
        return {"total_entries": 0, "unique_tags": 0}
        
    except Exception as e:
        log.error("get_project_memory_stats_failed", project_id=str(project_id), error=str(e))
        return {"total_entries": 0, "unique_tags": 0, "error": str(e)}
    finally:
        if conn:
            conn.close()
