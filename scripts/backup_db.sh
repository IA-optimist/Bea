#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────
# backup_db.sh — Daily backup of JarvisMax databases
# ──────────────────────────────────────────────────────────────────
# Usage (sur VPS1, root) :
#   bash scripts/backup_db.sh                     # run once
#   # or install via cron :
#   (crontab -l 2>/dev/null; echo "0 3 * * * /root/Jarvismax-master/scripts/backup_db.sh >> /var/log/jarvis_backup.log 2>&1") | crontab -
#
# What it backs up :
#   1. PostgreSQL (jarvismax database) → pg_dump (compressed)
#   2. Redis (if persistent data present) → RDB dump
#   3. Canonical missions SQLite (~/.jarvismax/canonical.db)
#   4. .env (encrypted with age if age keypair present ; else restrictive perms)
#
# Retention : keeps 7 daily + 4 weekly + 3 monthly locally.
# Optional off-site sync (rsync/rclone) if BACKUP_REMOTE env is set.
# ──────────────────────────────────────────────────────────────────
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/root/jarvismax-backups}"
CONTAINER_PG="${CONTAINER_PG:-postgres}"
CONTAINER_REDIS="${CONTAINER_REDIS:-redis}"
DATA_DIR="${DATA_DIR:-/root/.jarvismax}"
ENV_FILE="${ENV_FILE:-/root/Jarvismax-master/.env}"
REPO_DIR="${REPO_DIR:-/root/Jarvismax-master}"
TS="$(date +%Y%m%d-%H%M%S)"
DATE_TAG="$(date +%Y%m%d)"
DOW="$(date +%u)"          # 1=Mon … 7=Sun
DOM="$(date +%d)"
RETENTION_DAILY=7
RETENTION_WEEKLY=4
RETENTION_MONTHLY=3

log()  { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
die()  { printf '[ERROR] %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "must run as root"
command -v docker >/dev/null || die "docker not found"

mkdir -p "$BACKUP_DIR/daily" "$BACKUP_DIR/weekly" "$BACKUP_DIR/monthly"
chmod 700 "$BACKUP_DIR"

# ── 1. PostgreSQL ────────────────────────────────────────────
log "Backing up PostgreSQL..."
PG_DUMP="$BACKUP_DIR/daily/pg_${TS}.sql.gz"
if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_PG}$"; then
  docker exec "$CONTAINER_PG" pg_dump -U jarvis jarvismax 2>/dev/null | gzip > "$PG_DUMP" \
    && log "  ✓ $PG_DUMP ($(du -h "$PG_DUMP" | cut -f1))" \
    || die "pg_dump failed"
  chmod 600 "$PG_DUMP"
else
  log "  ⚠ postgres container not running — skipped"
fi

# ── 2. Redis ────────────────────────────────────────────────
log "Backing up Redis..."
REDIS_DUMP="$BACKUP_DIR/daily/redis_${TS}.rdb"
if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_REDIS}$"; then
  docker exec "$CONTAINER_REDIS" redis-cli --rdb /tmp/dump.rdb >/dev/null 2>&1 || true
  if docker exec "$CONTAINER_REDIS" test -f /tmp/dump.rdb; then
    docker cp "${CONTAINER_REDIS}:/tmp/dump.rdb" "$REDIS_DUMP" \
      && log "  ✓ $REDIS_DUMP ($(du -h "$REDIS_DUMP" | cut -f1))"
    chmod 600 "$REDIS_DUMP"
  else
    log "  ⚠ redis dump not produced — skipped"
  fi
else
  log "  ⚠ redis container not running — skipped"
fi

