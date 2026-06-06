"""PostgreSQL backend for VaultMemory with Redis L1 cache.

Provides persistent storage for VaultEntry objects with:
- PostgreSQL as durable L2 storage
- Redis as fast L1 cache (optional)
- Tag-based search capabilities
- JSON serialization for complex objects
"""

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

# Hardening (audit Mo1): `table_name` est interpolé en f-string dans tous les
# SQL (CREATE TABLE, CREATE INDEX, INSERT, SELECT, UPDATE, DELETE) parce que
# psycopg2 ne sait pas paramétrer les identifiants. Aujourd'hui le seul
# caller passe la valeur par défaut "vault_entries", donc pas d'injection
# possible — mais le pattern est fragile : tout futur caller qui passerait
# une chaîne issue d'un input utilisateur ouvrirait une RCE SQL.
# On valide ici à la frontière du constructeur : seul un identifiant
# alphanumérique + underscore est accepté.
_SQL_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}$")

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

logger = logging.getLogger(__name__)


class PostgresBackend:
    """PostgreSQL backend with Redis L1 cache for VaultMemory."""

    def __init__(self,
                 connection_string: Optional[str] = None,
                 redis_url: Optional[str] = None,
                 table_name: str = "vault_entries"):
        """Initialize PostgreSQL backend with optional Redis cache.

        Args:
            connection_string: PostgreSQL connection string (postgresql://user:pass@host:port/db)
            redis_url: Redis connection URL (redis://host:port/db)
            table_name: Name of the PostgreSQL table. Must be a valid SQL
                identifier (letters, digits, underscore, max 63 chars). Raises
                ValueError otherwise — interpolation directe en SQL.

        Raises:
            ValueError: si table_name n'est pas un identifiant SQL sûr.
        """
        if not isinstance(table_name, str) or not _SQL_IDENTIFIER_RE.match(table_name):
            raise ValueError(
                f"Invalid table_name {table_name!r}: must match "
                f"{_SQL_IDENTIFIER_RE.pattern} (SQL identifier, max 63 chars)."
            )
        self.connection_string = connection_string
        self.redis_url = redis_url
        self.table_name = table_name
        self.conn = None
        self.redis_client = None
        self._initialized = False

    def initialize(self) -> bool:
        """Initialize database connection and create table if needed.
        
        Returns:
            True if initialization successful, False otherwise
        """
        if not POSTGRES_AVAILABLE:
            logger.warning("psycopg2 not available, PostgreSQL backend disabled")
            return False

        if not self.connection_string:
            logger.info("No PostgreSQL connection string provided, backend disabled")
            return False

        try:
            # Connect to PostgreSQL
            self.conn = psycopg2.connect(self.connection_string)
            self._create_table()
            
            # Connect to Redis if available and configured
            if REDIS_AVAILABLE and self.redis_url:
                try:
                    self.redis_client = redis.from_url(self.redis_url, decode_responses=True)
                    self.redis_client.ping()
                    logger.info("Redis L1 cache initialized")
                except Exception as e:
                    logger.warning(f"Redis connection failed, continuing without cache: {e}")
                    self.redis_client = None
            
            self._initialized = True
            logger.info(f"PostgreSQL backend initialized (table: {self.table_name})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize PostgreSQL backend: {e}")
            self.conn = None
            return False

    def _create_table(self):
        """Create the vault entries table if it doesn't exist."""
        with self.conn.cursor() as cur:
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.table_name} (
                    key TEXT PRIMARY KEY,
                    value JSONB NOT NULL,
                    tags TEXT[] DEFAULT '{{}}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create indexes for performance
            cur.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{self.table_name}_tags 
                ON {self.table_name} USING GIN(tags)
            """)
            cur.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{self.table_name}_created 
                ON {self.table_name}(created_at DESC)
            """)
            
            self.conn.commit()

    def store(self, key: str, value: Dict[str, Any], tags: Optional[List[str]] = None) -> bool:
        """Store an entry in PostgreSQL and Redis cache.
        
        Args:
            key: Unique identifier for the entry
            value: Dictionary to store (will be JSON serialized)
            tags: Optional list of tags for search
            
        Returns:
            True if successful, False otherwise
        """
        if not self._initialized:
            return False

        try:
            tags = tags or []
            value_json = json.dumps(value)
            
            with self.conn.cursor() as cur:
                cur.execute(f"""
                    INSERT INTO {self.table_name} (key, value, tags, updated_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (key) 
                    DO UPDATE SET 
                        value = EXCLUDED.value,
                        tags = EXCLUDED.tags,
                        updated_at = EXCLUDED.updated_at
                """, (key, value_json, tags, datetime.now()))
                
            self.conn.commit()
            
            # Update Redis cache
            if self.redis_client:
                try:
                    cache_key = f"vault:{key}"
                    cache_value = {
                        'key': key,
                        'value': value,
                        'tags': tags,
                        'created_at': datetime.now().isoformat()
                    }
                    self.redis_client.setex(
                        cache_key, 
                        3600,  # 1 hour TTL
                        json.dumps(cache_value)
                    )
                except Exception as e:
                    logger.warning(f"Redis cache update failed: {e}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to store entry {key}: {e}")
            if self.conn:
                self.conn.rollback()
            return False

    def retrieve(self, key: str) -> Optional[Dict[str, Any]]:
        """Retrieve a single entry by key.
        
        Args:
            key: The entry key
            
        Returns:
            Dictionary with keys: key, value, tags, created_at, or None
        """
        if not self._initialized:
            return None

        # Try Redis cache first
        if self.redis_client:
            try:
                cache_key = f"vault:{key}"
                cached = self.redis_client.get(cache_key)
                if cached:
                    logger.debug(f"Cache hit for key: {key}")
                    return json.loads(cached)
            except Exception as e:
                logger.warning(f"Redis cache read failed: {e}")

        # Fallback to PostgreSQL
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(f"""
                    SELECT key, value, tags, created_at
                    FROM {self.table_name}
                    WHERE key = %s
                """, (key,))
                
                row = cur.fetchone()
                if row:
                    result = {
                        'key': row['key'],
                        'value': row['value'],  # Already deserialized by JSONB
                        'tags': row['tags'],
                        'created_at': row['created_at'].isoformat()
                    }
                    
                    # Warm Redis cache
                    if self.redis_client:
                        try:
                            cache_key = f"vault:{key}"
                            self.redis_client.setex(cache_key, 3600, json.dumps(result))
                        except Exception as e:
                            logger.warning(f"Redis cache write failed: {e}")
                    
                    return result
                
        except Exception as e:
            logger.error(f"Failed to retrieve entry {key}: {e}")
        
        return None

    def search_by_tags(self, tags: List[str], limit: int = 100) -> List[Dict[str, Any]]:
        """Search entries by tags.
        
        Args:
            tags: List of tags to search for (OR logic)
            limit: Maximum number of results
            
        Returns:
            List of dictionaries with keys: key, value, tags, created_at
        """
        if not self._initialized or not tags:
            return []

        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Search for entries with ANY of the provided tags
                cur.execute(f"""
                    SELECT key, value, tags, created_at
                    FROM {self.table_name}
                    WHERE tags && %s
                    ORDER BY created_at DESC
                    LIMIT %s
                """, (tags, limit))
                
                results = []
                for row in cur.fetchall():
                    results.append({
                        'key': row['key'],
                        'value': row['value'],  # Already deserialized by JSONB
                        'tags': row['tags'],
                        'created_at': row['created_at'].isoformat()
                    })
                
                return results
                
        except Exception as e:
            logger.error(f"Failed to search by tags {tags}: {e}")
            return []

    def delete(self, key: str) -> bool:
        """Delete an entry.
        
        Args:
            key: The entry key
            
        Returns:
            True if successful, False otherwise
        """
        if not self._initialized:
            return False

        try:
            with self.conn.cursor() as cur:
                cur.execute(f"""
                    DELETE FROM {self.table_name}
                    WHERE key = %s
                """, (key,))
                
            self.conn.commit()
            
            # Invalidate Redis cache
            if self.redis_client:
                try:
                    cache_key = f"vault:{key}"
                    self.redis_client.delete(cache_key)
                except Exception as e:
                    logger.warning(f"Redis cache invalidation failed: {e}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete entry {key}: {e}")
            if self.conn:
                self.conn.rollback()
            return False

    def close(self):
        """Close database connections."""
        if self.conn:
            self.conn.close()
            self.conn = None
        if self.redis_client:
            self.redis_client.close()
            self.redis_client = None
        self._initialized = False
        logger.info("PostgreSQL backend closed")
