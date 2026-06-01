#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python}"

"$PYTHON_BIN" -m pip install --upgrade pip
"$PYTHON_BIN" -m pip install -r requirements.txt
"$PYTHON_BIN" -m pip install pytest pytest-cov pytest-asyncio pytest-xdist

DATABASE_URL="${DATABASE_URL:-postgresql://jarvis:***@localhost:5432/jarvismax_test}" \
REDIS_URL="${REDIS_URL:-redis://localhost:6379}" \
TESTING="${TESTING:-true}" \
pytest tests/ -v -n auto --dist=loadfile \
  --cov=core --cov-report=xml --cov-report=term \
  --cov-fail-under=55