# ── 3. Canonical missions SQLite ─────────────────────────────
log "Backing up canonical missions SQLite..."
CANON_DB="$DATA_DIR/canonical.db"
CANON_DUMP="$BACKUP_DIR/daily/canonical_${TS}.db.gz"
if [[ -f "$CANON_DB" ]]; then
  # Use sqlite3 .backup for crash-consistent snapshot if available, else cp
  if command -v sqlite3 >/dev/null; then
    TMP_CANON="$(mktemp --suffix=.db)"
    sqlite3 "$CANON_DB" ".backup $TMP_CANON"
    gzip -c "$TMP_CANON" > "$CANON_DUMP"
    rm -f "$TMP_CANON"
  else
    gzip -c "$CANON_DB" > "$CANON_DUMP"
  fi
  chmod 600 "$CANON_DUMP"
  log "  ✓ $CANON_DUMP ($(du -h "$CANON_DUMP" | cut -f1))"
else
  log "  ⚠ $CANON_DB not found — skipped"
fi

# ── 4. .env (age-encrypted if key present) ───────────────────
log "Backing up .env..."
ENV_DUMP="$BACKUP_DIR/daily/env_${TS}.tar"
if [[ -f "$ENV_FILE" ]]; then
  if command -v age >/dev/null && [[ -f "/root/.age/recipients" ]]; then
    age -R /root/.age/recipients -o "${ENV_DUMP}.age" "$ENV_FILE"
    chmod 600 "${ENV_DUMP}.age"
    log "  ✓ ${ENV_DUMP}.age (encrypted)"
  else
    tar -cf "$ENV_DUMP" -C "$(dirname "$ENV_FILE")" "$(basename "$ENV_FILE")"
    chmod 600 "$ENV_DUMP"
    log "  ✓ $ENV_DUMP (unencrypted — restrict filesystem access)"
  fi
fi

# ── 5. Weekly / monthly rotation ─────────────────────────────
if [[ "$DOW" == "7" ]]; then
  log "Promoting daily → weekly (Sunday)..."
  cp -p "$BACKUP_DIR/daily/pg_${TS}.sql.gz" "$BACKUP_DIR/weekly/pg_${DATE_TAG}.sql.gz" 2>/dev/null || true
  cp -p "$BACKUP_DIR/daily/canonical_${TS}.db.gz" "$BACKUP_DIR/weekly/canonical_${DATE_TAG}.db.gz" 2>/dev/null || true
fi
if [[ "$DOM" == "01" ]]; then
  log "Promoting daily → monthly (1st of month)..."
  cp -p "$BACKUP_DIR/daily/pg_${TS}.sql.gz" "$BACKUP_DIR/monthly/pg_${DATE_TAG}.sql.gz" 2>/dev/null || true
  cp -p "$BACKUP_DIR/daily/canonical_${TS}.db.gz" "$BACKUP_DIR/monthly/canonical_${DATE_TAG}.db.gz" 2>/dev/null || true
fi

# ── 6. Prune retention ───────────────────────────────────────
log "Pruning old backups..."
find "$BACKUP_DIR/daily"   -type f -mtime +$RETENTION_DAILY   -delete 2>/dev/null || true
find "$BACKUP_DIR/weekly"  -type f -mtime +$((7 * RETENTION_WEEKLY))  -delete 2>/dev/null || true
find "$BACKUP_DIR/monthly" -type f -mtime +$((31 * RETENTION_MONTHLY)) -delete 2>/dev/null || true

# ── 7. Off-site sync (optional) ──────────────────────────────
if [[ -n "${BACKUP_REMOTE:-}" ]]; then
  log "Syncing to off-site: $BACKUP_REMOTE"
  if command -v rclone >/dev/null && [[ "$BACKUP_REMOTE" == *:* ]]; then
    rclone sync "$BACKUP_DIR" "$BACKUP_REMOTE/jarvismax-backups" --checksum --transfers 4 || log "  ⚠ rclone sync failed"
  elif command -v rsync >/dev/null; then
    rsync -az --delete "$BACKUP_DIR/" "$BACKUP_REMOTE" || log "  ⚠ rsync failed"
  else
    log "  ⚠ no rclone/rsync — off-site skipped"
  fi
fi

# ── Summary ──────────────────────────────────────────────────
log "Backup complete."
log "Sizes :"
du -sh "$BACKUP_DIR/daily" "$BACKUP_DIR/weekly" "$BACKUP_DIR/monthly" 2>/dev/null | sed 's/^/  /'
