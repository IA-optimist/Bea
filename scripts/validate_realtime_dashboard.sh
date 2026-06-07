#!/bin/bash
# Validation script for BeaMax Real-Time Dashboard

set -e

echo "=========================================="
echo "🔍 BeaMax Real-Time Dashboard Validator"
echo "=========================================="
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

ERRORS=0
WARNINGS=0

# Project root
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

echo -e "${YELLOW}📁 Project root: $PROJECT_ROOT${NC}"
echo ""

# Check backend files
echo "🔧 Checking backend files..."

if [ -f "api/routes/metrics_websocket.py" ]; then
    echo -e "${GREEN}✅ api/routes/metrics_websocket.py${NC}"
else
    echo -e "${RED}❌ api/routes/metrics_websocket.py NOT FOUND${NC}"
    ERRORS=$((ERRORS+1))
fi

if grep -q "metrics_websocket" api/main.py; then
    echo -e "${GREEN}✅ metrics_websocket imported in api/main.py${NC}"
else
    echo -e "${RED}❌ metrics_websocket NOT imported in api/main.py${NC}"
    ERRORS=$((ERRORS+1))
fi

echo ""
echo "🎨 Checking frontend files..."

if [ -f "frontend/src/hooks/useWebSocket.ts" ]; then
    echo -e "${GREEN}✅ frontend/src/hooks/useWebSocket.ts${NC}"
else
    echo -e "${RED}❌ frontend/src/hooks/useWebSocket.ts NOT FOUND${NC}"
    ERRORS=$((ERRORS+1))
fi

if [ -f "frontend/src/components/RealtimeChart.tsx" ]; then
    echo -e "${GREEN}✅ frontend/src/components/RealtimeChart.tsx${NC}"
else
    echo -e "${RED}❌ frontend/src/components/RealtimeChart.tsx NOT FOUND${NC}"
    ERRORS=$((ERRORS+1))
fi

if grep -q "useWebSocket" frontend/src/pages/Dashboard.tsx; then
    echo -e "${GREEN}✅ useWebSocket integrated in Dashboard.tsx${NC}"
else
    echo -e "${RED}❌ useWebSocket NOT integrated in Dashboard.tsx${NC}"
    ERRORS=$((ERRORS+1))
fi

if grep -q "RealtimeChart" frontend/src/pages/Dashboard.tsx; then
    echo -e "${GREEN}✅ RealtimeChart integrated in Dashboard.tsx${NC}"
else
    echo -e "${RED}❌ RealtimeChart NOT integrated in Dashboard.tsx${NC}"
    ERRORS=$((ERRORS+1))
fi

echo ""
echo "📚 Checking documentation..."

if [ -f "docs/REALTIME_DASHBOARD.md" ]; then
    echo -e "${GREEN}✅ docs/REALTIME_DASHBOARD.md${NC}"
else
    echo -e "${YELLOW}⚠️  docs/REALTIME_DASHBOARD.md NOT FOUND${NC}"
    WARNINGS=$((WARNINGS+1))
fi

if [ -f "REALTIME_DASHBOARD_QUICKSTART.md" ]; then
    echo -e "${GREEN}✅ REALTIME_DASHBOARD_QUICKSTART.md${NC}"
else
    echo -e "${YELLOW}⚠️  REALTIME_DASHBOARD_QUICKSTART.md NOT FOUND${NC}"
    WARNINGS=$((WARNINGS+1))
fi

if [ -f "REALTIME_DASHBOARD_SUMMARY.md" ]; then
    echo -e "${GREEN}✅ REALTIME_DASHBOARD_SUMMARY.md${NC}"
else
    echo -e "${YELLOW}⚠️  REALTIME_DASHBOARD_SUMMARY.md NOT FOUND${NC}"
    WARNINGS=$((WARNINGS+1))
fi

echo ""
echo "🧪 Checking test files..."

if [ -f "tests/test_realtime_websocket.py" ]; then
    echo -e "${GREEN}✅ tests/test_realtime_websocket.py${NC}"
