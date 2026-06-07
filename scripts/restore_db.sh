#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────
# restore_db.sh — Restore BeaMax databases from a backup
# ──────────────────────────────────────────────────────────────────
# Usage :
#   bash scripts/restore_db.sh <backup_timestamp>
#
# Example :
#   bash scripts/restore_db.sh 20260421-030000
#
# Or to pick the latest daily backup interactively :
#   bash scripts/restore_db.sh latest
#
# What it does :
#   1. Stops bea_core container (avoid writes during restore)
#   2. Restores PostgreSQL from pg_dump
#   3. Restores Redis from RDB
#   4. Restores canonical.db from SQLite dump
#   5. (Does NOT restore .env automatically ; operator must decide)
#   6. Restarts bea_core + verifies health
#
# Safety :
#   - Requires explicit confirmation
#   - Takes a pre-restore snapshot of current state (double backup)
#   - Can rollback to pre-restore state on failure
# ──────────────────────────────────────────────────────────────────
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/root/beamax-backups}"
CONTAINER_PG="${CONTAINER_PG:-postgres}"
CONTAINER_REDIS="${CONTAINER_REDIS:-redis}"
CONTAINER_CORE="${CONTAINER_CORE:-bea_core}"
DATA_DIR="${DATA_DIR:-/root/.beamax}"
HEALTH_URL="${HEALTH_URL:-http://localhost:8000/api/v2/health}"

red()    { printf '\033[0;31m%s\033[0m\n' "$*" >&2; }
green()  { printf '\033[0;32m%s\033[0m\n' "$*"; }
blue()   { printf '\033[0;34m%s\033[0m\n' "$*"; }
yellow() { printf '\033[0;33m%s\033[0m\n' "$*"; }
die()    { red "✗ $*"; exit 1; }

confirm() {
  read -r -p "$(yellow "$* [y/N] ")" a
  [[ "$a" =~ ^[Yy]$ ]] || die "aborted"
}

[[ $EUID -eq 0 ]] || die "must run as root"
[[ $# -ge 1 ]]   || die "usage: bash scripts/restore_db.sh <timestamp|latest>"

TARGET="$1"

# ── Resolve target timestamp ─────────────────────────────────
if [[ "$TARGET" == "latest" ]]; then
  TS=$(ls -1 "$BACKUP_DIR/daily" 2>/dev/null | grep -oE '[0-9]{8}-[0-9]{6}' | sort -u | tail -1)
  [[ -z "$TS" ]] && die "no backups found in $BACKUP_DIR/daily"
  blue "Latest backup timestamp: $TS"
else
  TS="$TARGET"
fi

PG_DUMP="$BACKUP_DIR/daily/pg_${TS}.sql.gz"
REDIS_DUMP="$BACKUP_DIR/daily/redis_${TS}.rdb"
CANON_DUMP="$BACKUP_DIR/daily/canonical_${TS}.db.gz"

blue "════════════════════════════════════════════════════════════"
blue "  BeaMax Restore — target=$TS"
blue "════════════════════════════════════════════════════════════"
echo
echo "Will attempt to restore :"
[[ -f "$PG_DUMP"    ]] && echo "  ✓ $PG_DUMP"    || echo "  ✗ $PG_DUMP (missing)"
[[ -f "$REDIS_DUMP" ]] && echo "  ✓ $REDIS_DUMP" || echo "  - $REDIS_DUMP (missing, will skip)"
[[ -f "$CANON_DUMP" ]] && echo "  ✓ $CANON_DUMP" || echo "  - $CANON_DUMP (missing, will skip)"
echo
yellow "  ⚠ This will OVERWRITE the current databases."
yellow "  ⚠ Container $CONTAINER_CORE will be briefly stopped."
confirm "Proceed ?"

# ── Pre-restore snapshot ─────────────────────────────────────
PRE_TS="$(date +%Y%m%d-%H%M%S)-pre-restore"
PRE_LOG="/tmp/bea-pre-restore-${PRE_TS}.log"
blue "[0/5] Taking pre-restore snapshot tagged $PRE_TS (log: $PRE_LOG)..."
# Capture stderr to a log so the operator can inspect a failed pre-snapshot
# without losing the rollback safety net silently.
if ! bash "$(dirname "$0")/backup_db.sh" >"$PRE_LOG" 2>&1; then
  yellow "  ⚠ pre-restore snapshot exited non-zero — see $PRE_LOG"
  yellow "  ⚠ Without a valid snapshot, rollback after this restore will not be possible."
  confirm "  Continue anyway WITHOUT a guaranteed pre-snapshot ?"
fi

# ── Stop core container ──────────────────────────────────────
blue "[1/5] Stopping $CONTAINER_CORE..."
docker stop "$CONTAINER_CORE" >/dev/null 2>&1 || yellow "  (not running)"

# ── Restore PostgreSQL ───────────────────────────────────────
if [[ -f "$PG_DUMP" ]]; then
  blue "[2/5] Restoring PostgreSQL..."
  confirm "  DROP + recreate beamax DB ?"
  docker exec "$CONTAINER_PG" psql -U bea -c "DROP DATABASE IF EXISTS beamax;"
  docker exec "$CONTAINER_PG" psql -U bea -c "CREATE DATABASE beamax;"
  gunzip -c "$PG_DUMP" | docker exec -i "$CONTAINER_PG" psql -U bea beamax >/dev/null
  green "  ✓ restored"
else
  yellow "[2/5] Skipped (no pg dump)"
fi

# ── Restore Redis ────────────────────────────────────────────
if [[ -f "$REDIS_DUMP" ]]; then
  blue "[3/5] Restoring Redis..."
  docker stop "$CONTAINER_REDIS" >/dev/null 2>&1 || true
  # Redis needs the RDB to be in its data dir before restart
  docker cp "$REDIS_DUMP" "${CONTAINER_REDIS}:/data/dump.rdb"
  docker start "$CONTAINER_REDIS" >/dev/null
  sleep 2
  green "  ✓ restored"
else
  yellow "[3/5] Skipped (no redis dump)"
fi

# ── Restore canonical.db ─────────────────────────────────────
if [[ -f "$CANON_DUMP" ]]; then
  blue "[4/5] Restoring canonical missions SQLite..."
  mkdir -p "$DATA_DIR"
  cp -p "$DATA_DIR/canonical.db" "$DATA_DIR/canonical.db.pre-restore-$PRE_TS" 2>/dev/null || true
  gunzip -c "$CANON_DUMP" > "$DATA_DIR/canonical.db"
  chmod 600 "$DATA_DIR/canonical.db"
  green "  ✓ restored"
else
  yellow "[4/5] Skipped (no canonical dump)"
fi

# ── Restart + health ─────────────────────────────────────────
blue "[5/5] Restarting $CONTAINER_CORE + health check..."
docker start "$CONTAINER_CORE" >/dev/null
for i in {1..30}; do
  if curl -sf --max-time 3 "$HEALTH_URL" >/dev/null 2>&1; then
    green "  ✓ health OK after ${i}×2s"
    break
  fi
  [[ $i -eq 30 ]] && die "health check timeout after restore — inspect container logs"
  sleep 2
done

echo
green "════════════════════════════════════════════════════════════"
green "  RESTORE COMPLETE — source=$TS"
green "════════════════════════════════════════════════════════════"
echo
yellow "If something is wrong, rollback to pre-restore snapshot :"
echo "  bash scripts/restore_db.sh <timestamp-before-this-run>"
echo
echo "Check logs :"
echo "  docker logs -f $CONTAINER_CORE"
