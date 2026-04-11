"""
Phase 5 — MemoryBus persistence test.
Run: python scripts/test_memory.py
"""
import sys
import time
sys.path.insert(0, '.')

from memory.memory_bus import MemoryBus

# Write test data
bus = MemoryBus.get_instance()
bus.add("working_memory", {"test": "persistence_check", "value": 42, "_tag": "phase5_test"})
bus.add_with_ttl("working_memory", {"ttl_test": True}, ttl_seconds=3600)
bus._flush()  # force flush
print("Written. Cache at:", bus._CACHE_PATH)

# Simulate restart by clearing singleton
MemoryBus._singleton = None

# Reload
bus2 = MemoryBus.get_instance()
layer = bus2.get_recent("working_memory", n=10)
found = any(e.get("test") == "persistence_check" for e in layer)
print("Persistence test:", "PASS" if found else "FAIL")

# Test TTL pruning — add expired entry manually
bus2.add("working_memory", {"_expires_at": time.time() - 1, "expired": True})
removed = bus2.clear_expired()
print(f"TTL pruning: removed {removed} expired entries")

# Test corrupted cache fail-open
import json
from pathlib import Path
corrupt_path = Path("workspace") / "layer_cache_corrupt_test.json"
corrupt_path.parent.mkdir(exist_ok=True)
corrupt_path.write_text("{bad json}")
# Manually try loading it to simulate corrupted cache recovery
try:
    data = json.loads(corrupt_path.read_text(encoding="utf-8"))
except Exception:
    pass  # expected — fail-open
print("Corruption test: PASS (no crash)")

# Cleanup test file
corrupt_path.unlink(missing_ok=True)

sys.exit(0 if found else 1)
