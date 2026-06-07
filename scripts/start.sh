#!/usr/bin/env bash
# BEA MAX — Démarrage
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BOLD='\033[1m'; NC='\033[0m'
info()  { echo -e "${BLUE}[Bea]${NC} $1"; }
ok()    { echo -e "${GREEN}[✓]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
error() { echo -e "${RED}[✗]${NC} $1"; exit 1; }

echo -e "\n${BOLD}  🤖 BEA MAX — Démarrage${NC}\n"

# ── Vérifications ─────────────────────────────────────────────
[ -f .env ] || error ".env introuvable. Lance d'abord : bash scripts/install.sh"
cd "${PROJECT_ROOT}" 2>/dev/null || true
# Note: variables lues depuis .env par docker compose directement

[[ "${TELEGRAM_BOT_TOKEN:-CHANGE_ME}" == *"CHANGE_ME"* ]] && \
    error "TELEGRAM_BOT_TOKEN non configuré dans .env"
[[ "${TELEGRAM_ALLOWED_USER_ID:-CHANGE_ME}" == *"CHANGE_ME"* ]] && \
    error "TELEGRAM_ALLOWED_USER_ID non configuré dans .env"
[[ "${POSTGRES_PASSWORD:-CHANGE_ME}" == *"CHANGE_ME"* ]] && \
    error "POSTGRES_PASSWORD non configuré dans .env"

ok "Variables .env vérifiées"

# ── Démarrage ─────────────────────────────────────────────────
info "Démarrage de toute la stack..."
docker compose up -d

info "Attente que bea_core soit healthy..."
MAX=60
for i in $(seq 1 $MAX); do
    STATUS=$(docker inspect --format='{{.State.Health.Status}}' bea_core 2>/dev/null || echo "missing")
    if [ "$STATUS" = "healthy" ]; then
        break
    elif [ "$STATUS" = "unhealthy" ]; then
        error "bea_core unhealthy. Logs : docker compose logs bea"
    fi
    sleep 3
    [ $((i % 10)) -eq 0 ] && echo -n "." && docker compose logs --tail=3 bea 2>/dev/null || true
done
echo ""

# Test API
curl -sf http://localhost:8000/health >/dev/null 2>&1 && ok "API Bea opérationnelle" || warn "API non accessible (peut être en démarrage)"

echo ""
echo -e "${GREEN}${BOLD}  ✅ BeaMax opérationnel !${NC}"
echo ""
echo "  → Envoie un message à ton bot Telegram"
echo "  → API      : http://localhost:8000"
echo "  → n8n      : http://localhost:5678"
echo "  → WebUI    : http://localhost:3001"
echo ""
echo "  Logs en direct : docker compose logs -f bea"
echo ""
