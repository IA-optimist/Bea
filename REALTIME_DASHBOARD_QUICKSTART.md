# Dashboard Temps Réel - Quick Start

## Installation rapide

### Backend
```bash
# Déjà configuré, pas de modifications nécessaires
# Le routeur WebSocket est auto-chargé dans api/main.py
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

### Frontend
```bash
cd frontend
npm install  # Recharts déjà dans package.json
npm run dev
```

## Test rapide

### 1. Vérifier le WebSocket backend
```bash
curl http://localhost:8000/metrics/websocket/status
curl http://localhost:8000/metrics/snapshot
```

### 2. Ouvrir le dashboard
```
http://localhost:3000/
```

Vous devriez voir:
- 🟢 Indicateur "Live" en haut à droite
- Graphiques CPU/Memory animés
- Statistiques missions/revenue temps réel

## URLs des endpoints

- **WebSocket Stream**: `ws://localhost:8000/ws/metrics?interval=2`
- **Status**: `GET /metrics/websocket/status`
- **Snapshot**: `GET /metrics/snapshot`

## Configuration

**Frontend** (`.env`):
```bash
VITE_API_URL=http://localhost:8000/api/v2
VITE_WS_URL=ws://localhost:8000/ws/metrics
```

**Backend**: Aucune configuration requise (psutil optionnel pour métriques système)

## Fichiers créés/modifiés

### Backend
- ✅ `/api/routes/metrics_websocket.py` (nouveau)
- ✅ `/api/main.py` (import ajouté)

### Frontend
- ✅ `/frontend/src/hooks/useWebSocket.ts` (nouveau)
- ✅ `/frontend/src/components/RealtimeChart.tsx` (nouveau)
- ✅ `/frontend/src/pages/Dashboard.tsx` (mis à jour avec données live)

### Documentation
- ✅ `/docs/REALTIME_DASHBOARD.md` (guide complet)
- ✅ `/REALTIME_DASHBOARD_QUICKSTART.md` (ce fichier)

## Features implémentées

✅ WebSocket endpoint `/ws/metrics` avec auto-reconnect
✅ Hook React `useWebSocket` réutilisable
✅ Composant `RealtimeChart` avec Recharts
✅ Métriques système live (CPU, Memory)
✅ Statistiques missions live
✅ Métriques revenue live
✅ Graphiques animés temps réel
✅ Indicateur de connexion WebSocket
✅ Fallback gracieux si WebSocket indisponible
✅ Documentation complète

## Prochaines étapes

1. Connecter les métriques missions à la vraie DB PostgreSQL
2. Intégrer les vraies données revenue du module finance
3. Ajouter authentification JWT au WebSocket
4. Implémenter alertes visuelles sur seuils

Voir `/docs/REALTIME_DASHBOARD.md` pour la documentation complète.
