#!/usr/bin/env python3
"""Simple test for VaultMemory retrieve() with cache-through pattern."""

from memory.vault_memory import VaultEntry, VaultMemory

print("=== Simple VaultMemory Test ===\n")

# Create VaultMemory
vm = VaultMemory(vault_path="/tmp/simple_test.json")
print(f"Created VaultMemory: {len(vm._entries)} entries in L1 cache")

# Store test entries
print("\nStoring 5 test entries...")
for i in range(5):
    entry = VaultEntry(
        key=f"entry_{i}",
        content=f"Test content number {i}",
        entry_type="test",
        tags=["test", f"tag_{i}"],
        confidence=0.5 + (i * 0.1)
    )
    vm.store(entry)

print(f"L1 cache now has {len(vm._entries)} entries")

# Test retrieval
print("\n--- Test 1: Retrieve all (empty query) ---")
results = vm.retrieve("", max_k=10)
print(f"Retrieved {len(results)} entries:")
for r in results:
    print(f"  {r.key}: confidence={r.confidence}")

print("\n--- Test 2: Retrieve with min_confidence=0.8 ---")
results = vm.retrieve("", min_confidence=0.8, max_k=10)
print(f"Retrieved {len(results)} entries:")
for r in results:
    print(f"  {r.key}: confidence={r.confidence}")

print("\n--- Test 3: Retrieve with query 'number 3' ---")
results = vm.retrieve("number 3", max_k=10)
print(f"Retrieved {len(results)} entries:")
for r in results:
    print(f"  {r.key}: {r.content}")

# Test cache statistics
print("\n--- Cache Statistics ---")
stats = vm.get_stats()
print(f"L1 entries: {stats['l1_entries']}")
print(f"PostgreSQL enabled: {stats['postgres_enabled']}")

vm.close()
print("\n✓ Test completed successfully")
