"""VaultMemory: Unified memory storage with JSON + PostgreSQL backend.

Provides:
- In-memory cache (L1) for fast access via self._entries
- JSON file persistence for portability
- PostgreSQL backend (L2) for durability and search
- Redis cache (L0) via postgres_backend for distributed systems

Cache hierarchy:
1. L1: self._entries (in-memory dict, fastest)
2. L2: PostgreSQL with Redis L0 (postgres_backend handles this)
3. L3: JSON file (fallback for compatibility)
"""

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from memory.postgres_backend import PostgresBackend

logger = logging.getLogger(__name__)


@dataclass
class VaultEntry:
    """A single memory entry in the vault."""
    
    key: str
    content: str
    entry_type: str = "memory"  # memory, fact, context, skill, etc.
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert entry to dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VaultEntry':
        """Create entry from dictionary."""
        # Handle nested data structures
        if 'tags' not in data:
            data['tags'] = []
        if 'metadata' not in data:
            data['metadata'] = {}
        return cls(**data)


class VaultMemory:
    """Unified memory storage with multi-tier caching."""
    
    def __init__(self,
                 vault_path: Optional[str] = None,
                 postgres_connection: Optional[str] = None,
                 redis_url: Optional[str] = None):
        """Initialize VaultMemory.
        
        Args:
            vault_path: Path to JSON file for persistence
            postgres_connection: PostgreSQL connection string
            redis_url: Redis connection URL
        """
        # L1 cache: in-memory dictionary
        self._entries: Dict[str, VaultEntry] = {}
        
        # JSON file path
        self.vault_path = vault_path or os.path.expanduser("~/.hermes/vault_memory.json")
        
        # PostgreSQL backend (L2 with Redis L0)
        self._pg_backend: Optional[PostgresBackend] = None
        if postgres_connection:
            self._pg_backend = PostgresBackend(
                connection_string=postgres_connection,
                redis_url=redis_url,
                table_name="vault_entries"
            )
            if self._pg_backend.initialize():
                logger.info("PostgreSQL backend initialized for VaultMemory")
            else:
                logger.warning("PostgreSQL backend initialization failed, using JSON only")
                self._pg_backend = None
        
        # Load from JSON
        self._load_from_json()
        
        logger.info(f"VaultMemory initialized with {len(self._entries)} entries")
        logger.info(f"L1 (memory): {len(self._entries)} entries")
        logger.info(f"L2 (PostgreSQL): {'enabled' if self._pg_backend else 'disabled'}")
    
    def _load_from_json(self):
        """Load entries from JSON file into L1 cache."""
        if not os.path.exists(self.vault_path):
            logger.info(f"No vault file found at {self.vault_path}, starting fresh")
            return
        
        try:
            with open(self.vault_path, 'r') as f:
                data = json.load(f)
            
            for key, entry_dict in data.items():
                try:
                    self._entries[key] = VaultEntry.from_dict(entry_dict)
                except Exception as e:
                    logger.warning(f"Failed to load entry {key}: {e}")
            
            logger.info(f"Loaded {len(self._entries)} entries from {self.vault_path}")
            
        except Exception as e:
            logger.error(f"Failed to load vault from {self.vault_path}: {e}")
    
    def _save_to_json(self):
        """Save entries from L1 cache to JSON file."""
        try:
            # Create directory if needed
            os.makedirs(os.path.dirname(self.vault_path), exist_ok=True)
            
            # Convert entries to dict
            data = {key: entry.to_dict() for key, entry in self._entries.items()}
            
            # Write atomically
            temp_path = self.vault_path + ".tmp"
            with open(temp_path, 'w') as f:
                json.dump(data, f, indent=2)
            os.replace(temp_path, self.vault_path)
            
            logger.debug(f"Saved {len(self._entries)} entries to {self.vault_path}")
            
        except Exception as e:
            logger.error(f"Failed to save vault to {self.vault_path}: {e}")
    
    def store(self, entry: VaultEntry) -> bool:
        """Store an entry in all layers (L1 + L2 + JSON).
        
        Dual-write pattern: Write to both in-memory cache and PostgreSQL.
        
        Args:
            entry: VaultEntry to store
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Update timestamp
            entry.updated_at = datetime.now().isoformat()
            
            # Write to L1 cache (in-memory)
            self._entries[entry.key] = entry
            logger.debug(f"Stored entry {entry.key} to L1 cache")
            
            # Write to L2 (PostgreSQL)
            if self._pg_backend:
                try:
                    success = self._pg_backend.store(
                        key=entry.key,
                        value=entry.to_dict(),
                        tags=entry.tags
                    )
                    if success:
                        logger.debug(f"Stored entry {entry.key} to PostgreSQL")
                    else:
                        logger.warning(f"Failed to store entry {entry.key} to PostgreSQL")
                except Exception as e:
                    logger.error(f"PostgreSQL store failed for {entry.key}: {e}")
            
            # Write to JSON (L3)
            self._save_to_json()
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to store entry {entry.key}: {e}")
            return False
    
    def retrieve(self,
                 query: str,
                 type_filter: Optional[List[str]] = None,
                 tags_filter: Optional[List[str]] = None,
                 min_confidence: float = 0.0,
                 max_k: int = 10) -> List[VaultEntry]:
        """Retrieve entries with L1 → L2 fallback (cache-through pattern).
        
        Strategy:
        1. Search L1 cache (self._entries) first
        2. If insufficient results AND PostgreSQL available:
           - Query PostgreSQL for additional entries
           - Convert results to VaultEntry objects
           - Add to L1 cache (warm cache for future queries)
        3. Apply all filters and return top-k results
        
        Args:
            query: Search query (used for filtering, not semantic search yet)
            type_filter: Filter by entry types (e.g., ['memory', 'fact'])
            tags_filter: Filter by tags
            min_confidence: Minimum confidence threshold
            max_k: Maximum number of results
            
        Returns:
            List of matching VaultEntry objects, sorted by relevance
        """
        results = []
        l1_hits = 0
        l2_hits = 0
        
        # Step 1: Search L1 cache (in-memory)
        logger.debug(f"Searching L1 cache ({len(self._entries)} entries)")
        
        for entry in self._entries.values():
            # Apply filters
            if type_filter and entry.entry_type not in type_filter:
                continue
            if tags_filter and not any(tag in entry.tags for tag in tags_filter):
                continue
            if entry.confidence < min_confidence:
                continue
            
            # Simple relevance scoring (can be enhanced with embeddings later)
            # If no query or query matches content/tags/key, include the entry
            if not query or \
               query.lower() in entry.content.lower() or \
               query.lower() in ' '.join(entry.tags).lower() or \
               query.lower() in entry.key.lower():
                results.append(entry)
                l1_hits += 1
        
        logger.info(f"L1 cache hits: {l1_hits}")
        
        # Step 2: L2 fallback if needed and available
        if len(results) < max_k and self._pg_backend:
            try:
                logger.debug("Insufficient L1 results, querying PostgreSQL (L2)")
                
                # Build tag search from query + filters
                search_tags = tags_filter or []
                # Add query terms as potential tags
                query_terms = query.lower().split()
                search_tags.extend(query_terms)
                
                # Query PostgreSQL
                pg_results = self._pg_backend.search_by_tags(
                    tags=search_tags,
                    limit=max_k * 2  # Get extra for filtering
                )
                
                logger.debug(f"PostgreSQL returned {len(pg_results)} results")
                
                # Convert to VaultEntry and warm L1 cache
                for pg_entry in pg_results:
                    key = pg_entry['key']
                    
                    # Skip if already in L1 cache
                    if key in self._entries:
                        continue
                    
                    try:
                        # Deserialize value (PostgreSQL stores full VaultEntry as JSON)
                        entry_dict = pg_entry['value']
                        entry = VaultEntry.from_dict(entry_dict)
                        
                        # Apply filters
                        if type_filter and entry.entry_type not in type_filter:
                            continue
                        if tags_filter and not any(tag in entry.tags for tag in tags_filter):
                            continue
                        if entry.confidence < min_confidence:
                            continue
                        
                        # Add to L1 cache (cache warming)
                        self._entries[key] = entry
                        logger.debug(f"Warmed L1 cache with key: {key}")
                        
                        # Add to results
                        results.append(entry)
                        l2_hits += 1
                        
                    except Exception as e:
                        logger.warning(f"Failed to deserialize PostgreSQL entry {key}: {e}")
                
                logger.info(f"L2 cache hits: {l2_hits}")
                
                # Save warmed cache to JSON
                if l2_hits > 0:
                    self._save_to_json()
                
            except Exception as e:
                logger.error(f"PostgreSQL fallback failed: {e}")
                logger.info("Continuing with L1 results only")
        
        # Step 3: Sort and limit results
        # Sort by confidence (descending), then by updated_at (descending)
        results.sort(key=lambda e: (e.confidence, e.updated_at), reverse=True)
        results = results[:max_k]
        
        # Log cache statistics
        logger.info(f"Retrieved {len(results)} entries (L1: {l1_hits}, L2: {l2_hits})")
        
        return results
    
    def delete(self, key: str) -> bool:
        """Delete an entry from all layers.
        
        Args:
            key: Entry key to delete
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Delete from L1
            if key in self._entries:
                del self._entries[key]
                logger.debug(f"Deleted entry {key} from L1 cache")
            
            # Delete from L2
            if self._pg_backend:
                self._pg_backend.delete(key)
                logger.debug(f"Deleted entry {key} from PostgreSQL")
            
            # Save to JSON
            self._save_to_json()
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete entry {key}: {e}")
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """Get memory statistics.
        
        Returns:
            Dictionary with cache statistics
        """
        stats = {
            'l1_entries': len(self._entries),
            'postgres_enabled': self._pg_backend is not None,
            'vault_path': self.vault_path,
        }
        
        # Entry type breakdown
        type_counts = {}
        for entry in self._entries.values():
            type_counts[entry.entry_type] = type_counts.get(entry.entry_type, 0) + 1
        stats['entry_types'] = type_counts
        
        return stats
    
    def is_known(self, key: str) -> bool:
        """Check if a key exists in vault memory."""
        try:
            results = self.retrieve(query=key, limit=1)
            return len(results) > 0
        except Exception:
            return False

    def close(self):
        """Clean shutdown - save to JSON and close PostgreSQL."""
        logger.info("Closing VaultMemory")
        
        # Save L1 to JSON
        self._save_to_json()
        
        # Close PostgreSQL
        if self._pg_backend:
            self._pg_backend.close()
        
        logger.info("VaultMemory closed")


# ── Singleton helper ───────────────────────────────────────────────────────────
_vault_instance = None

def get_vault_memory() -> VaultMemory:
    global _vault_instance
    if _vault_instance is None:
        _vault_instance = VaultMemory()
    return _vault_instance
