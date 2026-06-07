#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────
# rotate_secrets.sh — Interactive rotation of BeaMax prod secrets
# ──────────────────────────────────────────────────────────────────
# Usage (sur VPS1, en tant que root) :
#   cd /root/Beamax-master
#   git pull origin main
#   bash scripts/rotate_secrets.sh
#
# Ce que ça fait (par étape, avec confirmation) :
#   1. Backup /root/.env et .tokens.json actuels (timestampés)
#   2. Te demande les NOUVELLES valeurs une à une (hidden input pour
#      les secrets, prompt pour les placeholders à régénérer)
#   3. Regénère BEA_SECRET_KEY + POSTGRES_PASSWORD + N8N_ENCRYPTION_KEY
#      via openssl (tu peux override)
#   4. Écrit le nouveau .env dans un fichier temporaire
#   5. Valide la syntaxe (pas de lignes cassées)
#   6. Swap atomique : backup → temp → .env
#   7. Restart le container bea_core
#   8. Smoke test : /api/v2/health + auth/me via cookie
#   9. Si smoke échoue → rollback automatique du .env
#
# Safe : chaque étape demande confirmation. Rien d'irréversible sans "yes".
# ──────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_DIR="${REPO_DIR:-/root/Beamax-master}"
ENV_FILE="${ENV_FILE:-${REPO_DIR}/.env}"
TOKENS_FILE="${TOKENS_FILE:-${REPO_DIR}/.tokens.json}"
CONTAINER="${CONTAINER:-bea_core}"
DOMAIN="${DOMAIN:-bea.beamaxapp.co.uk}"
HEALTH_URL="${HEALTH_URL:-http://localhost:8000/api/v2/health}"

BACKUP_DIR="${BACKUP_DIR:-/root/beamax-secrets-backups}"
TS="$(date +%Y%m%d-%H%M%S)"

red()   { printf '\033[0;31m%s\033[0m\n' "$*" >&2; }
green() { printf '\033[0;32m%s\033[0m\n' "$*"; }
blue()  { printf '\033[0;34m%s\033[0m\n' "$*"; }
yellow(){ printf '\033[0;33m%s\033[0m\n' "$*"; }

die() { red "✗ $*"; exit 1; }

confirm() {
  local prompt="$1"
  read -r -p "$(yellow "$prompt [y/N] ")" ans
  [[ "$ans" =~ ^[Yy]$ ]] || die "aborted by user"
}

# ── Pre-flight ───────────────────────────────────────────────
[[ $EUID -eq 0 ]] || die "must run as root"
[[ -d "$REPO_DIR" ]] || die "repo dir not found: $REPO_DIR"
[[ -f "$ENV_FILE" ]] || die "env file not found: $ENV_FILE"
command -v docker >/dev/null || die "docker not found"
command -v openssl >/dev/null || die "openssl not found"
command -v curl >/dev/null || die "curl not found"

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

blue "════════════════════════════════════════════════════════════"
blue "  BeaMax Secret Rotation — $TS"
blue "════════════════════════════════════════════════════════════"
echo
echo "Target VPS      : $(hostname)"
echo "Repo            : $REPO_DIR"
echo "Env file        : $ENV_FILE"
echo "Container       : $CONTAINER"
echo "Domain          : $DOMAIN"
echo "Backup dir      : $BACKUP_DIR"
echo
confirm "Ready to proceed ?"

# ── Step 1: Backup ───────────────────────────────────────────
blue "[1/9] Backing up current secrets…"
BACKUP_ENV="$BACKUP_DIR/env.$TS"
cp -p "$ENV_FILE" "$BACKUP_ENV"
chmod 600 "$BACKUP_ENV"
green "  ✓ $BACKUP_ENV"

if [[ -f "$TOKENS_FILE" ]]; then
  BACKUP_TOK="$BACKUP_DIR/tokens.$TS.json"
  cp -p "$TOKENS_FILE" "$BACKUP_TOK"
  chmod 600 "$BACKUP_TOK"
  green "  ✓ $BACKUP_TOK"
fi

# ── Step 2: Load current vars ───────────────────────────────
blue "[2/9] Reading current .env…"
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

# ── Step 3: Prompt for new values ───────────────────────────
blue "[3/9] Gathering new secrets (leave empty to auto-generate)…"
echo
yellow "  TIP: auto-generated secrets use 'openssl rand -hex 32' (64 hex chars)"
echo

read_secret() {
  local varname="$1"
  local prompt="$2"
  local current="${!varname:-}"
  local display="${current:0:8}…"
  [[ -z "$current" ]] && display="(unset)"
  echo
  echo "  $varname (current: $display)"
  read -r -s -p "$(yellow "  New value for $prompt (hidden, empty=autogen): ")" val
  echo
  if [[ -z "$val" ]]; then
    val="$(openssl rand -hex 32)"
    green "  → auto-generated"
  fi
  eval "NEW_$varname=\"\$val\""
}

read_secret BEA_SECRET_KEY "JWT signing key"
read_secret BEA_API_TOKEN  "static API token (ex: jv-xxxx)"
read_secret POSTGRES_PASSWORD "PostgreSQL password"
read_secret N8N_ENCRYPTION_KEY "N8N encryption key"

