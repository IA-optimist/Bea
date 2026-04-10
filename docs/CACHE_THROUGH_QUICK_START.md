# VaultMemory Cache-Through Pattern - Quick Start

## Installation

```bash
# Install dependencies
pip install psycopg2-binary redis

# Optional: Set up PostgreSQL
createdb hermes
```

## Usage

### Basic Example
```python
from memory.vault_memory import VaultEntry, VaultMemory

# Initialize (JSON only)
vm = VaultMemory()

# Initialize with PostgreSQL + Redis
vm = VaultMemory(
    postgres_connection="postgresql://user:pass@localhost/hermes",
    redis_url="redis://localhost:6379/0"
)

# Store entry (dual-write to all layers)
entry = VaultEntry(
    key="my_memory",
    content="Important information",
    entry_type="memory",
    tags=["important", "work"],
    confidence=0.9
)
vm.store(entry)

# Retrieve (cache-through pattern)
results = vm.retrieve(
    query="important",
    tags_filter=["work"],
    max_k=10
)

# Get statistics
stats = vm.get_stats()
print(f"L1 entries: {stats['l1_entries']}")
print(f"PostgreSQL: {stats['postgres_enabled']}")

vm.close()
```

## Cache Flow

```
Query → L1 (memory) → [if miss] → L2 (PostgreSQL + Redis) → Warm L1 → Return
```

## Key Methods

### store(entry: VaultEntry) → bool
Writes to ALL layers (L1 + L2 + JSON)

### retrieve(query, type_filter, tags_filter, min_confidence, max_k) → List[VaultEntry]
Reads from L1 first, fallback to L2, warms L1 cache

### get_stats() → Dict[str, Any]
Returns cache statistics

### close()
Clean shutdown, saves L1 to JSON

## Environment Variables

```bash
export POSTGRES_CONNECTION="postgresql://user:pass@localhost/hermes"
export REDIS_URL="redis://localhost:6379/0"  # Optional
```

## Testing

```bash
# Run comprehensive tests
python3 test_cache_through.py

# Run simple tests
python3 simple_test.py
```

## Performance

- **L1 Hit**: ~1-10 μs (in-memory)
- **L2 Hit (Redis)**: ~1-5 ms (cached)
- **L2 Hit (PostgreSQL)**: ~10-50 ms (database)

## Troubleshooting

### PostgreSQL not available
→ Falls back to JSON-only mode (no errors)

### Redis not available
→ Falls back to PostgreSQL without cache (slower but works)

### No results found
→ Check filters, query string, and data was stored with dual-write

## Features

✓ Multi-tier caching (L1 → L2 fallback)  
✓ Cache warming (L2 → L1 population)  
✓ Filter preservation across layers  
✓ Observability logging  
✓ Graceful degradation  
✓ Backwards compatible  

## See Also

- [CACHE_THROUGH_IMPLEMENTATION.md](CACHE_THROUGH_IMPLEMENTATION.md) - Full documentation
- [memory/vault_memory.py](memory/vault_memory.py) - Source code
- [memory/postgres_backend.py](memory/postgres_backend.py) - PostgreSQL backend
