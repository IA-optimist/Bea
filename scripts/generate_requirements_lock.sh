#!/bin/bash
# =================================================================
# Generate requirements.lock from the canonical Python 3.12 Docker image.
#
# This produces a fully-pinned (==) lock file that makes builds
# 100% reproducible. Run this after any intentional dep upgrade.
#
# Usage:
#   bash scripts/generate_requirements_lock.sh
#   bash scripts/generate_requirements_lock.sh --image jarvismax-lock:py312
#   bash scripts/generate_requirements_lock.sh --no-build --image jarvismax-lock:py312
#
# Output:
#   requirements.lock  (commit this file)
#
# In the Dockerfile, swap:
#   pip install -r requirements.txt
# for:
#   pip install -r requirements.lock
# to enforce the exact lock on every build.
# =================================================================

set -euo pipefail

IMAGE="jarvismax-lock:py312"
LOCKFILE="requirements.lock"
BUILD=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --image)
      IMAGE="${2:?missing image after --image}"
      shift 2
      ;;
    --no-build)
      BUILD=0
      shift
      ;;
    *)
      echo "usage: $0 [--image IMAGE] [--no-build]" >&2
      exit 2
      ;;
  esac
done

echo "[generate_lock] Using image: $IMAGE"

if [[ "$BUILD" -eq 1 ]]; then
  docker build -f docker/Dockerfile -t "$IMAGE" .
fi

docker run --rm "$IMAGE" pip freeze \
  | grep -v '^-e' \
  | grep -v '^#' \
  > "$LOCKFILE"

echo "[generate_lock] Written: $LOCKFILE ($(wc -l < "$LOCKFILE") packages)"
echo "[generate_lock] Commit this file to freeze the build."
