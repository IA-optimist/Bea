#!/bin/bash
# JarvisMax API Keys Configuration
# Usage: ./configure_api_keys.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_ROOT/.env"

echo "=== JARVISMAX API KEYS CONFIGURATION ==="
echo ""

# Backup existing .env if present
if [ -f "$ENV_FILE" ]; then
    cp "$ENV_FILE" "$ENV_FILE.backup.$(date +%s)"
    echo "✓ Backed up existing .env"
fi

# Create/update .env
cat > "$ENV_FILE" << 'EOF'
# ═══════════════════════════════════════
# JARVISMAX — API KEYS CONFIGURATION
# ═══════════════════════════════════════

# LLM Providers (au moins 1 requis)
OPENROUTER_API_KEY=sk-or-v1-CHANGE_ME
ANTHROPIC_API_KEY=sk-ant-CHANGE_ME
OPENAI_API_KEY=sk-CHANGE_ME

# Vector Store (recommandé)
QDRANT_API_KEY=CHANGE_ME
QDRANT_URL=https://your-cluster.qdrant.io

# Embeddings (si pas Qdrant local)
# OPENAI_API_KEY déjà défini ci-dessus

# Observability (optionnel)
LANGFUSE_PUBLIC_KEY=pk-lf-CHANGE_ME
LANGFUSE_SECRET_KEY=sk-lf-CHANGE_ME
LANGFUSE_HOST=https://cloud.langfuse.com

# Database (déjà configuré via Docker Compose)
# DATABASE_URL=postgresql://jarvis:jarvis@postgres:5432/jarvismax

# Security
JWT_SECRET_KEY=$(openssl rand -hex 32)

# Mode
DRY_RUN=false
PRODUCTION_MODE=false
EOF

echo "✓ Created .env template"
echo ""
echo "NEXT STEPS:"
echo "1. Edit $ENV_FILE"
echo "2. Replace CHANGE_ME values with real API keys"
echo "3. Run: docker cp $ENV_FILE jarvis_core:/app/.env"
echo "4. Run: docker restart jarvis_core"
echo ""
echo "MINIMAL SETUP (choose ONE):"
echo "  - OPENROUTER_API_KEY (recommended - access to all models)"
echo "  - OR ANTHROPIC_API_KEY (Claude only)"
echo "  - OR rely on Ollama (already running in jarvis_ollama container)"
