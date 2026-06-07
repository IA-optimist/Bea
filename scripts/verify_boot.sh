#!/bin/bash
# verify_boot.sh — Post-startup verification script
# Usage: ./scripts/verify_boot.sh [base_url]
# Default base_url: http://localhost:8000

set -euo pipefail

BASE_URL="${1:-http://localhost:8000}"
MAX_WAIT=90
INTERVAL=3
# Admin password for auth — read from env or default to "admin" for dev probing
ADMIN_PASSWORD="${BEA_ADMIN_PASSWORD:-admin}"

echo "=== Bea Max Boot Verification ==="
echo "Target: $BASE_URL"
echo ""

# Step 1: Wait for /health
echo "1. Waiting for /health to respond..."
ELAPSED=0
until curl -sf "$BASE_URL/health" > /dev/null 2>&1; do
    if [ "$ELAPSED" -ge "$MAX_WAIT" ]; then
        echo "   FAILED: /health did not respond within ${MAX_WAIT}s"
        exit 1
    fi
    sleep "$INTERVAL"
    ELAPSED=$((ELAPSED + INTERVAL))
done
echo "   OK — server is up after ${ELAPSED}s"

# Step 2: Check readiness probe
echo "2. Checking /api/v3/system/readiness..."
READINESS=$(curl -sf "$BASE_URL/api/v3/system/readiness" 2>/dev/null || echo '{"ok":false}')
READY=$(echo "$READINESS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',d).get('ready','false'))" 2>/dev/null || echo "false")

if [ "$READY" = "True" ] || [ "$READY" = "true" ]; then
    echo "   OK — system is ready"
    echo "   Probes: $(echo "$READINESS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',d).get('probes',{}))" 2>/dev/null)"
else
    echo "   NOT READY — readiness probe failed"
    echo "   Response: $READINESS"
    echo ""
    echo "   Diagnose:"
    echo "   - Check OPENAI_API_KEY / ANTHROPIC_API_KEY / OPENROUTER_API_KEY"
    echo "   - Check Qdrant is running and QDRANT_HOST is correct"
    echo "   - Check logs: docker logs bea_test_core"
    exit 1
fi

# Step 2b: Authenticate to get a bearer token
echo "2b. Authenticating (admin)..."
AUTH_RESP=$(curl -sf -X POST "$BASE_URL/auth/token" \
    -d "username=admin&password=${ADMIN_PASSWORD}" 2>/dev/null || echo '{}')
TOKEN=$(echo "$AUTH_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('access_token',''))" 2>/dev/null || echo "")

if [ -z "$TOKEN" ]; then
    echo "   FAILED — could not obtain auth token"
    echo "   Response: $AUTH_RESP"
    echo "   Set BEA_ADMIN_PASSWORD env var to the correct admin password"
    exit 1
fi
echo "   OK — authenticated"

# Step 3: Submit a test mission
echo "3. Submitting test mission..."
SUBMIT=$(curl -sf -X POST "$BASE_URL/api/v3/missions" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $TOKEN" \
    -d '{"goal":"Return only the number 42."}' 2>/dev/null || echo '{}')
MISSION_ID=$(echo "$SUBMIT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',d).get('mission_id',''))" 2>/dev/null || echo "")

if [ -z "$MISSION_ID" ]; then
    echo "   FAILED — no mission_id returned"
    echo "   Response: $SUBMIT"
    exit 1
fi
echo "   OK — mission submitted: $MISSION_ID"

# Step 4: Poll for terminal state
echo "4. Polling for mission result (timeout: ${MAX_WAIT}s)..."
ELAPSED=0
STATUS="CREATED"
until echo "$STATUS" | grep -qE "DONE|COMPLETED|FAILED|CANCELLED|REJECTED"; do
    if [ "$ELAPSED" -ge "$MAX_WAIT" ]; then
        echo "   TIMEOUT — mission stuck in status: $STATUS"
        echo "   Check logs for LLM errors"
        exit 1
    fi
    sleep "$INTERVAL"
    ELAPSED=$((ELAPSED + INTERVAL))
    POLL=$(curl -sf "$BASE_URL/api/v3/missions/$MISSION_ID" \
        -H "Authorization: Bearer $TOKEN" 2>/dev/null || echo '{}')
    STATUS=$(echo "$POLL" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',d).get('status','UNKNOWN'))" 2>/dev/null || echo "UNKNOWN")
    echo "   ... status: $STATUS (${ELAPSED}s elapsed)"
done

if [ "$STATUS" = "DONE" ] || [ "$STATUS" = "COMPLETED" ]; then
    echo "   Mission reached terminal state: $STATUS (${ELAPSED}s)"

    # Step 5: Validate result quality
    # With the ghost-DONE fix, a valid key should always produce real content.
    # An empty or trivially-short result here means the fix was bypassed — report it.
    echo "5. Validating result quality..."
    RESULT=$(echo "$POLL" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    data = d.get('data', d)
    r = data.get('result') or data.get('output') or data.get('summary') or ''
    print(str(r).strip())
except Exception:
    print('')
" 2>/dev/null || echo "")
    RESULT_LEN=${#RESULT}

    if [ "$RESULT_LEN" -lt 5 ]; then
        echo "   FAILED — mission COMPLETED but result is empty (${RESULT_LEN} chars)"
        echo "   The ghost-DONE guard was bypassed or the key is still invalid."
        echo "   Expected: with a bad key the mission should reach FAILED (not COMPLETED)."
        echo ""
        echo "   Diagnose:"
        echo "   - Verify ANTHROPIC_API_KEY / OPENROUTER_API_KEY is valid and has credits"
        echo "   - Check logs for: provider_auth_failure, all_agents_failed, execution_result_invalid"
        exit 1
    fi

    echo "   OK — result has ${RESULT_LEN} chars of content"
    echo "   Preview: $(echo "$RESULT" | head -c 120)"
    echo ""
    echo "=== BOOT VERIFICATION PASSED ==="
    echo "Bea Max is operational."
    exit 0

elif [ "$STATUS" = "FAILED" ]; then
    # Step 5: Retrieve failure reason — confirm it is a diagnosable failure (not a silent one)
    echo "5. Retrieving failure reason..."
    FAIL_REASON=$(echo "$POLL" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    data = d.get('data', d)
    r = data.get('error') or data.get('failure_reason') or data.get('error_class') or ''
    print(str(r).strip())
except Exception:
    print('')
" 2>/dev/null || echo "")

    echo "   FAILED — mission reached FAILED state (${ELAPSED}s)"
    echo "   Failure reason: ${FAIL_REASON:-<not available in API response>}"
    echo ""
    echo "   If this is expected (invalid key test): the fix is working correctly."
    echo "   If this is unexpected (valid key): check logs for provider_auth_failure / all_agents_failed"
    exit 1

else
    echo "   FAILED — mission ended with unexpected status: $STATUS"
    echo "   Check logs."
    exit 1
fi
