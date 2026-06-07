#!/bin/bash
set -e
cd /opt/Beamax
git pull origin master

# Rebuild and restart (volume-mounted code, rebuild only if Dockerfile changed)
docker compose up -d bea --build

# Wait for healthy
echo "Waiting for Bea to start..."
for i in $(seq 1 30); do
  if curl -sf http://localhost:8000/api/health > /dev/null 2>&1; then
    echo "✅ Bea is healthy!"
    exit 0
  fi
  sleep 2
done

echo "❌ Bea did not start within 60s"
exit 1
