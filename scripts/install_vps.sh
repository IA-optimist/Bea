#!/bin/bash
set -e

echo "🚀 BeaMax VPS Setup"

# System update
apt-get update && apt-get upgrade -y
apt-get install -y curl git ufw

# Docker
curl -fsSL https://get.docker.com | sh
apt-get install -y docker-compose-plugin

# Firewall
ufw allow 22
ufw allow 80
ufw allow 443
ufw deny 8000
ufw --force enable

# Clone repo
git clone https://github.com/UniTy01/Beamax /opt/beamax
cd /opt/beamax

# Setup .env
cp .env.example .env
echo ""
echo "⚠️  Edit /opt/beamax/.env with your values, then press ENTER to continue"
read

# Pull Ollama models
docker compose -f docker-compose.prod.yml up ollama -d
echo "Waiting for Ollama..."
sleep 15
docker exec $(docker compose -f docker-compose.prod.yml ps -q ollama) ollama pull llama3.1:8b
docker exec $(docker compose -f docker-compose.prod.yml ps -q ollama) ollama pull deepseek-coder-v2:16b
docker exec $(docker compose -f docker-compose.prod.yml ps -q ollama) ollama pull mistral:7b
docker exec $(docker compose -f docker-compose.prod.yml ps -q ollama) ollama pull dolphin-mixtral

# Start services
docker compose -f docker-compose.prod.yml up -d

# Wait for API
sleep 10

# Health check
curl -f http://localhost:8000/health && echo "✅ BeaMax is running!" || echo "❌ Health check failed"

echo "→ API: http://YOUR_IP:8000"
echo "→ Docs: http://YOUR_IP:8000/docs"
