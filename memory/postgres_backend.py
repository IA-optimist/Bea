"""
PostgreSQL Backend for Vault Memory
====================================
Implements persistent storage for memory/vault_memory.py using PostgreSQL.

Migration: 002_memory_tables.sql (vault_memory table)
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

log = structlog.get_logger()

# Optional dependencies
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    _PSYCOPG2_AVAILABLE = True
except ImportError:
    _PSYCOPG2_AVAILABLE = False
    log.warning("postgres_backend.psycopg2_unavailable", hint="pip install psycopg2-binary")


class PostgresMemoryBackend:
    """
    PostgreSQL-backed memory store for vault_memory.
    
    Features:
    - Persistent storage in vault_memory table
    - Type-based partitioning (mission, knowledge, improvement)
    - Tag-based search
    - Optional vector embeddings (requires pgvector extension)
    
    Usage:
        backend = PostgresMemoryBackend()
        backend.store("mission", "mission_123", {"status": "completed"}, tags=["success"])
        result = backend.retrieve("mission", "mission_123")
    """
    
    def __init__(self, database_url: str | None = None):
        """
        Initialize PostgreSQL backend.
        
        Args:
            database_url: PostgreSQL connection string (postgresql://user:pass@host:port/db)
                         Falls back to DATABASE_URL env var
        """
        self.database_url = database_url or os.getenv("DATABASE_URL", "")
        self._connection = None
        
        if not _PSYCOPG2_AVAILABLE:
            log.warning("postgres_backend.init_skipped", reason="psycopg2 not installed")
            return
        
        if not self.database_url:
            log.warning("postgres_backend.init_skipped", reason="DATABASE_URL not set")
            return
        
        try:
            self._connection = psycopg2.connect(self.database_url)
            log.info("postgres_backend.connected", host=self._get_host())
        except Exception as e:
            log.error("postgres_backend.connection_failed", error=str(e))
            self._connection = None
    
    def _get_host(self) -> str:
        """Extract hostname from database_url for logging."""
        if not self.database_url:
            return "none"
        try:
            # Format: postgresql://user:pass@host:port/db
            parts = self.database_url.split("@")
            if len(parts) < 2:
                return "localhost"
            host_part = parts[1].split("/")[0].split(":")[0]
            return host_part
        except Exception:
            return "unknown"
    
    def is_available(self) -> bool:
        """Check if backend is available."""
        return _PSYCOPG2_AVAILABLE and self._connection is not None
    
    def store(
        self,
        memory_type: str,
        key: str,
        value: dict[str, Any],
        tags: list[str] | None = None,
        embedding: list[float] | None = None,
    ) -> bool:
        """
        Store memory entry in PostgreSQL.
        
        Args:
            memory_type: Memory category (mission, knowledge, improvement, etc.)
            key: Unique identifier within memory_type namespace
            value: Memory payload (arbitrary dict)
            tags: Optional searchable tags
            embedding: Optional vector embedding (requires pgvector)
        
        Returns:
            True if stored successfully, False otherwise
        """
        if not self.is_available():
            return False
        
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO vault_memory (memory_type, key, value, tags, embedding, created_at, updated_at, accessed_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (memory_type, key) DO UPDATE SET
                        value = EXCLUDED.value,
                        tags = EXCLUDED.tags,
                        embedding = EXCLUDED.embedding,
                        updated_at = EXCLUDED.updated_at,
                        accessed_at = EXCLUDED.accessed_at
                    """,
                    (
                        memory_type,
                        key,
                        json.dumps(value),
                        tags or [],
                        embedding,  # TODO: Convert to pgvector format
                        datetime.now(timezone.utc),
                        datetime.now(timezone.utc),
                        datetime.now(timezone.utc),
                    ),
                )
                self._connection.commit()
                log.debug("postgres_backend.stored", type=memory_type, key=key, tags=tags)
                return True
        except Exception as e:
            log.error("postgres_backend.store_failed", type=memory_type, key=key, error=str(e))
            if self._connection:
                self._connection.rollback()
            return False
    
    def retrieve(self, memory_type: str, key: str) -> dict[str, Any] | None:
        """
        Retrieve memory entry from PostgreSQL.
        
        Args:
            memory_type: Memory category
            key: Entry identifier
        
        Returns:
            Memory value dict or None if not found
        """
        if not self.is_available():
            return None
        
        try:
            with self._connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    UPDATE vault_memory SET accessed_at = %s
                    WHERE memory_type = %s AND key = %s
                    RETURNING value
                    """,
                    (datetime.now(timezone.utc), memory_type, key),
                )
                result = cursor.fetchone()
                self._connection.commit()
                
                if result:
                    log.debug("postgres_backend.retrieved", type=memory_type, key=key)
                    return json.loads(result["value"]) if isinstance(result["value"], str) else result["value"]
                return None
        except Exception as e:
            log.error("postgres_backend.retrieve_failed", type=memory_type, key=key, error=str(e))
            if self._connection:
                self._connection.rollback()
            return None
    
    def search_by_tags(self, memory_type: str, tags: list[str], limit: int = 10) -> list[dict[str, Any]]:
        """
        Search memory entries by tags.
        
        Args:
            memory_type: Memory category filter
            tags: Tags to search for (ANY match)
            limit: Maximum results
        
        Returns:
            List of matching memory entries
        """
        if not self.is_available():
            return []
        
        try:
            with self._connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT key, value, tags, created_at, updated_at
                    FROM vault_memory
                    WHERE memory_type = %s AND tags && %s
                    ORDER BY updated_at DESC
                    LIMIT %s
                    """,
                    (memory_type, tags, limit),
                )
                results = cursor.fetchall()
                
                log.debug("postgres_backend.search", type=memory_type, tags=tags, found=len(results))
                return [
                    {
                        "key": row["key"],
                        "value": json.loads(row["value"]) if isinstance(row["value"], str) else row["value"],
                        "tags": row["tags"],
                        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
                    }
                    for row in results
                ]
        except Exception as e:
            log.error("postgres_backend.search_failed", type=memory_type, tags=tags, error=str(e))
            return []
    
    def delete(self, memory_type: str, key: str) -> bool:
        """Delete memory entry."""
        if not self.is_available():
            return False
        
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM vault_memory WHERE memory_type = %s AND key = %s",
                    (memory_type, key),
                )
                self._connection.commit()
                log.debug("postgres_backend.deleted", type=memory_type, key=key)
                return True
        except Exception as e:
            log.error("postgres_backend.delete_failed", type=memory_type, key=key, error=str(e))
            if self._connection:
                self._connection.rollback()
            return False
    
    def count(self, memory_type: str | None = None) -> int:
        """Count memory entries."""
        if not self.is_available():
            return 0
        
        try:
            with self._connection.cursor() as cursor:
                if memory_type:
                    cursor.execute("SELECT COUNT(*) FROM vault_memory WHERE memory_type = %s", (memory_type,))
                else:
                    cursor.execute("SELECT COUNT(*) FROM vault_memory")
                result = cursor.fetchone()
                return result[0] if result else 0
        except Exception as e:
            log.error("postgres_backend.count_failed", type=memory_type, error=str(e))
            return 0
    
    def close(self):
        """Close database connection."""
        if self._connection:
            self._connection.close()
            self._connection = None
            log.info("postgres_backend.closed")


# Singleton instance
_backend: PostgresMemoryBackend | None = None


def get_postgres_backend() -> PostgresMemoryBackend:
    """Get shared PostgreSQL backend instance."""
    global _backend
    if _backend is None:
        _backend = PostgresMemoryBackend()
    return _backend


def reset_postgres_backend():
    """Reset backend (for testing)."""
    global _backend
    if _backend:
        _backend.close()
    _backend = None
