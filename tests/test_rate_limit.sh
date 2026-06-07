#!/bin/bash
# Test rate limiting with concurrent requests

API_URL="${1:-http://localhost:8000}"
ENDPOINT="${2:-/api/v2/health}"
NUM_REQUESTS="${3:-150}"

echo "=== BeaMax Rate Limit Test ==="
echo "API: $API_URL"
echo "Endpoint: $ENDPOINT"
echo "Requests: $NUM_REQUESTS"
echo ""

echo "Sending $NUM_REQUESTS concurrent requests..."

# Sequential requests to test rate limit
SUCCESS=0
RATE_LIMITED=0

for i in $(seq 1 $NUM_REQUESTS); do
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$API_URL$ENDPOINT")
    
    if [ "$HTTP_CODE" = "200" ]; then
        SUCCESS=$((SUCCESS + 1))
        echo -n "."
    elif [ "$HTTP_CODE" = "429" ]; then
        RATE_LIMITED=$((RATE_LIMITED + 1))
        echo -n "R"
    else
        echo -n "E"
    fi
    
    # Small delay between requests
    sleep 0.05
done

echo ""
echo ""
echo "=== Results ==="
echo "✅ Successful: $SUCCESS"
echo "⚠️  Rate Limited: $RATE_LIMITED"
echo "❌ Errors: $(($NUM_REQUESTS - $SUCCESS - $RATE_LIMITED))"
echo ""

if [ $RATE_LIMITED -gt 0 ]; then
    echo "✅ Rate limiting is ACTIVE (expected ~50 rate limited with 100/min limit)"
else
    echo "⚠️  Rate limiting may not be working (0 requests blocked)"
fi

# Check rate limit headers
echo ""
echo "=== Rate Limit Headers ==="
curl -s -I "$API_URL$ENDPOINT" | grep -i "X-RateLimit" || echo "No rate limit headers found"
