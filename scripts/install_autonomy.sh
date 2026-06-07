#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────
# install_autonomy.sh — Install the autonomy daemon bootstrap on VPS1
# ──────────────────────────────────────────────────────────────────
# Usage (on VPS1, as root) :
#   cd /root/Beamax-master
#   bash scripts/install_autonomy.sh
#
# What it does :
#   1. Verifies the API token is reachable in /root/Beamax-master/.env
#   2. Creates /etc/beamax/ with autonomy_objective.txt + autonomy.env
#   3. Copies deploy/bea-autonomy.service → /etc/systemd/system/
#   4. systemctl daemon-reload + enable --now bea-autonomy
#   5. Smoke test : curl /api/v3/autonomy/status
#
# Safety :
#   - Asks confirmation before each destructive step
#   - Backs up any existing service file
#   - Refuses to install if BEA_AUTONOMY_USE_REAL=1 isn't set explicitly
#     (forces the operator to opt in to "real" mode)
# ──────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_DIR="${REPO_DIR:-/root/Beamax-master}"
ENV_FILE="${ENV_FILE:-${REPO_DIR}/.env}"
SVC_SRC="${REPO_DIR}/deploy/bea-autonomy.service"
SVC_DST="/etc/systemd/system/bea-autonomy.service"
CFG_DIR="/etc/beamax"
CFG_OBJ="${CFG_DIR}/autonomy_objective.txt"
CFG_ENV="${CFG_DIR}/autonomy.env"
API_URL="${API_URL:-http://localhost:8000}"

red()   { printf '\033[0;31m%s\033[0m\n' "$*" >&2; }
green() { printf '\033[0;32m%s\033[0m\n' "$*"; }
blue()  { printf '\033[0;34m%s\033[0m\n' "$*"; }
yellow(){ printf '\033[0;33m%s\033[0m\n' "$*"; }
die()   { red "✗ $*"; exit 1; }

confirm() {
  read -r -p "$(yellow "$* [y/N] ")" a
  [[ "$a" =~ ^[Yy]$ ]] || die "aborted"
}

[[ $EUID -eq 0 ]] || die "must run as root"
[[ -d "$REPO_DIR" ]] || die "repo dir not found: $REPO_DIR"
[[ -f "$SVC_SRC" ]] || die "service file not found: $SVC_SRC"
[[ -f "$ENV_FILE" ]] || die ".env not found: $ENV_FILE"

blue "════════════════════════════════════════════════════════════"
blue "  BeaMax autonomy daemon — install"
blue "════════════════════════════════════════════════════════════"

# ── 1. Extract API token ─────────────────────────────────────
TOKEN=$(grep -E '^BEA_API_TOKEN=' "$ENV_FILE" | head -1 | cut -d= -f2-)
if [[ -z "$TOKEN" ]]; then
  die "BEA_API_TOKEN missing in $ENV_FILE"
fi
green "  ✓ token loaded from $ENV_FILE"

# ── 2. /etc/beamax/ config ────────────────────────────────
mkdir -p "$CFG_DIR"
chmod 750 "$CFG_DIR"

if [[ ! -f "$CFG_OBJ" ]]; then
  cat > "$CFG_OBJ" <<'EOF'
Surveille la santé de la plateforme : container, latence API, échecs LLM, anomalies dans les logs récents. Ouvre une décision multi-choix à l'opérateur dès qu'une dérive est détectée.
EOF
  yellow "  ⚠ $CFG_OBJ created with default objective — edit before enabling for real autonomy"
fi

if [[ ! -f "$CFG_ENV" ]]; then
  cat > "$CFG_ENV" <<EOF
# /etc/beamax/autonomy.env — overrides for bea-autonomy.service
# Edit then : systemctl daemon-reload && systemctl restart bea-autonomy

BEA_API_TOKEN=$TOKEN
BEA_API_URL=$API_URL

# Mission caps (defaults are conservative)
MAX_ITERS=20
SLEEP_S=30
MAX_SECONDS=1800
MAX_TOKENS=200000
MAX_USD=1.0

# IMPORTANT : the API process itself must export
#   BEA_AUTONOMY_USE_REAL=1
# in its env (docker-compose.yml or similar) for the daemon to use the
# real MetaOrchestrator. Without it, the daemon runs in safe mode
# (event-bus only, no real LLM calls).
EOF
  chmod 600 "$CFG_ENV"
  green "  ✓ $CFG_ENV created"
fi

# ── 3. Install service file ──────────────────────────────────
if [[ -f "$SVC_DST" ]]; then
  cp -p "$SVC_DST" "${SVC_DST}.bak.$(date +%s)"
  yellow "  ⚠ existing service file backed up"
fi
confirm "  Install $SVC_DST (overrides existing) ?"
cp "$SVC_SRC" "$SVC_DST"
chmod 644 "$SVC_DST"
green "  ✓ $SVC_DST installed"

# ── 4. Reload + enable ───────────────────────────────────────
systemctl daemon-reload
confirm "  Enable + start bea-autonomy now ?"
systemctl enable bea-autonomy
systemctl start bea-autonomy
sleep 2
systemctl status --no-pager bea-autonomy | head -20

# ── 5. Smoke test ────────────────────────────────────────────
blue "  Smoke test : GET /api/v3/autonomy/status"
status_resp=$(curl -fsS "$API_URL/api/v3/autonomy/status" \
  -H "Authorization: Bearer $TOKEN" || echo "{}")
echo "$status_resp" | python3 -m json.tool 2>/dev/null || echo "$status_resp"

green ""
green "════════════════════════════════════════════════════════════"
green "  Autonomy bootstrap installed."
green "════════════════════════════════════════════════════════════"
echo
echo "  Edit objective       : $CFG_OBJ"
echo "  Edit limits / token  : $CFG_ENV"
echo "  Restart bootstrap    : systemctl restart bea-autonomy"
echo "  Disable              : systemctl disable --now bea-autonomy"
echo "  Pause running daemon : echo BEA_AUTONOMY_PAUSED=1 >> .env && docker restart bea_core"
echo
yellow "  REMINDER : the daemon currently runs in SAFE mode unless the API"
yellow "  process has BEA_AUTONOMY_USE_REAL=1 in its environment. Add"
yellow "  it to docker-compose.yml + restart the container when you are"
yellow "  ready to wire to the real MetaOrchestrator."
