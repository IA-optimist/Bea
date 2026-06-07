#!/usr/bin/env bash
# BEA MAX — Pull modèles Ollama
# Usage : bash scripts/pull_models.sh [--all]
# Fonctionne depuis n'importe quel dossier courant.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${PROJECT_ROOT}/.env"

# Lire les variables sans 'source' (évite l'injection de commandes)
_get_env() {
    grep -E "^${1}=" "${ENV_FILE}" 2>/dev/null | cut -d'=' -f2- | tr -d '"' | tr -d "'" || true
}

if [ -f "${ENV_FILE}" ]; then
    MAIN="$(_get_env OLLAMA_MODEL_MAIN)"
    CODE="$(_get_env OLLAMA_MODEL_CODE)"
    FAST="$(_get_env OLLAMA_MODEL_FAST)"
    VISION="$(_get_env OLLAMA_MODEL_VISION)"
fi

# Valeurs par défaut si .env absent ou variable vide
MAIN="${MAIN:-llama3.1:8b}"
CODE="${CODE:-deepseek-coder-v2:16b}"
FAST="${FAST:-mistral:7b}"
VISION="${VISION:-llava:7b}"

MODELS=("$MAIN" "$CODE" "$FAST")
if [ "${1:-}" = "--all" ]; then
    MODELS+=("$VISION")
fi

echo "[Bea] Téléchargement des modèles Ollama..."
echo "  Modèles : ${MODELS[*]}"
echo ""

for m in "${MODELS[@]}"; do
    if [ -z "$m" ]; then continue; fi
    echo "  → Pulling $m..."
    docker compose -f "${PROJECT_ROOT}/docker-compose.yml" exec ollama ollama pull "$m" \
        && echo "  ✓ $m" \
        || echo "  ✗ $m (échec — vérifier ollama logs)"
    echo ""
done

echo "Modèles installés :"
docker compose -f "${PROJECT_ROOT}/docker-compose.yml" exec ollama ollama list
