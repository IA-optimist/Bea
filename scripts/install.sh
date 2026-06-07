#!/usr/bin/env bash
# ================================================================
# BEA MAX — Script d'installation automatique
# Usage : bash scripts/install.sh
# ================================================================
set -euo pipefail

# ── Couleurs ──────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[1;33m'
RED='\033[0;31m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${BLUE}[Bea]${NC} $1"; }
ok()      { echo -e "${GREEN}[✓]${NC} $1"; }
warn()    { echo -e "${YELLOW}[!]${NC} $1"; }
error()   { echo -e "${RED}[✗]${NC} $1"; exit 1; }
step()    { echo -e "\n${BOLD}${BLUE}━━ $1 ━━${NC}"; }

banner() {
cat << 'EOF'
  ╔══════════════════════════════════════════╗
  ║          BEA MAX  v1.0                ║
  ║   Assistant Personnel Autonome IA        ║
  ╚══════════════════════════════════════════╝
EOF
}

banner
echo ""

# ── Vérifications ─────────────────────────────────────────────
step "Vérification des prérequis"

command -v docker &>/dev/null     || error "Docker non installé. Voir : https://docs.docker.com/get-docker/"
docker compose version &>/dev/null || error "Docker Compose v2 requis (plugin, pas docker-compose)."
command -v curl &>/dev/null       || error "curl requis."
ok "Docker + Compose disponibles"

# Docker accessible sans sudo ?
docker ps &>/dev/null || {
    warn "Docker requiert sudo. Ajoute ton user au groupe docker :"
    warn "  sudo usermod -aG docker \$USER && newgrp docker"
    error "Relance le script après."
}
ok "Docker accessible sans sudo"

# ── .env ──────────────────────────────────────────────────────
step "Configuration .env"

if [ ! -f .env ]; then
    cp .env.example .env

    # Auto-générer les secrets
    gen_secret() { openssl rand -hex 32 2>/dev/null || python3 -c "import secrets; print(secrets.token_hex(32))"; }
    gen_pass()   { openssl rand -base64 24 | tr -d '=/+' | head -c 28; }

    PGPASS=$(gen_pass)
    RDPASS=$(gen_pass)
    N8KEY=$(gen_secret | head -c 32)
    JSKEY=$(gen_secret)
    N8PASS=$(gen_pass)

    # Remplacer les placeholders
    sed -i.bak \
      -e "s/CHANGE_ME_generate_with_openssl_rand_hex_32/$JSKEY/" \
      -e "s/CHANGE_ME_strong_db_password_here/$PGPASS/" \
      -e "s/CHANGE_ME_redis_password/$RDPASS/" \
      -e "s/CHANGE_ME_32_char_key_for_n8n_encryption/$N8KEY/" \
      -e "s/CHANGE_ME_n8n_ui_password/$N8PASS/" \
      .env
    rm -f .env.bak

    ok ".env créé avec secrets auto-générés"
    echo ""
    warn "┌─────────────────────────────────────────────────┐"
    warn "│  ⚠️  COMPLÈTE CES VALEURS DANS .env AVANT       │"
    warn "│  DE LANCER docker compose :                     │"
    warn "│                                                 │"
    warn "│  TELEGRAM_BOT_TOKEN     → @BotFather            │"
    warn "│  TELEGRAM_ALLOWED_USER_ID → @userinfobot        │"
    warn "│  OPENAI_API_KEY         → platform.openai.com  │"
    warn "└─────────────────────────────────────────────────┘"
    echo ""
else
    warn ".env existant conservé (non modifié)"
fi

# ── Vérifications .env ────────────────────────────────────────
cd "${PROJECT_ROOT}" 2>/dev/null || true
# Note: variables lues depuis .env par docker compose directement

if [[ "${TELEGRAM_BOT_TOKEN:-CHANGE_ME}" == *"CHANGE_ME"* ]]; then
    warn "TELEGRAM_BOT_TOKEN non configuré → édite .env puis relance"
fi
if [[ "${TELEGRAM_ALLOWED_USER_ID:-CHANGE_ME}" == *"CHANGE_ME"* ]]; then
    warn "TELEGRAM_ALLOWED_USER_ID non configuré → édite .env puis relance"
fi

# ── Répertoires ───────────────────────────────────────────────
step "Création des répertoires"
mkdir -p workspace/{projects,reports,missions,patches,.backups} logs
ok "workspace/ et logs/ prêts"

# ── Pull images ───────────────────────────────────────────────
step "Téléchargement des images Docker"
docker compose pull --quiet 2>/dev/null || warn "Certaines images non disponibles (normal si première fois)"
ok "Images prêtes"

# ── Démarrage infrastructure ──────────────────────────────────
step "Démarrage Postgres + Redis + Qdrant"
docker compose up -d postgres redis qdrant
info "Attente Postgres..."
for i in $(seq 1 40); do
    docker compose exec -T postgres pg_isready -U "${POSTGRES_USER:-bea}" &>/dev/null && break
    sleep 2
    [ $((i % 5)) -eq 0 ] && echo -n "."
done
echo ""
ok "Postgres prêt"

# ── Ollama + modèles ──────────────────────────────────────────
step "Démarrage Ollama + téléchargement modèles"
docker compose up -d ollama
info "Attente Ollama..."
for i in $(seq 1 30); do
    curl -sf "http://localhost:11434/api/tags" &>/dev/null && break
    sleep 3
done

MAIN_MODEL="${OLLAMA_MODEL_MAIN:-llama3.1:8b}"
CODE_MODEL="${OLLAMA_MODEL_CODE:-deepseek-coder:6.7b}"
FAST_MODEL="${OLLAMA_MODEL_FAST:-mistral:7b}"

for model in "$MAIN_MODEL" "$CODE_MODEL" "$FAST_MODEL"; do
    info "Pull modèle Ollama : $model (peut prendre plusieurs minutes)..."
    docker compose exec -T ollama ollama pull "$model" \
        && ok "Modèle $model prêt" \
        || warn "Modèle $model non téléchargé — relance manuellement : docker compose exec ollama ollama pull $model"
done

# ── n8n ───────────────────────────────────────────────────────
step "Démarrage n8n"
docker compose up -d n8n
info "Attente n8n..."
sleep 15
ok "n8n → http://localhost:5678 (user: ${N8N_BASIC_AUTH_USER:-admin})"

# ── Build Bea ──────────────────────────────────────────────
step "Build du conteneur Bea Max"
docker compose build bea
ok "Image bea_core construite"

echo ""
echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════════════╗"
echo -e "║   ✅  Installation terminée avec succès          ║"
echo -e "╚══════════════════════════════════════════════════╝${NC}"
echo ""
echo "  Services disponibles :"
echo "  → n8n        : http://localhost:5678"
echo "  → Open WebUI : http://localhost:3001  (après démarrage)"
echo "  → Qdrant UI  : http://localhost:6333/dashboard"
echo "  → Bea API : http://localhost:8000  (après démarrage)"
echo ""
echo "  Prochaines étapes :"
echo -e "  ${YELLOW}1.${NC} Édite .env : TELEGRAM_BOT_TOKEN + TELEGRAM_ALLOWED_USER_ID + OPENAI_API_KEY"
echo -e "  ${YELLOW}2.${NC} Lance     : ${BOLD}bash scripts/start.sh${NC}"
echo ""
