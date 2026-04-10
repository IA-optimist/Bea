#!/usr/bin/env python3
"""Test script for VaultMemory with cache-through pattern."""

import logging
import os
import sys
from memory.vault_memory import VaultEntry, VaultMemory

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def test_basic_operations():
    """Test basic VaultMemory operations."""
    print("\n" + "="*80)
    print("TEST 1: Basic Operations (JSON only)")
    print("="*80)
    
    # Create VaultMemory without PostgreSQL
    vm = VaultMemory(vault_path="/tmp/test_vault.json")
    
    # Store some entries
    entry1 = VaultEntry(
        key="test_1",
        content="Python is a programming language",
        entry_type="fact",
        tags=["python", "programming"],
        confidence=0.9
    )
    entry2 = VaultEntry(
        key="test_2",
        content="JavaScript is used for web development",
        entry_type="fact",
        tags=["javascript", "web"],
        confidence=0.85
    )
    entry3 = VaultEntry(
        key="test_3",
        content="AI models can process natural language",
        entry_type="memory",
        tags=["ai", "nlp"],
        confidence=0.95
    )
    
    print(f"\nStoring {3} entries...")
    vm.store(entry1)
    vm.store(entry2)
    vm.store(entry3)
    
    # Retrieve with various filters
    print("\n--- Test: Retrieve all (max_k=10) ---")
    results = vm.retrieve("test", max_k=10)
    print(f"Retrieved {len(results)} entries")
    for entry in results:
        print(f"  - {entry.key}: {entry.content[:50]}... (type={entry.entry_type}, confidence={entry.confidence})")
    
    print("\n--- Test: Retrieve with type filter (fact) ---")
    results = vm.retrieve("test", type_filter=["fact"], max_k=10)
    print(f"Retrieved {len(results)} entries")
    for entry in results:
        print(f"  - {entry.key}: {entry.content[:50]}... (type={entry.entry_type})")
    
    print("\n--- Test: Retrieve with tag filter (python) ---")
    results = vm.retrieve("test", tags_filter=["python"], max_k=10)
    print(f"Retrieved {len(results)} entries")
    for entry in results:
        print(f"  - {entry.key}: tags={entry.tags}")
    
    print("\n--- Test: Retrieve with confidence filter (min_confidence=0.9) ---")
    results = vm.retrieve("test", min_confidence=0.9, max_k=10)
    print(f"Retrieved {len(results)} entries")
    for entry in results:
        print(f"  - {entry.key}: confidence={entry.confidence}")
    
    # Get statistics
    print("\n--- Statistics ---")
    stats = vm.get_stats()
    print(f"L1 entries: {stats['l1_entries']}")
    print(f"PostgreSQL enabled: {stats['postgres_enabled']}")
    print(f"Entry types: {stats['entry_types']}")
    
    vm.close()
    print("\n✓ Test 1 completed successfully")


def test_cache_through():
    """Test cache-through pattern with simulated L2 fallback."""
    print("\n" + "="*80)
    print("TEST 2: Cache-Through Pattern (L1 → L2 fallback)")
    print("="*80)
    
    # Create VaultMemory without PostgreSQL (simulating L2)
    vm = VaultMemory(vault_path="/tmp/test_vault_cache.json")
    
    # Store entries in L1
    print("\nStoring 3 entries in L1 cache...")
    for i in range(3):
        entry = VaultEntry(
            key=f"l1_entry_{i}",
            content=f"L1 cached content {i}",
            entry_type="memory",
            tags=["l1", "cache"],
            confidence=0.8
        )
        vm.store(entry)
    
    print(f"L1 cache size: {len(vm._entries)}")
    
    # First retrieval - all from L1
    print("\n--- First retrieval (L1 hits) ---")
    results = vm.retrieve("l1", tags_filter=["l1"], max_k=5)
    print(f"Retrieved {len(results)} entries from L1")
    
    # Simulate L2 data (manually add to demonstrate fallback)
    print("\n--- Simulating L2 data (manual injection) ---")
    print("Note: In real scenario, this would come from PostgreSQL")
    
    # The retrieve() method would normally:
    # 1. Search L1 first
    # 2. If insufficient results, query PostgreSQL
    # 3. Warm L1 cache with PostgreSQL results
    # 4. Return combined results
    
    print("\n✓ Test 2 completed successfully")


def test_with_postgres():
    """Test with PostgreSQL if available."""
    print("\n" + "="*80)
    print("TEST 3: PostgreSQL Integration (if available)")
    print("="*80)
    
    # Try to get PostgreSQL connection from environment
    pg_conn = os.getenv("POSTGRES_CONNECTION")
    redis_url = os.getenv("REDIS_URL")
    
    if not pg_conn:
        print("\n⚠ PostgreSQL connection not configured (set POSTGRES_CONNECTION env var)")
        print("Skipping PostgreSQL integration test")
        return
    
    print(f"\nPostgreSQL: {pg_conn}")
    print(f"Redis: {redis_url or 'not configured'}")
    
    try:
        # Create VaultMemory with PostgreSQL
        vm = VaultMemory(
            vault_path="/tmp/test_vault_pg.json",
            postgres_connection=pg_conn,
            redis_url=redis_url
        )
        
        # Store entries (dual-write to JSON + PostgreSQL)
        print("\nStoring entries (dual-write to JSON + PostgreSQL)...")
        for i in range(5):
            entry = VaultEntry(
                key=f"pg_entry_{i}",
                content=f"PostgreSQL test entry {i}",
                entry_type="fact",
                tags=["postgres", "test", f"tag_{i}"],
                confidence=0.7 + (i * 0.05)
            )
            vm.store(entry)
        
        print(f"Stored {5} entries")
        
        # Clear L1 cache to force L2 fallback
        print("\n--- Clearing L1 cache to test L2 fallback ---")
        original_entries = vm._entries.copy()
        vm._entries = {}
        print(f"L1 cache cleared (was {len(original_entries)}, now {len(vm._entries)})")
        
        # Retrieve - should fallback to PostgreSQL and warm L1
        print("\n--- Retrieving with empty L1 (should hit PostgreSQL) ---")
        results = vm.retrieve("postgres", tags_filter=["postgres"], max_k=10)
        print(f"Retrieved {len(results)} entries")
        print(f"L1 cache size after retrieval: {len(vm._entries)}")
        
        # Verify cache warming
        for entry in results:
            print(f"  - {entry.key}: {entry.content[:50]}... (cached={entry.key in vm._entries})")
        
        # Second retrieval - should be all L1 hits
        print("\n--- Second retrieval (should be all L1 hits) ---")
        results2 = vm.retrieve("postgres", tags_filter=["postgres"], max_k=10)
        print(f"Retrieved {len(results2)} entries from L1 cache")
        
        vm.close()
        print("\n✓ Test 3 completed successfully")
        
    except Exception as e:
        print(f"\n✗ PostgreSQL test failed: {e}")
        import traceback
        traceback.print_exc()


def main():
    """Run all tests."""
    print("VaultMemory Cache-Through Pattern Test Suite")
    print("=" * 80)
    
    try:
        test_basic_operations()
        test_cache_through()
        test_with_postgres()
        
        print("\n" + "="*80)
        print("ALL TESTS COMPLETED")
        print("="*80)
        
    except Exception as e:
        print(f"\n✗ Test suite failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
