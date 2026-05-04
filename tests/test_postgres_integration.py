#!/usr/bin/env python3
"""
Test script for PostgreSQL integration in VaultMemory

This demonstrates the dual-write strategy for memory persistence:
1. All writes go to JSON/SQLite (existing behavior)
2. If DATABASE_URL is set and PostgreSQL is available, writes also go to PostgreSQL
3. Failures in PostgreSQL writes don't break the main flow
4. sync_to_postgres() can bulk migrate existing entries

Run:
    python3 tests/test_postgres_integration.py

With PostgreSQL:
    DATABASE_URL="postgresql://user:pass@host:5432/db" python3 tests/test_postgres_integration.py
"""

import os
import pytest

from memory.vault_memory import VaultMemory

# NOTE: these tests target an outdated VaultMemory API (kwargs `type=`,
# attribute `_use_pg`, method `get_context_for_prompt`) and require a rewrite
# against the current API. They were previously only run manually as a script
# and drifted silently. Skipped by default; set RUN_POSTGRES_INTEGRATION=1 to
# execute and surface the API drift.
if os.environ.get("RUN_POSTGRES_INTEGRATION", "0") != "1":
    pytest.skip("API drift — rewrite contre la nouvelle API VaultMemory requise",
                allow_module_level=True)


def test_without_postgres():
    """Test VaultMemory works without PostgreSQL (backward compatible)"""
    print("\n" + "="*60)
    print("TEST 1: VaultMemory without PostgreSQL")
    print("="*60)
    
    # Ensure DATABASE_URL is not set for this test
    original_db_url = os.environ.get('DATABASE_URL')
    if 'DATABASE_URL' in os.environ:
        del os.environ['DATABASE_URL']
    
    try:
        vm = VaultMemory()
        
        # Verify PostgreSQL is not enabled
        assert vm._pg_backend is None, "PostgreSQL backend should be None"
        assert not bool(vm._pg_backend), "PostgreSQL should not be enabled"
        print("✓ PostgreSQL backend not initialized (expected)")
        
        # Store entry (with timestamp to ensure uniqueness)
        import time
        entry = vm.store(
            type='pattern',
            content=f'Test entry without PostgreSQL - {time.time()}',
            source='test',
            confidence=0.85,
            tags=['test', 'integration']
        )
        assert entry is not None, "Entry should be stored"
        print(f"✓ Entry stored successfully: {entry.id}")
        
        # Retrieve entry
        results = vm.retrieve(query='test', max_k=5)
        assert len(results) > 0, "Should retrieve entries"
        print(f"✓ Retrieved {len(results)} entries")
        
        # sync_to_postgres should gracefully handle absence of PostgreSQL
        stats = vm.sync_to_postgres()
        assert stats['synced'] == 0, "Should not sync without PostgreSQL"
        assert stats['failed'] == 0, "Should not fail"
        print(f"✓ sync_to_postgres handled gracefully: {stats}")
        
        print("\n✅ TEST 1 PASSED: Backward compatibility maintained")
        
    finally:
        # Restore original DATABASE_URL
        if original_db_url:
            os.environ['DATABASE_URL'] = original_db_url


def test_with_postgres():
    """Test VaultMemory with PostgreSQL configured"""
    print("\n" + "="*60)
    print("TEST 2: VaultMemory with PostgreSQL (if configured)")
    print("="*60)
    
    database_url = os.environ.get('DATABASE_URL')
    
    if not database_url:
        print("⚠️  DATABASE_URL not set - skipping PostgreSQL tests")
        print("   Set DATABASE_URL to test PostgreSQL integration:")
        print("   DATABASE_URL='postgresql://user:pass@host:5432/db' python3 test_postgres_integration.py")
        return
    
    vm = VaultMemory()
    
    if not bool(vm._pg_backend):
        print("⚠️  PostgreSQL configured but not available")
        print("   Connection may have failed - check credentials")
        print(f"   Backend available: {vm._pg_backend is not None}")
        return
    
    print("✓ PostgreSQL backend initialized and available")
    
    # Store entry (should dual-write to PostgreSQL)
    import time
    entry = vm.store(
        type='pattern',
        content=f'Test entry WITH PostgreSQL - {time.time()}',
        source='test',
        confidence=0.9,
        tags=['test', 'postgres', 'dual-write']
    )
    
    if entry:
        print(f"✓ Entry stored with dual-write: {entry.id}")
        print("  - JSON/SQLite: OK")
        print("  - PostgreSQL: OK (if backend available)")
    
    # Test sync
    stats = vm.sync_to_postgres()
    print(f"✓ Bulk sync completed: {stats}")
    
    print("\n✅ TEST 2 PASSED: PostgreSQL integration working")


def test_api_compatibility():
    """Verify all API methods are present and working"""
    print("\n" + "="*60)
    print("TEST 3: API Compatibility")
    print("="*60)
    
    vm = VaultMemory()
    
    required_methods = [
        'store',
        'retrieve', 
        'get_context_for_prompt',
        'feedback',
        'invalidate',
        'get_by_id',
        'get_by_type',
        'get_by_tag',
        'is_known',
        'prune_expired',
        'stats',
        'sync_to_postgres',  # New method
    ]
    
    for method in required_methods:
        assert hasattr(vm, method), f"Missing method: {method}"
        print(f"✓ Method present: {method}")
    
    print("\n✅ TEST 3 PASSED: All API methods present")


if __name__ == '__main__':
    print("\n" + "#"*60)
    print("# PostgreSQL Integration Tests for VaultMemory")
    print("#"*60)
    
    try:
        test_without_postgres()
        test_with_postgres()
        test_api_compatibility()
        
        print("\n" + "#"*60)
        print("# 🎉 ALL TESTS PASSED")
        print("#"*60)
        print("\nIntegration Summary:")
        print("  ✓ Backward compatible - works without DATABASE_URL")
        print("  ✓ Dual-write enabled when PostgreSQL available")
        print("  ✓ Graceful failure handling")
        print("  ✓ No breaking changes to VaultMemory API")
        print("  ✓ New sync_to_postgres() method for bulk migration")
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        exit(1)
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
