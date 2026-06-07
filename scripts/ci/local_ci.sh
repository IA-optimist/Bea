#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python}"

echo "[1/4] Upgrade pip"
"$PYTHON_BIN" -m pip install --upgrade pip

echo "[2/4] Install runtime + test dependencies"
"$PYTHON_BIN" -m pip install -r requirements.txt
"$PYTHON_BIN" -m pip install pytest pytest-cov pytest-asyncio pytest-xdist ruff==0.15.8

echo "[3/4] Lint (same blocking linter as CI)"
ruff check .

echo "[4/4] Test with coverage gate (same as CI)"
DATABASE_URL="${DATABASE_URL:-postgresql://localhost:5432/beamax_test}" \
REDIS_URL="${REDIS_URL:-redis://localhost:6379}" \
TESTING="${TESTING:-true}" \
pytest tests/ -v -n auto --dist=loadfile \
  --cov=core --cov-report=xml --cov-report=term \
  --cov-fail-under=55

echo "✅ local_ci.sh completed successfully"
