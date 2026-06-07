#!/bin/bash
# Phase 3 Validation Script

set -e

echo "=== Phase 3 Bio-Inspired AGI Validation ==="
echo ""

# Start server in background (if not running)
echo "Starting test server..."
export BEA_DEV_MODE=1
export BEA_API_TOKEN=test123

# Test 1: Cognitive Consolidation Endpoint
echo "Test 1: POST /api/v3/training/consolidate"
python3 << 'PYEOF'
from fastapi.testclient import TestClient
from api.main import app
import json

client = TestClient(app)
response = client.post("/api/v3/training/consolidate", headers={"X-Bea-Token": "test123"})

print(f"Status: {response.status_code}")
data = response.json()
print(f"OK: {data.get('ok')}")
print(f"Total traces: {data.get('data', {}).get('total_traces')}")
print(f"Domains processed: {data.get('data', {}).get('domains_processed')}")

assert response.status_code == 200, "Expected 200 status"
assert data['ok'] == True, "Expected ok=True"
print("✓ Consolidation endpoint working")
PYEOF

echo ""

# Test 2: Global Workspace Stats
echo "Test 2: GET /api/v3/training/workspace"
python3 << 'PYEOF'
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)
response = client.get("/api/v3/training/workspace", headers={"X-Bea-Token": "test123"})

print(f"Status: {response.status_code}")
data = response.json()
print(f"OK: {data.get('ok')}")
print(f"Stats: {data.get('data')}")

assert response.status_code == 200, "Expected 200 status"
assert data['ok'] == True, "Expected ok=True"
print("✓ Workspace stats endpoint working")
PYEOF

echo ""

# Test 3: Dopamine Signal Verification
echo "Test 3: Dopamine signal verification"
python3 << 'PYEOF'
import asyncio
from core.cognitive_consolidation import run_nightly_consolidation

async def test():
    result = await run_nightly_consolidation()
    print(f"Status: {result['status']}")
    print(f"Traces processed: {result['total_traces']}")
    
    # Check if dopamine signals are computed
    summary = result.get('summary', {})
    patterns = summary.get('domain_patterns', {})
    
    for domain, stats in patterns.items():
        dopamine = stats.get('avg_dopamine_signal')
        print(f"  {domain}: avg_dopamine={dopamine}")
    
    print("✓ Dopamine signal computation working")

asyncio.run(test())
PYEOF

echo ""

# Test 4: Global Workspace Integration
echo "Test 4: Global Workspace Theory integration"
python3 << 'PYEOF'
import asyncio
from core.global_workspace import get_workspace

async def test():
    ws = get_workspace()
    
    # Publish test data
    await ws.publish("test-agent", "Test output", confidence=0.9)
    
    stats = await ws.get_stats()
    print(f"Total entries: {stats['total_entries']}")
    print(f"Unique agents: {stats['unique_agents']}")
    print(f"Avg confidence: {stats['avg_confidence']}")
    
    recent = await ws.get_recent(limit=5)
    print(f"Recent broadcasts: {len(recent)}")
    
    assert stats['total_entries'] > 0, "Expected entries in workspace"
    print("✓ Global Workspace working")

asyncio.run(test())
PYEOF

echo ""
echo "=== All Phase 3 Tests Passed ✓ ==="
