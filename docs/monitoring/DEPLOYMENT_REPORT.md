# 📊 Rapport de Déploiement - Stack Monitoring BeaMax

**Date**: 2026-04-09  
**Serveur**: VPS1 (MONITORING_HOST)
**Statut**: ✅ DÉPLOYÉ ET OPÉRATIONNEL

---

## 🎯 Résumé

Stack de monitoring complète déployée avec succès incluant:
- ✅ **Prometheus** - Collecte et stockage des métriques
- ✅ **Grafana** - Visualisation avec 3 dashboards pré-configurés
- ✅ **Node Exporter** - Métriques système (CPU, RAM, Disque)
- ✅ **Alertmanager** - Gestion des alertes avec support Telegram
- ✅ **Configuration réseau** - Ports ouverts et accessibles

---

## 📦 Services Déployés

| Service | Container | Port | Statut | Health |
|---------|-----------|------|--------|--------|
| **Prometheus** | beamax-prometheus | 9090 | ✅ Running | ✅ Healthy |
| **Grafana** | beamax-grafana | 3002 | ✅ Running | ✅ Healthy |
| **Node Exporter** | beamax-node-exporter | 9100 | ✅ Running | ✅ Running |
| **Alertmanager** | beamax-alertmanager | 9093 | ✅ Running | ✅ Healthy |

### Targets Prometheus

| Job | Health | Description |
|-----|--------|-------------|
| beamax-api | ✅ UP | API metrics sur /metrics |
| node-exporter | ✅ UP | Métriques système |
| prometheus | ✅ UP | Self-monitoring |
| qdrant | ✅ UP | Vector database |
| postgres | ⚠️ DOWN | Pas d'exporter (normal) |
| redis | ⚠️ DOWN | Pas d'exporter (normal) |

*Note: Postgres et Redis n'exposent pas de métriques Prometheus par défaut. Pour les monitorer, installer des exporters dédiés si nécessaire.*

---

## 📊 Dashboards Grafana

Tous accessibles via http://MONITORING_HOST:3002 (admin / ${GRAFANA_ADMIN_PASSWORD})

