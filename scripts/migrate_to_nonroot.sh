#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────
# migrate_to_nonroot.sh — Migrate BeaMax container to non-root USER
# ──────────────────────────────────────────────────────────────────
# Usage (sur VPS1, root) :
#   cd /root/Beamax-master
#   git pull origin main
#   bash scripts/migrate_to_nonroot.sh
#
# Ce que ça fait :
#   1. Backup Dockerfile et docker-compose.yml actuels
#   2. Crée un user UID=1000 GID=1000 sur l'host si absent
#   3. chown ~/.beamax vers UID:GID 1000
#   4. Swap Dockerfile → Dockerfile.nonroot
#   5. Adapte docker-compose.yml : volume mount → /home/bea/.beamax
#   6. Rebuild image
#   7. Restart container
#   8. Smoke test health + logs
#   9. Rollback auto si smoke échoue
#
# Safe : backups systématiques, rollback in-script.
# ──────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_DIR="${REPO_DIR:-/root/Beamax-master}"
COMPOSE="${COMPOSE:-${REPO_DIR}/docker-compose.yml}"
DOCKERFILE="${DOCKERFILE:-${REPO_DIR}/Dockerfile}"
NONROOT_DF="${NONROOT_DF:-${REPO_DIR}/Dockerfile.nonroot}"
DATA_DIR="${DATA_DIR:-/root/.beamax}"
NEW_DATA_DIR="${NEW_DATA_DIR:-/home/bea/.beamax}"
CONTAINER="${CONTAINER:-bea_core}"
HEALTH_URL="${HEALTH_URL:-http://localhost:8000/api/v2/health}"
TS="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="${BACKUP_DIR:-/root/beamax-nonroot-migration.$TS}"

red()    { printf '\033[0;31m%s\033[0m\n' "$*" >&2; }
green()  { printf '\033[0;32m%s\033[0m\n' "$*"; }
blue()   { printf '\033[0;34m%s\033[0m\n' "$*"; }
yellow() { printf '\033[0;33m%s\033[0m\n' "$*"; }
die()    { red "✗ $*"; exit 1; }

confirm() {
  read -r -p "$(yellow "$* [y/N] ")" a
  [[ "$a" =~ ^[Yy]$ ]] || die "aborted"
}

rollback() {
  yellow "→ rolling back…"
  [[ -f "$BACKUP_DIR/Dockerfile" ]] && cp "$BACKUP_DIR/Dockerfile" "$DOCKERFILE"
  [[ -f "$BACKUP_DIR/docker-compose.yml" ]] && cp "$BACKUP_DIR/docker-compose.yml" "$COMPOSE"
  docker compose -f "$COMPOSE" up -d "$CONTAINER" || true
  red "rolled back. Review logs."
  exit 2
}

[[ $EUID -eq 0 ]] || die "must run as root"
[[ -d "$REPO_DIR" ]] || die "repo dir not found: $REPO_DIR"
[[ -f "$NONROOT_DF" ]] || die "Dockerfile.nonroot not found (git pull?)"

blue "════════════════════════════════════════════════════════════"
blue "  BeaMax → Non-root USER migration — $TS"
blue "════════════════════════════════════════════════════════════"
echo
echo "Repo         : $REPO_DIR"
echo "Data (old)   : $DATA_DIR  (owned by root)"
echo "Data (new)   : $NEW_DATA_DIR  (owned by UID=1000)"
echo "Container    : $CONTAINER"
echo "Backup dir   : $BACKUP_DIR"
echo
yellow "  ⚠ This will cause brief downtime during rebuild+restart."
yellow "  ⚠ Data will be migrated (NOT deleted). Rollback available."
echo
confirm "Proceed ?"

# ── Step 1: Backups ──────────────────────────────────────
blue "[1/9] Backing up config…"
mkdir -p "$BACKUP_DIR"
cp -p "$DOCKERFILE" "$BACKUP_DIR/Dockerfile"
cp -p "$COMPOSE"    "$BACKUP_DIR/docker-compose.yml"
green "  ✓ $BACKUP_DIR"

# ── Step 2: Host user ────────────────────────────────────
blue "[2/9] Ensuring UID=1000 exists on host…"
if id -u bea >/dev/null 2>&1; then
  EXISTING_UID=$(id -u bea)
  [[ "$EXISTING_UID" == "1000" ]] || die "user bea exists with UID=$EXISTING_UID (expected 1000)"
  green "  ✓ user bea (UID=1000) already exists"
else
  useradd --uid 1000 --user-group --create-home --shell /bin/bash bea
  green "  ✓ user bea created (UID=1000)"
fi

