#!/bin/bash
# Script to start BeaMax with real-time dashboard

set -e

echo "=================================================="
echo "🚀 BeaMax Real-Time Dashboard Startup"
echo "=================================================="
echo ""

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Project root
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

echo -e "${BLUE}📁 Project root: $PROJECT_ROOT${NC}"
echo ""

# Check dependencies
echo -e "${YELLOW}🔍 Checking dependencies...${NC}"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found. Please install Python 3.8+"
    exit 1
fi
echo "✅ Python: $(python3 --version)"

# Check Node.js
if ! command -v node &> /dev/null; then
    echo "❌ Node.js not found. Please install Node.js 16+"
    exit 1
fi
echo "✅ Node.js: $(node --version)"

# Check npm
if ! command -v npm &> /dev/null; then
    echo "❌ npm not found. Please install npm"
    exit 1
fi
echo "✅ npm: $(npm --version)"

echo ""
echo -e "${YELLOW}📦 Installing Python dependencies...${NC}"
pip3 install -q psutil websockets fastapi uvicorn
echo "✅ Python dependencies installed"

echo ""
echo -e "${YELLOW}📦 Installing Frontend dependencies...${NC}"
cd frontend
if [ ! -d "node_modules" ]; then
    npm install
else
    echo "✅ node_modules already exists (skipping install)"
fi
cd "$PROJECT_ROOT"

echo ""
echo -e "${GREEN}🎉 All dependencies ready!${NC}"
echo ""

# Start backend
echo -e "${BLUE}🚀 Starting Backend API...${NC}"
echo "   Endpoint: http://localhost:8000"
echo "   WebSocket: ws://localhost:8000/ws/metrics"
echo ""

# Kill existing backend if running
pkill -f "uvicorn api.main:app" 2>/dev/null || true
sleep 1

# Start backend in background
nohup python3 -m uvicorn api.main:app --host 0.0.0.0 --port 8000 > logs/backend.log 2>&1 &
BACKEND_PID=$!
echo "✅ Backend started (PID: $BACKEND_PID)"
echo "   Logs: logs/backend.log"

# Wait for backend to be ready
echo ""
echo -e "${YELLOW}⏳ Waiting for backend to be ready...${NC}"
for i in {1..30}; do
    if curl -s http://localhost:8000/metrics/websocket/status > /dev/null 2>&1; then
        echo "✅ Backend is ready!"
        break
    fi
    echo -n "."
    sleep 1
    if [ $i -eq 30 ]; then
        echo ""
        echo "❌ Backend failed to start. Check logs/backend.log"
        exit 1
    fi
done

echo ""
echo -e "${BLUE}🚀 Starting Frontend (React + Vite)...${NC}"
echo "   URL: http://localhost:3000"
echo ""

cd frontend

# Kill existing frontend if running
pkill -f "vite" 2>/dev/null || true
sleep 1

# Start frontend in background
nohup npm run dev > ../logs/frontend.log 2>&1 &
FRONTEND_PID=$!
echo "✅ Frontend started (PID: $FRONTEND_PID)"
echo "   Logs: logs/frontend.log"

cd "$PROJECT_ROOT"

echo ""
echo "=================================================="
echo -e "${GREEN}✅ BeaMax Real-Time Dashboard Started!${NC}"
echo "=================================================="
echo ""
echo "📊 Dashboard: http://localhost:3000"
echo "🔌 API: http://localhost:8000"
echo "⚡ WebSocket: ws://localhost:8000/ws/metrics"
echo ""
echo "📝 Test WebSocket:"
echo "   curl http://localhost:8000/metrics/websocket/status"
echo "   curl http://localhost:8000/metrics/snapshot"
echo ""
echo "   Or open: tests/websocket_test.html"
echo ""
echo "🛑 Stop services:"
echo "   kill $BACKEND_PID $FRONTEND_PID"
echo "   pkill -f 'uvicorn api.main:app'"
echo "   pkill -f 'vite'"
echo ""
echo "📚 Documentation: docs/REALTIME_DASHBOARD.md"
echo "=================================================="
