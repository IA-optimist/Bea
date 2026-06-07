#!/usr/bin/env bash
# BEA MAX — Vérification pré-déploiement v2
# Usage : bash scripts/deploy_check.sh [--from-dir /chemin/vers/beamax]
# Ce script VÉRIFIE seulement. Il ne démarre rien.

set -euo pipefail

GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[1;33m'
RED='\033[0;31m'; BOLD='\033[1m'; NC='\033[0m'

ok()    { echo -e "${GREEN}[✓]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
error() { echo -e "${RED}[✗]${NC} $1"; }
info()  { echo -e "${BLUE}[i]${NC} $1"; }

echo -e "\n${BOLD}  🤖 BEA MAX — Vérification pré-déploiement${NC}\n"

# ── Localiser la racine du projet ──────────────────────────────
# Fonctionner depuis n'importe quel dossier courant
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [ "${1:-}" = "--from-dir" ] && [ -n "${2:-}" ]; then
    PROJECT_ROOT="$(cd "$2" && pwd)"
fi

info "Racine projet : ${PROJECT_ROOT}"

if [ ! -f "${PROJECT_ROOT}/docker-compose.yml" ]; then
    error "docker-compose.yml introuvable dans ${PROJECT_ROOT}"
    exit 1
fi

ERRORS=0

# ── 1. Docker ──────────────────────────────────────────────────
echo "── Docker ──────────────────────────────────────────────"
command -v docker &>/dev/null \
    && ok "docker installé" \
    || { error "docker manquant"; ((ERRORS++)); }

docker compose version &>/dev/null \
    && ok "docker compose v2 OK" \
    || { error "docker compose v2 manquant"; ((ERRORS++)); }

docker ps &>/dev/null \
    && ok "docker accessible" \
    || { error "docker requiert sudo ou daemon non lancé"; ((ERRORS++)); }

# ── 2. .env ────────────────────────────────────────────────────
echo ""
echo "── .env ────────────────────────────────────────────────"

ENV_FILE="${PROJECT_ROOT}/.env"
ENV_EXAMPLE="${PROJECT_ROOT}/.env.example"

if [ ! -f "${ENV_FILE}" ]; then
    error ".env manquant — copie .env.example et remplis les valeurs :"
    error "  cp ${ENV_EXAMPLE} ${ENV_FILE}"
    ((ERRORS++))
else
    ok ".env présent"

    # Lire les variables sans 'source' (évite l'injection de commandes)
    _get_env() {
        grep -E "^${1}=" "${ENV_FILE}" 2>/dev/null | cut -d'=' -f2- | tr -d '"' | tr -d "'" || true
    }

    TG_TOKEN="$(_get_env TELEGRAM_BOT_TOKEN)"
    TG_UID="$(_get_env TELEGRAM_ALLOWED_USER_ID)"
    PG_PASS="$(_get_env POSTGRES_PASSWORD)"
    REDIS_PASS="$(_get_env REDIS_PASSWORD)"
    SECRET_KEY="$(_get_env BEA_SECRET_KEY)"
    OPENAI_KEY="$(_get_env OPENAI_API_KEY)"
    MODEL_STRAT="$(_get_env MODEL_STRATEGY)"

    check_var() {
        local name="$1" val="$2"
        if [ -z "$val" ] || echo "$val" | grep -qiE "CHANGE_ME|your_|example"; then
            error "${name} non configuré ou valeur par défaut"; ((ERRORS++))
        else
            ok "${name} configuré"
        fi
    }

    check_var "TELEGRAM_BOT_TOKEN"      "${TG_TOKEN}"
    check_var "TELEGRAM_ALLOWED_USER_ID" "${TG_UID}"
    check_var "POSTGRES_PASSWORD"       "${PG_PASS}"
    check_var "REDIS_PASSWORD"          "${REDIS_PASS}"

    if [ -z "${SECRET_KEY}" ] || echo "${SECRET_KEY}" | grep -qiE "CHANGE_ME"; then
        error "BEA_SECRET_KEY non configuré"; ((ERRORS++))
    elif [ "${#SECRET_KEY}" -lt 16 ]; then
        error "BEA_SECRET_KEY trop court (${#SECRET_KEY} chars < 16)"; ((ERRORS++))
    else
        ok "BEA_SECRET_KEY configuré (${#SECRET_KEY} chars)"
    fi

    if [ -z "${OPENAI_KEY}" ]; then
        warn "OPENAI_API_KEY vide → mode Ollama-only (OK si Ollama disponible)"
    else
        ok "OPENAI_API_KEY configuré"
    fi

    info "MODEL_STRATEGY=${MODEL_STRAT:-non défini (défaut: ollama)}"

    # Vérifier qu'aucun secret réel ne traîne dans .env.example
    if [ -f "${ENV_EXAMPLE}" ] && grep -qE "^[A-Z_]+=[^$#]" "${ENV_EXAMPLE}" \
       && ! grep -qiE "CHANGE_ME|your_|example|<" "${ENV_EXAMPLE}"; then
        warn ".env.example semble contenir des valeurs réelles (vérifier)"
    fi
fi

# ── 3. Ports ────────────────────────────────────────────────────
echo ""
echo "── Ports disponibles ───────────────────────────────────"
for port in 8000 5678 6333 11434 3001 5432 6379; do
    if ss -tlnp 2>/dev/null | grep -q ":${port} " \
    || netstat -tlnp 2>/dev/null | grep -q ":${port} "; then
        warn "Port ${port} OCCUPÉ — risque de conflit"
    else
        ok "Port ${port} libre"
    fi
done

# ── 4. Ressources ────────────────────────────────────────────────
echo ""
echo "── Ressources ──────────────────────────────────────────"

AVAIL=$(df -BG "${PROJECT_ROOT}" 2>/dev/null | awk 'NR==2{gsub("G",""); print $4}' || echo "0")
if [ "${AVAIL:-0}" -ge 20 ]; then
    ok "Espace disque : ${AVAIL}G disponible (≥20G requis)"
else
    warn "Espace disque : ${AVAIL:-?}G — les modèles Ollama pèsent ~15G"
fi

RAM_GB=$(free -g 2>/dev/null | awk '/^Mem:/{print $2}' || echo "?")
if [ "${RAM_GB:-0}" -ge 8 ]; then
    ok "RAM : ${RAM_GB}G (≥8G OK)"
else
    warn "RAM : ${RAM_GB}G — 8G minimum recommandé pour Ollama"
fi

# ── 5. Répertoires workspace ─────────────────────────────────────
echo ""
echo "── Répertoires ────────────────────────────────────────"
mkdir -p "${PROJECT_ROOT}/workspace"/{projects,reports,missions,patches,.backups,sandboxes} \
         "${PROJECT_ROOT}/logs" 2>/dev/null \
    && ok "workspace/ et logs/ créés/vérifiés" \
    || warn "Impossible de créer les répertoires workspace (permissions ?)"

# ── 6. Fichiers critiques ────────────────────────────────────────
echo ""
echo "── Fichiers projet ─────────────────────────────────────"
for f in docker-compose.yml docker/Dockerfile requirements.txt; do
    [ -f "${PROJECT_ROOT}/${f}" ] \
        && ok "${f} présent" \
        || { error "${f} manquant"; ((ERRORS++)); }
done

# ── Bilan ───────────────────────────────────────────────────────
echo ""
if [ "${ERRORS}" -eq 0 ]; then
    echo -e "${GREEN}${BOLD}  ✅ Prêt pour le déploiement${NC}"
    echo ""
    echo "  Commandes :"
    echo "    docker compose build bea"
    echo "    docker compose up -d"
    echo "    bash scripts/pull_models.sh   # première installation"
else
    echo -e "${RED}${BOLD}  ✗ ${ERRORS} erreur(s) bloquante(s) à corriger${NC}"
    exit 1
fi
