#!/bin/bash
# Script de vérification E2E avant commit
# Usage: ./scripts/verify-e2e.sh

set -e

echo "🧪 Vérification E2E JarvisMax"
echo "=============================="
echo ""

# Couleurs
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Vérifier que les services sont actifs
echo "📡 Vérification des services..."

if ! curl -s http://72.62.177.55:8000/health > /dev/null; then
    echo -e "${RED}✗ API non disponible sur http://72.62.177.55:8000${NC}"
    exit 1
fi
echo -e "${GREEN}✓ API disponible${NC}"

if ! curl -s -I http://72.62.177.55:3001 | grep -q "200 OK"; then
    echo -e "${RED}✗ Frontend non disponible sur http://72.62.177.55:3001${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Frontend disponible${NC}"

echo ""
echo "🧪 Lancement des tests E2E..."
echo ""

# Lancer les tests sur Chromium (plus rapide)
if npx playwright test --project=chromium; then
    echo ""
    echo -e "${GREEN}✅ Tous les tests E2E passent !${NC}"
    echo ""
    echo "📊 Générer le rapport HTML avec:"
    echo "   npm run test:e2e:report"
    exit 0
else
    echo ""
    echo -e "${RED}❌ Certains tests E2E ont échoué${NC}"
    echo ""
    echo "🔍 Pour debugger:"
    echo "   npm run test:e2e:headed  # Voir les navigateurs"
    echo "   npm run test:e2e:debug   # Mode debug"
    echo "   npm run test:e2e:report  # Voir le rapport détaillé"
    exit 1
fi
