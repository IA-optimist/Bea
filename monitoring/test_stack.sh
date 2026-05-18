#!/bin/bash
# Test de la stack monitoring JarvisMax

set -e

echo "=========================================="
echo "🧪 Test de la Stack Monitoring JarvisMax"
echo "=========================================="
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test function
test_endpoint() {
    local name=$1
    local url=$2
    local expected=$3
    
    echo -n "Testing $name... "
    
    if response=$(curl -s -m 5 "$url" 2>/dev/null); then
        if [[ "$response" == *"$expected"* ]]; then
            echo -e "${GREEN}✓ OK${NC}"
            return 0
        else
            echo -e "${RED}✗ FAILED${NC} (unexpected response)"
            return 1
        fi
    else
        echo -e "${RED}✗ FAILED${NC} (connection error)"
        return 1
    fi
}

# Test health function
test_health() {
    local name=$1
    local url=$2
    
    echo -n "Testing $name health... "
    
    if curl -sf -m 5 "$url" > /dev/null 2>&1; then
        echo -e "${GREEN}✓ HEALTHY${NC}"
        return 0
    else
        echo -e "${RED}✗ DOWN${NC}"
        return 1
    fi
}

echo "1️⃣  Checking Docker containers..."
echo "-----------------------------------"
cd /root/Jarvismax-master/monitoring
docker compose -f docker-compose-monitoring.yml ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"
echo ""

echo "2️⃣  Testing Prometheus..."
echo "-----------------------------------"
test_health "Prometheus" "http://localhost:9090/-/healthy"
test_endpoint "Prometheus API" "http://localhost:9090/api/v1/status/config" "prometheus.yml"
echo ""

echo "3️⃣  Testing Node Exporter..."
echo "-----------------------------------"
test_endpoint "Node Exporter" "http://localhost:9100/metrics" "node_cpu_seconds_total"
echo ""

echo "4️⃣  Testing Grafana..."
echo "-----------------------------------"
test_health "Grafana" "http://localhost:3002/api/health"
test_endpoint "Grafana Login" "http://localhost:3002/login" "Grafana"
echo ""

echo "5️⃣  Testing Alertmanager..."
echo "-----------------------------------"
test_health "Alertmanager" "http://localhost:9093/-/healthy"
echo ""

echo "6️⃣  Checking Prometheus Targets..."
echo "-----------------------------------"
targets=$(curl -s http://localhost:9090/api/v1/targets 2>/dev/null | jq -r '.data.activeTargets[] | "\(.labels.job): \(.health)"' 2>/dev/null)
if [ -n "$targets" ]; then
    echo "$targets" | while read line; do
        if [[ "$line" == *"up"* ]]; then
            echo -e "${GREEN}✓${NC} $line"
        else
            echo -e "${RED}✗${NC} $line"
        fi
    done
else
    echo -e "${YELLOW}⚠${NC} Could not fetch targets"
fi
echo ""

echo "7️⃣  Testing API Metrics..."
echo "-----------------------------------"
if curl -sf http://localhost:8000/metrics > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} API metrics endpoint accessible"
    metric_count=$(curl -s http://localhost:8000/metrics 2>/dev/null | grep -c "^[a-z]" || echo "0")
    echo "   Found $metric_count metrics"
else
    echo -e "${YELLOW}⚠${NC} API metrics endpoint not accessible (API may not be running)"
fi
echo ""

echo "8️⃣  Checking Grafana Dashboards..."
echo "-----------------------------------"
# This requires authentication, so we just check if provisioning directory exists
if [ -d "/root/Jarvismax-master/monitoring/grafana/dashboards" ]; then
    dashboard_count=$(ls -1 /root/Jarvismax-master/monitoring/grafana/dashboards/*.json 2>/dev/null | wc -l)
    echo -e "${GREEN}✓${NC} $dashboard_count dashboard files found"
    ls -1 /root/Jarvismax-master/monitoring/grafana/dashboards/*.json 2>/dev/null | xargs -n1 basename
else
    echo -e "${RED}✗${NC} Dashboard directory not found"
fi
echo ""

echo "9️⃣  Checking Firewall Rules..."
echo "-----------------------------------"
for port in 3002 9090 9093; do
    if ufw status | grep -q "$port"; then
        echo -e "${GREEN}✓${NC} Port $port is allowed in firewall"
    else
        echo -e "${YELLOW}⚠${NC} Port $port not found in firewall rules"
    fi
done
echo ""

echo "🔟 Testing External Access..."
echo "-----------------------------------"
echo "Testing from localhost (should work):"
for port in 3002 9090 9093; do
    if nc -z localhost $port 2>/dev/null; then
        echo -e "  ${GREEN}✓${NC} Port $port: Open"
    else
        echo -e "  ${RED}✗${NC} Port $port: Closed"
    fi
done
echo ""

echo "=========================================="
echo "📊 Access URLs:"
echo "=========================================="
echo "Grafana:      http://MONITORING_HOST:3002"
echo "              Username: admin"
echo "              Password: ${GRAFANA_ADMIN_PASSWORD}"
echo ""
echo "Prometheus:   http://MONITORING_HOST:9090"
echo "Alertmanager: http://MONITORING_HOST:9093"
echo "Node Exporter: http://MONITORING_HOST:9100"
echo ""
echo "=========================================="
echo "📝 Next Steps:"
echo "=========================================="
echo "1. Open Grafana in browser: http://MONITORING_HOST:3002"
echo "2. Login with admin / ${GRAFANA_ADMIN_PASSWORD}"
echo "3. Navigate to Dashboards > JarvisMax folder"
echo "4. Open any dashboard to see metrics"
echo ""
echo "For Telegram alerts:"
echo "1. Create a Telegram bot with @BotFather"
echo "2. Add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to .env"
echo "3. Restart API: docker compose restart api"
echo "4. Test: curl http://localhost:8000/api/v2/webhooks/test-telegram"
echo ""
echo "=========================================="