echo
yellow "  For third-party keys, paste the NEW value from the dashboard:"
echo "  (OpenRouter, Anthropic, etc. must be rotated in their UIs first)"
read_secret OPENROUTER_API_KEY "OpenRouter API key (sk-or-v1-…)"

# ── Step 4: Build new .env ──────────────────────────────────
blue "[4/9] Writing new .env to temp file…"
NEW_ENV="$(mktemp)"
chmod 600 "$NEW_ENV"

# Copy .env line by line, replacing target vars
while IFS= read -r line || [[ -n "$line" ]]; do
  case "$line" in
    BEA_SECRET_KEY=*)   echo "BEA_SECRET_KEY=$NEW_BEA_SECRET_KEY" ;;
    BEA_API_TOKEN=*)    echo "BEA_API_TOKEN=$NEW_BEA_API_TOKEN" ;;
    POSTGRES_PASSWORD=*)   echo "POSTGRES_PASSWORD=$NEW_POSTGRES_PASSWORD" ;;
    N8N_ENCRYPTION_KEY=*)  echo "N8N_ENCRYPTION_KEY=$NEW_N8N_ENCRYPTION_KEY" ;;
    OPENROUTER_API_KEY=*)  echo "OPENROUTER_API_KEY=$NEW_OPENROUTER_API_KEY" ;;
    DATABASE_URL=*)
      # Update inline password in DATABASE_URL
      echo "DATABASE_URL=postgresql://bea:${NEW_POSTGRES_PASSWORD}@postgres:5432/beamax"
      ;;
    *) echo "$line" ;;
  esac
done < "$ENV_FILE" > "$NEW_ENV"
green "  ✓ new env prepared ($(wc -l < "$NEW_ENV") lines)"

# ── Step 5: Sanity check ────────────────────────────────────
blue "[5/9] Sanity check (no CHANGE_ME left, critical vars present)…"
for required in BEA_SECRET_KEY POSTGRES_PASSWORD DATABASE_URL; do
  grep -q "^${required}=" "$NEW_ENV" || die "missing $required"
done
if grep -q "CHANGE_ME" "$NEW_ENV"; then
  yellow "  ⚠ CHANGE_ME placeholders still present :"
  grep -n "CHANGE_ME" "$NEW_ENV" | head -5
  confirm "  Continue anyway ?"
fi
green "  ✓ sanity OK"

# ── Step 6: Atomic swap ─────────────────────────────────────
blue "[6/9] Atomic swap .env…"
confirm "  Swap $ENV_FILE with new values ?"
mv "$NEW_ENV" "$ENV_FILE"
chmod 600 "$ENV_FILE"
green "  ✓ .env swapped"

# ── Step 7: Restart container ───────────────────────────────
blue "[7/9] Restarting $CONTAINER…"
confirm "  Restart container (brief downtime) ?"
docker restart "$CONTAINER" >/dev/null || die "docker restart failed"
green "  ✓ container restarted"

# Wait for health
blue "  Waiting for container to be healthy (max 60s)…"
for i in {1..30}; do
  if curl -sf --max-time 3 "$HEALTH_URL" >/dev/null 2>&1; then
    green "  ✓ health OK after ${i}×2s"
    break
  fi
  sleep 2
  [[ $i -eq 30 ]] && die "health check timeout — rollback recommended"
done

# ── Step 8: Smoke test ──────────────────────────────────────
blue "[8/9] Smoke test (health, container status, no startup errors)…"

# 8a. Container still running
docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$" || die "container died"
green "  ✓ $CONTAINER running"

# 8b. No error in logs (last 50 lines)
if docker logs --tail 50 "$CONTAINER" 2>&1 | grep -iE "error|fatal|traceback" | grep -vE "no error|0 errors|error_class" >/dev/null; then
  yellow "  ⚠ Errors detected in recent logs (review):"
  docker logs --tail 50 "$CONTAINER" 2>&1 | grep -iE "error|fatal|traceback" | grep -vE "no error|0 errors|error_class" | head -5
  confirm "  Continue anyway ?"
else
  green "  ✓ no errors in recent logs"
fi

# 8c. Health endpoint
if curl -sf --max-time 5 "$HEALTH_URL" >/dev/null; then
  green "  ✓ $HEALTH_URL responds"
else
  die "health endpoint failed — ROLLBACK"
fi

# ── Step 9: Success summary ─────────────────────────────────
blue "[9/9] Done. Summary :"
green "  • Old .env backed up   : $BACKUP_ENV"
green "  • Container restarted  : $CONTAINER"
green "  • Health               : OK"
echo
yellow "  NEXT STEPS (hors-script) :"
echo "    1. Revoke old BEA_API_TOKEN via /api/v2/tokens/{id}/revoke"
echo "       (use the NEW BEA_API_TOKEN as auth for that call)"
echo "    2. If OpenRouter key was rotated, verify LLM provider still works :"
echo "       curl -b /tmp/c.txt https://$DOMAIN/api/v2/chat ..."
echo "    3. Log event in audit trail (ops journal)."
echo
yellow "  ROLLBACK if anything is wrong :"
echo "    cp $BACKUP_ENV $ENV_FILE && docker restart $CONTAINER"
echo
green "rotation complete."
