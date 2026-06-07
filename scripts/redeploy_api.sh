#!/bin/bash
set -e
echo "[redeploy] Pulling latest code..."
git pull origin master
echo "[redeploy] Rebuilding bea container..."
docker-compose build bea
echo "[redeploy] Restarting..."
docker-compose up -d bea
echo "[redeploy] Waiting for health..."
sleep 5
curl -s http://localhost:8000/health | python3 -c "import sys,json; d=json.load(sys.stdin); print('OK' if d.get('status')=='ok' else 'FAIL')"
echo "[redeploy] Done."