### 1. System Monitoring Dashboard
**UID**: `beamax-system`  
**Métriques**:
- CPU Usage (temps réel + alertes > 80%)
- Memory Usage (avec seuils d'alerte)
- Disk Usage (alertes < 20%)
- Network Traffic (RX/TX par interface)
- System Load Average (1m, 5m, 15m)
- Container Status (UP/DOWN pour chaque service)

### 2. API Monitoring Dashboard
**UID**: `beamax-api`  
**Métriques**:
- Request Rate (par endpoint et méthode)
- Response Time (P50, P95, P99)
- Error Rate (4xx et 5xx)
- Success Rate (gauge avec seuils)
- Active Requests
- Top 10 Endpoints (par volume)
- Slowest Endpoints (par latence P95)
- API Health Status
- Total Requests (24h)
- Average Response Time

### 3. Business Metrics Dashboard
**UID**: `beamax-business`  
**Métriques**:
- Business Tasks (total, completed, failed)
- Task Success Rate (gauge)
- Task Duration Distribution (P50, P95, P99)
- Tasks by Type (pie chart)
- Agent Execution Count
- Agent Success Rate (bar gauge)
- Revenue Metrics
- Active Users
- Data Processing Pipeline
- LLM API Calls (par provider)
- Cost Tracking (24h)
- Database Query Rate
- Cache Hit Rate
- Queue Depth

---

## 🔔 Alertes Configurées

### Critical (🔴)
- **APIDown**: API inaccessible > 1 minute
- **DiskSpaceCritical**: Espace disque < 10%
- **PostgresDown**: Base de données down
- **RedisDown**: Cache down
- **ContainerDown**: Conteneur arrêté > 2 minutes

### Warning (⚠️)
- **HighErrorRate**: Taux d'erreur > 5% pendant 5min
- **SlowResponseTime**: P95 > 2 secondes pendant 5min
- **HighCPUUsage**: CPU > 80% pendant 5min
- **HighMemoryUsage**: RAM > 85% pendant 5min
- **DiskSpaceLow**: Espace disque < 20%
- **HighBusinessTaskFailureRate**: Échec > 20% pendant 10min

### Info (ℹ️)
- **LowBusinessActivityRate**: Activité faible > 30min

---

## 🔐 Accès et Identifiants

### Grafana
- **URL**: http://MONITORING_HOST:3002
- **Username**: `admin`
- **Password**: `${GRAFANA_ADMIN_PASSWORD}`
- **Datasource**: Prometheus (pré-configuré)

### Prometheus
- **URL**: http://MONITORING_HOST:9090
- **Targets**: http://MONITORING_HOST:9090/targets
- **Alerts**: http://MONITORING_HOST:9090/alerts
- **Auth**: Aucune

### Alertmanager
- **URL**: http://MONITORING_HOST:9093
- **Auth**: Aucune

### Node Exporter
- **URL**: http://MONITORING_HOST:9100/metrics
- **Auth**: Aucune

---

## 📁 Structure des Fichiers

```
/root/Beamax-master/deploy/monitoring/
├── docker-compose-monitoring.yml    # Compose file principal
├── prometheus/
│   ├── prometheus.yml              # Config Prometheus
│   └── alerts.yml                  # Règles d'alerte
├── grafana/
│   ├── provisioning/
│   │   ├── datasources/
│   │   │   └── prometheus.yml      # Datasource auto-provisionnée
│   │   └── dashboards/
│   │       └── dashboards.yml      # Config dashboards
│   └── dashboards/
│       ├── system-dashboard.json   # Dashboard système
│       ├── api-dashboard.json      # Dashboard API
│       └── business-dashboard.json # Dashboard business
├── alertmanager/
│   └── alertmanager.yml            # Config alertes + webhook
├── telegram_webhook.py             # Module webhook Telegram
├── api_webhook_integration.py      # Code d'intégration API
├── test_stack.sh                   # Script de test
├── QUICKSTART.md                   # Guide de démarrage rapide
├── README.md                       # Documentation complète
└── DEPLOYMENT_REPORT.md            # Ce fichier
```

---

## 🔧 Configuration Réseau

### Ports Ouverts (UFW)
- ✅ 3002/tcp (Grafana)
- ✅ 9090/tcp (Prometheus)
- ✅ 9093/tcp (Alertmanager)
- ✅ 9100/tcp (Node Exporter)

### Network Docker
- **Nom**: `beamax-master_beamax-network`
- **Type**: bridge
- **Services connectés**: 8 (API, DB, Redis, Qdrant, Caddy, Frontend, Ollama + Monitoring stack)

---

## 📈 Volumes Persistants

| Volume | Type | Description | Retention |
|--------|------|-------------|-----------|
| `monitoring_prometheus_data` | Docker volume | Métriques Prometheus | 15 jours |
| `monitoring_grafana_data` | Docker volume | Dashboards et config | Permanent |
| `monitoring_alertmanager_data` | Docker volume | État des alertes | Permanent |

---

## 🔗 Intégration Telegram (Optionnel)

### Configuration Requise

1. **Créer un bot Telegram**:
   - Parler à @BotFather
   - Commande: `/newbot`
   - Récupérer le token

2. **Obtenir le Chat ID**:
   - Envoyer un message au bot
   - Visiter: `https://api.telegram.org/bot<TOKEN>/getUpdates`
   - Récupérer le chat ID dans la réponse JSON

3. **Configurer dans .env**:
   ```bash
   TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
   TELEGRAM_CHAT_ID=123456789
   ```

4. **Intégrer le webhook dans l'API**:
   - Copier le code de `api_webhook_integration.py`
   - Ajouter le router dans `main.py`
   - Redémarrer l'API

5. **Tester**:
   ```bash
   curl http://localhost:8000/api/v2/webhooks/test-telegram
   ```

### Webhook Alertmanager
- **Endpoint**: `http://beamax-api:8000/api/v2/webhooks/alertmanager`
- **Méthode**: POST
- **Format**: JSON (Alertmanager v4)
- **Priorités**: default, critical, info

---

## ✅ Checklist de Validation

- [x] Stack déployée et tous les conteneurs healthy
- [x] Prometheus scrape l'API BeaMax avec succès
- [x] Node Exporter expose les métriques système
- [x] Grafana accessible sur port 3002
- [x] 3 dashboards créés et provisionnés
- [x] Alertmanager configuré avec règles
- [x] Ports ouverts dans le firewall
- [x] Network Docker correctement configuré
- [x] Volumes persistants créés
- [x] Documentation complète fournie
- [ ] Webhook Telegram configuré (optionnel)

---

## 🎓 Guide d'Utilisation Rapide

### Démarrer/Arrêter la Stack
```bash
cd /root/Beamax-master/monitoring

# Démarrer
docker compose -f docker-compose-monitoring.yml up -d

# Arrêter
docker compose -f docker-compose-monitoring.yml down

# Redémarrer
docker compose -f docker-compose-monitoring.yml restart
```

### Voir les Logs
```bash
# Tous les services
docker compose -f docker-compose-monitoring.yml logs -f

# Service spécifique
docker compose -f docker-compose-monitoring.yml logs -f grafana
```

### Vérifier le Statut
```bash
docker compose -f docker-compose-monitoring.yml ps
```

### Recharger la Configuration
```bash
# Prometheus (sans redémarrage)
curl -X POST http://localhost:9090/-/reload

# Alertmanager
curl -X POST http://localhost:9093/-/reload
```

---

## 📚 Documentation

- **QUICKSTART.md**: Guide de démarrage rapide
- **README.md**: Documentation détaillée complète
- **api_webhook_integration.py**: Code d'intégration Telegram
- **telegram_webhook.py**: Module webhook standalone
- **test_stack.sh**: Script de test automatique

---

## 🐛 Troubleshooting

### Dashboard vide
- Attendre 1-2 minutes pour la première collecte
- Vérifier que l'API expose /metrics: `curl http://localhost:8000/metrics`
- Vérifier les targets: http://MONITORING_HOST:9090/targets

### Alerte ne fonctionne pas
- Vérifier Alertmanager: http://MONITORING_HOST:9093
- Vérifier les logs: `docker logs beamax-alertmanager`
- Tester manuellement l'endpoint webhook

### Grafana inaccessible
- Vérifier le conteneur: `docker ps | grep grafana`
- Vérifier les logs: `docker logs beamax-grafana`
- Vérifier le firewall: `ufw status | grep 3002`

---

## 📞 Support

En cas de problème:
1. Consulter la documentation dans `README.md`
2. Vérifier les logs: `docker compose logs -f`
3. Exécuter le script de test: `./test_stack.sh`
4. Vérifier les targets Prometheus: http://MONITORING_HOST:9090/targets

---

## 🎯 Prochaines Étapes Recommandées

1. **Configurer Telegram** pour recevoir les alertes en temps réel
2. **Personnaliser les dashboards** selon vos besoins spécifiques
3. **Ajuster les seuils d'alerte** dans `prometheus/alerts.yml`
4. **Ajouter des métriques business** personnalisées dans l'API
5. **Configurer les exporters** pour Postgres et Redis si nécessaire
6. **Mettre en place les backups** des volumes Grafana

---

## 📊 Métriques Collectées

### Système (via Node Exporter)
- CPU: utilisation par core, idle, iowait
- Mémoire: total, available, used, cached
- Disque: space, I/O, latency
- Network: bandwidth, packets, errors
- Load: 1min, 5min, 15min

### API (via FastAPI)
- HTTP: requests total, duration, active requests
- Endpoints: par méthode, path, status code
- Performance: P50, P95, P99 latency
- Errors: count, rate, types

### Business (à implémenter)
- Tasks: total, completed, failed, duration
- Agents: executions, success rate
- Revenue & Cost tracking
- LLM API calls & costs
- Cache performance
- Queue depth

---

**Déploiement réalisé avec succès le 2026-04-09 21:20 UTC**

Pour toute question, consulter la documentation ou les logs des services.
