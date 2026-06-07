#!/usr/bin/env bash
# BEA MAX — Arrêt
echo "[Bea] Arrêt de la stack..."
docker compose down
echo "[✓] Stack arrêtée. Les données sont persistées dans les volumes Docker."
