#!/bin/bash
# Test Business Engine Activation
# Usage: bash scripts/test_business_engine.sh

set -e

echo "🚀 BUSINESS ENGINE TEST SUITE"
echo "================================"
echo ""

# Load token
TOKEN=$(grep "^BEA_API_TOKEN=" .env | cut -d'=' -f2)
API_BASE="http://localhost:8000"

echo "✅ Token loaded: ${TOKEN:0:15}..."
echo ""

# Test 1: List Business Actions
echo "📋 Test 1: List Business Actions"
ACTIONS=$(curl -s -H "Authorization: Bearer $TOKEN" "$API_BASE/api/v3/business-actions")
ACTION_COUNT=$(echo "$ACTIONS" | jq '.data | length')
echo "   Actions disponibles: $ACTION_COUNT"
echo "   $(echo "$ACTIONS" | jq -r '.data[].action_id')"
echo ""

# Test 2: Check SaaS MVP Spec Action
echo "🔍 Test 2: Check saas.mvp_spec Details"
SAAS_ACTION=$(curl -s -H "Authorization: Bearer $TOKEN" "$API_BASE/api/v3/business-actions/saas.mvp_spec")
echo "   $(echo "$SAAS_ACTION" | jq -r '.data | "\(.name) - \(.description[:80])"')"
echo ""

# Test 3: List Business Projects
echo "📁 Test 3: List Business Projects"
PROJECTS=$(ls -1 workspace/business/ 2>/dev/null | wc -l)
echo "   Projets créés: $PROJECTS"
ls -1 workspace/business/ 2>/dev/null | sed 's/^/   - /'
echo ""

# Test 4: Verify Business Engine Config
echo "⚙️  Test 4: Verify Configuration"
if grep -q "BUSINESS_ENGINE_ENABLED=true" .env; then
    echo "   ✅ BUSINESS_ENGINE_ENABLED=true"
else
    echo "   ❌ BUSINESS_ENGINE_ENABLED not set"
fi

if grep -q "BUSINESS_MODE" .env; then
    MODE=$(grep "BUSINESS_MODE" .env | cut -d'=' -f2)
    echo "   ✅ BUSINESS_MODE=$MODE"
else
    echo "   ⚠️  BUSINESS_MODE not set (defaults to TEST)"
fi

if grep -q "REVENUE_TARGET_MONTHLY" .env; then
    TARGET=$(grep "REVENUE_TARGET_MONTHLY" .env | cut -d'=' -f2)
    echo "   ✅ REVENUE_TARGET_MONTHLY=$TARGET EUR"
else
    echo "   ⚠️  REVENUE_TARGET_MONTHLY not set"
fi
echo ""

# Test 5: Count Generated Files
echo "📄 Test 5: Business Artifacts"
TOTAL_FILES=$(find workspace/business -type f \( -name "*.json" -o -name "*.md" \) 2>/dev/null | wc -l)
echo "   Fichiers générés: $TOTAL_FILES"
echo ""

# Test 6: API Health
echo "🏥 Test 6: API Health Check"
HEALTH=$(curl -s "$API_BASE/health" 2>/dev/null || echo '{"status":"unknown"}')
STATUS=$(echo "$HEALTH" | jq -r '.status // "unknown"')
echo "   API Status: $STATUS"
echo ""

# Test 7: Docker Containers
echo "🐳 Test 7: Docker Infrastructure"
CONTAINERS=$(docker ps --filter "name=bea" --format "{{.Names}}" | wc -l)
HEALTHY=$(docker ps --filter "name=bea" --filter "health=healthy" --format "{{.Names}}" | wc -l)
echo "   Containers: $HEALTHY/$CONTAINERS healthy"
echo ""

# Summary
echo "================================"
echo "📊 SUMMARY"
echo "================================"
echo "Business Actions:  $ACTION_COUNT/5 ✅"
echo "Projects Created:  $PROJECTS ✅"
echo "Files Generated:   $TOTAL_FILES ✅"
echo "Infrastructure:    $HEALTHY/$CONTAINERS healthy ✅"
echo ""

if [ "$ACTION_COUNT" -ge 5 ] && [ "$PROJECTS" -ge 2 ] && [ "$HEALTHY" -ge 6 ]; then
    echo "✅ BUSINESS ENGINE: OPERATIONAL"
    exit 0
else
    echo "⚠️  BUSINESS ENGINE: PARTIALLY OPERATIONAL"
    exit 1
fi