# ── Step 3: Migrate data ─────────────────────────────────
blue "[3/9] Migrating $DATA_DIR → $NEW_DATA_DIR…"
if [[ -d "$DATA_DIR" && ! -d "$NEW_DATA_DIR" ]]; then
  confirm "  Copy $DATA_DIR to $NEW_DATA_DIR (keeps original) ?"
  mkdir -p "$NEW_DATA_DIR"
  cp -a "$DATA_DIR/." "$NEW_DATA_DIR/"
  chown -R 1000:1000 "$NEW_DATA_DIR"
  green "  ✓ data copied + chowned UID:GID 1000"
elif [[ -d "$NEW_DATA_DIR" ]]; then
  chown -R 1000:1000 "$NEW_DATA_DIR"
  green "  ✓ $NEW_DATA_DIR already exists, re-chowned"
else
  mkdir -p "$NEW_DATA_DIR"
  chown -R 1000:1000 "$NEW_DATA_DIR"
  yellow "  ⚠ no prior data — fresh $NEW_DATA_DIR created"
fi

# ── Step 4: Swap Dockerfile ──────────────────────────────
blue "[4/9] Swapping Dockerfile → Dockerfile.nonroot…"
confirm "  Replace Dockerfile with Dockerfile.nonroot ?"
cp "$NONROOT_DF" "$DOCKERFILE"
green "  ✓ Dockerfile swapped"

# ── Step 5: Update compose volume ────────────────────────
blue "[5/9] Updating docker-compose.yml volume mount…"
if grep -q "~/.beamax:/root/.beamax" "$COMPOSE"; then
  sed -i 's|~/.beamax:/root/.beamax|~/.beamax:/home/bea/.beamax|g' "$COMPOSE"
  green "  ✓ volume mount updated"
elif grep -q "/home/bea/.beamax" "$COMPOSE"; then
  green "  ✓ volume mount already points to /home/bea/.beamax"
else
  yellow "  ⚠ no matching volume line found — check $COMPOSE manually"
fi

# ── Step 6: Rebuild ──────────────────────────────────────
blue "[6/9] Rebuilding Docker image (no-cache)…"
if ! docker compose -f "$COMPOSE" build --no-cache "$(basename "$REPO_DIR")" 2>&1 | tail -20; then
  if ! docker compose -f "$COMPOSE" build --no-cache 2>&1 | tail -20; then
    rollback
  fi
fi
green "  ✓ image built"

# ── Step 7: Restart ──────────────────────────────────────
blue "[7/9] Restarting container…"
confirm "  Stop + recreate $CONTAINER now ?"
docker compose -f "$COMPOSE" up -d --force-recreate "$CONTAINER" || rollback
green "  ✓ container recreated"

# ── Step 8: Health check ─────────────────────────────────
blue "[8/9] Waiting for health (max 60s)…"
for i in {1..30}; do
  if curl -sf --max-time 3 "$HEALTH_URL" >/dev/null 2>&1; then
    green "  ✓ health OK after ${i}×2s"
    break
  fi
  sleep 2
  [[ $i -eq 30 ]] && rollback
done

# ── Step 9: Verify non-root ──────────────────────────────
blue "[9/9] Verifying container runs as non-root…"
UID_IN_CONTAINER=$(docker exec "$CONTAINER" id -u 2>/dev/null || echo "?")
if [[ "$UID_IN_CONTAINER" == "1000" ]]; then
  green "  ✓ container UID=1000 (non-root)"
elif [[ "$UID_IN_CONTAINER" == "0" ]]; then
  red "  ✗ container still running as root — migration FAILED"
  rollback
else
  yellow "  ⚠ unexpected UID=$UID_IN_CONTAINER"
fi

# Check logs for permission issues
if docker logs --tail 50 "$CONTAINER" 2>&1 | grep -qE "Permission denied|PermissionError"; then
  red "  ✗ permission errors in logs — may need more chown fixes"
  docker logs --tail 20 "$CONTAINER" 2>&1 | grep -iE "permission" | head -5
  yellow "  Review + possibly rollback :"
  yellow "    cp $BACKUP_DIR/Dockerfile $DOCKERFILE"
  yellow "    cp $BACKUP_DIR/docker-compose.yml $COMPOSE"
  yellow "    docker compose -f $COMPOSE up -d --force-recreate $CONTAINER"
  exit 3
fi

# ── Done ─────────────────────────────────────────────────
echo
green "════════════════════════════════════════════════════════════"
green "  MIGRATION COMPLETE"
green "════════════════════════════════════════════════════════════"
echo
echo "  Container now runs as UID=1000 (non-root)."
echo "  Old data kept at : $DATA_DIR  (safe to delete after validation)"
echo "  New data at      : $NEW_DATA_DIR  (owned by UID=1000)"
echo
yellow "  Monitor for 24h. If issues, rollback :"
echo "    cp $BACKUP_DIR/Dockerfile $DOCKERFILE"
echo "    cp $BACKUP_DIR/docker-compose.yml $COMPOSE"
echo "    docker compose -f $COMPOSE up -d --force-recreate $CONTAINER"
echo "    chown -R root:root $DATA_DIR   # restore old ownership if needed"