else
    echo -e "${YELLOW}⚠️  tests/test_realtime_websocket.py NOT FOUND${NC}"
    WARNINGS=$((WARNINGS+1))
fi

if [ -f "tests/websocket_test.html" ]; then
    echo -e "${GREEN}✅ tests/websocket_test.html${NC}"
else
    echo -e "${YELLOW}⚠️  tests/websocket_test.html NOT FOUND${NC}"
    WARNINGS=$((WARNINGS+1))
fi

echo ""
echo "📦 Checking dependencies..."

# Check Python import
if python3 -c "from api.routes.metrics_websocket import router" 2>/dev/null; then
    echo -e "${GREEN}✅ Python backend imports OK${NC}"
else
    echo -e "${RED}❌ Python backend import failed${NC}"
    ERRORS=$((ERRORS+1))
fi

# Check if psutil is installed
if python3 -c "import psutil" 2>/dev/null; then
    echo -e "${GREEN}✅ psutil installed${NC}"
else
    echo -e "${YELLOW}⚠️  psutil NOT installed (optional but recommended)${NC}"
    echo "   Install with: pip install psutil"
    WARNINGS=$((WARNINGS+1))
fi

# Check if websockets is installed
if python3 -c "import websockets" 2>/dev/null; then
    echo -e "${GREEN}✅ websockets installed${NC}"
else
    echo -e "${RED}❌ websockets NOT installed${NC}"
    echo "   Install with: pip install websockets"
    ERRORS=$((ERRORS+1))
fi

# Check frontend dependencies
if [ -f "frontend/package.json" ]; then
    if grep -q "recharts" frontend/package.json; then
        echo -e "${GREEN}✅ recharts in package.json${NC}"
    else
        echo -e "${RED}❌ recharts NOT in package.json${NC}"
        ERRORS=$((ERRORS+1))
    fi
else
    echo -e "${RED}❌ frontend/package.json NOT FOUND${NC}"
    ERRORS=$((ERRORS+1))
fi

echo ""
echo "🔧 Checking utility scripts..."

if [ -f "scripts/start_realtime_dashboard.sh" ]; then
    if [ -x "scripts/start_realtime_dashboard.sh" ]; then
        echo -e "${GREEN}✅ scripts/start_realtime_dashboard.sh (executable)${NC}"
    else
        echo -e "${YELLOW}⚠️  scripts/start_realtime_dashboard.sh exists but not executable${NC}"
        echo "   Make executable with: chmod +x scripts/start_realtime_dashboard.sh"
        WARNINGS=$((WARNINGS+1))
    fi
else
    echo -e "${YELLOW}⚠️  scripts/start_realtime_dashboard.sh NOT FOUND${NC}"
    WARNINGS=$((WARNINGS+1))
fi

echo ""
echo "=========================================="
echo "📊 Validation Summary"
echo "=========================================="
echo ""

if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo -e "${GREEN}✅ ALL CHECKS PASSED!${NC}"
    echo ""
    echo "🎉 Real-Time Dashboard is ready to use!"
    echo ""
    echo "Next steps:"
    echo "  1. Start services: ./scripts/start_realtime_dashboard.sh"
    echo "  2. Open dashboard: http://localhost:3000"
    echo "  3. Test WebSocket: python tests/test_realtime_websocket.py"
    echo ""
    exit 0
elif [ $ERRORS -eq 0 ]; then
    echo -e "${YELLOW}⚠️  VALIDATION COMPLETED WITH WARNINGS${NC}"
    echo ""
    echo "Warnings: $WARNINGS"
    echo ""
    echo "The dashboard should work but some optional components are missing."
    echo ""
    exit 0
else
    echo -e "${RED}❌ VALIDATION FAILED${NC}"
    echo ""
    echo "Errors: $ERRORS"
    echo "Warnings: $WARNINGS"
    echo ""
    echo "Please fix the errors above before using the dashboard."
    echo ""
    exit 1
fi
