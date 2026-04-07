#!/bin/bash
# ACTIVATION SELF-IMPROVEMENT V3
# Usage: ./scripts/activate_si_v3.sh [API_KEY]

set -e
cd "$(dirname "$0")/.."

echo "🔧 ACTIVATION SELF-IMPROVEMENT V3"
echo "=================================="

# Vérifier clé LLM
if [ -z "$1" ]; then
    echo "❌ ERREUR: Clé LLM manquante"
    echo ""
    echo "Usage:"
    echo "  ./scripts/activate_si_v3.sh sk-ant-YOUR_KEY  # Anthropic"
    echo "  ./scripts/activate_si_v3.sh sk-or-YOUR_KEY   # OpenRouter"
    echo "  ./scripts/activate_si_v3.sh sk-YOUR_KEY      # OpenAI"
    exit 1
fi

API_KEY="$1"

# Détecter provider
if [[ "$API_KEY" == sk-ant-* ]]; then
    PROVIDER="ANTHROPIC"
    KEY_VAR="ANTHROPIC_API_KEY"
elif [[ "$API_KEY" == sk-or-* ]]; then
    PROVIDER="OPENROUTER"
    KEY_VAR="OPENROUTER_API_KEY"
elif [[ "$API_KEY" == sk-* ]]; then
    PROVIDER="OPENAI"
    KEY_VAR="OPENAI_API_KEY"
else
    echo "❌ Format de clé non reconnu (doit commencer par sk-)"
    exit 1
fi

echo "📋 Provider détecté: $PROVIDER"
echo ""

# Backup
BACKUP_FILE=".env.backup-$(date +%Y%m%d-%H%M%S)"
cp .env "$BACKUP_FILE"
echo "✅ Backup: $BACKUP_FILE"

# Configurer clé
if grep -q "^${KEY_VAR}=" .env; then
    sed -i "s|^${KEY_VAR}=.*|${KEY_VAR}=${API_KEY}|" .env
else
    echo "${KEY_VAR}=${API_KEY}" >> .env
fi
echo "✅ Clé $PROVIDER configurée"

# Activer SI + désactiver DRY_RUN
sed -i 's/^DRY_RUN=.*/DRY_RUN=false/' .env
sed -i 's/^SELF_IMPROVE_ENABLED=.*/SELF_IMPROVE_ENABLED=true/' .env

if ! grep -q "^SELF_IMPROVE_MAX_PATCHES=" .env; then
    echo "SELF_IMPROVE_MAX_PATCHES=1" >> .env
fi

echo "✅ Configuration SI activée (DRY_RUN=false)"
echo ""

# Redémarrer
echo "🔄 Redémarrage container..."
docker compose up -d jarvis --force-recreate

echo "⏳ Attente healthy (15s)..."
sleep 15

# Vérifier
if docker compose ps jarvis | grep -q "healthy"; then
    echo "✅ Container healthy"
    
    echo ""
    echo "📊 Logs de démarrage:"
    docker logs jarvis_core --tail=30 | grep -E "jarvismax_starting|self_improv" || true
    
    echo ""
    echo "✅ ACTIVATION COMPLÉTÉE"
    echo ""
    echo "📝 Prochaines étapes:"
    echo "  1. Monitorer logs: docker logs -f jarvis_core"
    echo "  2. Chercher: 'Self-improvement cycle started'"
    echo "  3. Vérifier workspace/self_improvement/ après 1er cycle"
    echo ""
    echo "⚠️  Rollback si problème:"
    echo "  docker compose stop jarvis"
    echo "  cp $BACKUP_FILE .env"
    echo "  docker compose up -d jarvis"
else
    echo "❌ Container non-healthy - vérifier logs:"
    docker logs jarvis_core --tail=50
    echo ""
    echo "🔙 Rollback automatique..."
    cp "$BACKUP_FILE" .env
    docker compose up -d jarvis --force-recreate
    exit 1
fi
