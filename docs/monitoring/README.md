# BeaMax Monitoring Stack

Stack de monitoring complète pour BeaMax incluant Prometheus, Grafana, Node Exporter et Alertmanager avec intégration Telegram.

## 📊 Architecture

```
┌──────────────┐
│  Node Exporter│──┐
│  (Port 9100)  │  │
└──────────────┘  │
                  │
┌──────────────┐  │    ┌──────────────┐
│ BeaMax API│──┼───▶│  Prometheus  │
│ (Port 8000)  │  │    │  (Port 9090) │
└──────────────┘  │    └──────┬───────┘
                  │           │
┌──────────────┐  │           │
│  PostgreSQL  │──┤           │
│  Redis       │  │           ▼
│  Qdrant      │──┘    ┌──────────────┐
└──────────────┘       │   Grafana    │
                       │  (Port 3002) │
                       └──────────────┘
                              │
                              ▼
                       ┌──────────────┐
                       │ Alertmanager │──▶ Telegram
                       │  (Port 9093) │
                       └──────────────┘
```

## 🚀 Déploiement

### 1. Prérequis

- Docker et Docker Compose installés
- Network Docker `beamax-network` créé
- API BeaMax avec endpoint `/metrics` exposé
- (Optionnel) Bot Telegram pour les alertes

### 2. Configuration Telegram (Optionnel mais recommandé)

#### Créer un Bot Telegram

1. Parler à [@BotFather](https://t.me/botfather) sur Telegram
2. Envoyer `/newbot` et suivre les instructions
3. Copier le token du bot (format: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

#### Obtenir le Chat ID

1. Envoyer un message à votre bot
2. Visiter: `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`
3. Trouver `"chat":{"id":123456789}` dans la réponse

#### Ajouter au .env

```bash
# Ajouter à /root/Beamax-master/.env
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_CHAT_ID=123456789
```

### 3. Lancer la Stack

```bash
cd /root/Beamax-master/monitoring

# Lancer tous les services
docker-compose -f docker-compose-monitoring.yml up -d

# Vérifier le statut
docker-compose -f docker-compose-monitoring.yml ps

# Voir les logs
docker-compose -f docker-compose-monitoring.yml logs -f
```

### 4. Accès aux Services

| Service | URL | Identifiants |
|---------|-----|--------------|
| **Grafana** | http://MONITORING_HOST:3002 | admin / ${GRAFANA_ADMIN_PASSWORD} |
| **Prometheus** | http://MONITORING_HOST:9090 | - |
| **Alertmanager** | http://MONITORING_HOST:9093 | - |
| **Node Exporter** | http://MONITORING_HOST:9100 | - |

## 📈 Dashboards Grafana

### 1. System Monitoring Dashboard
**UID:** `beamax-system`

Métriques système et infrastructure:
- **CPU Usage**: Utilisation CPU en temps réel avec alertes > 80%
- **Memory Usage**: Utilisation mémoire avec seuils d'alerte
- **Disk Usage**: Espace disque disponible
- **Network Traffic**: Trafic réseau entrant/sortant
- **System Load**: Load average (1m, 5m, 15m)
- **Container Status**: État des conteneurs Docker

### 2. API Monitoring Dashboard
**UID:** `beamax-api`

Métriques de performance API:
- **Request Rate**: Requêtes par seconde par endpoint
- **Response Time**: P50, P95, P99 latency
- **Error Rate**: Taux d'erreurs 4xx et 5xx
- **Success Rate**: Gauge de taux de succès
- **Active Requests**: Requêtes en cours
- **Top Endpoints**: Endpoints les plus sollicités
- **Slowest Endpoints**: Endpoints avec latence élevée
- **API Health**: État de santé de l'API
- **Total Requests**: Volume sur 24h
- **Average Response Time**: Temps de réponse moyen

### 3. Business Metrics Dashboard
**UID:** `beamax-business`

Métriques métier et analytics:
- **Business Tasks**: Total, completed, failed
- **Task Success Rate**: Taux de succès des tâches
- **Task Duration**: Distribution des durées (P50, P95, P99)
- **Tasks by Type**: Répartition par type de tâche
- **Agent Execution**: Nombre d'exécutions par agent
- **Agent Success Rate**: Taux de succès par agent
- **Revenue Metrics**: Métriques de revenus
- **Active Users**: Utilisateurs actifs
- **Data Processing Pipeline**: État du pipeline de données
- **LLM API Calls**: Appels LLM par provider
- **Cost Tracking**: Suivi des coûts sur 24h
- **Database Queries**: Requêtes DB par seconde
- **Cache Hit Rate**: Taux de hit du cache
- **Queue Depth**: Profondeur de la file d'attente

## 🔔 Alertes

### Configuration des Alertes

Les alertes sont définies dans `prometheus/alerts.yml` et envoyées via Alertmanager.

#### Catégories d'Alertes

**Critical (🔴)**:
- `APIDown`: API inaccessible > 1 minute
- `DiskSpaceCritical`: Espace disque < 10%
- `PostgresDown`: Base de données down
- `RedisDown`: Cache down
- `ContainerDown`: Conteneur arrêté > 2 minutes

**Warning (⚠️)**:
- `HighErrorRate`: Taux d'erreur > 5%
- `SlowResponseTime`: P95 > 2 secondes
- `HighCPUUsage`: CPU > 80% pendant 5 minutes
- `HighMemoryUsage`: RAM > 85% pendant 5 minutes
- `DiskSpaceLow`: Espace disque < 20%
- `HighBusinessTaskFailureRate`: Échec > 20%

**Info (ℹ️)**:
- `LowBusinessActivityRate`: Activité faible > 30 minutes

### Webhook Telegram

Les alertes sont envoyées à Telegram via webhook. Pour activer:

1. **Configurer le .env** (voir section Telegram)

2. **Implémenter le webhook dans l'API**:
```python
# Ajouter dans votre FastAPI app
from monitoring.telegram_webhook import TelegramAlertManager

telegram_manager = TelegramAlertManager(
    bot_token=os.getenv('TELEGRAM_BOT_TOKEN'),
    chat_id=os.getenv('TELEGRAM_CHAT_ID')
)

@app.post("/api/v2/webhooks/alertmanager")
async def alertmanager_webhook(request: Request, priority: str = Query(default="default")):
    payload = await request.json()
    results = await telegram_manager.process_webhook(payload, priority)
    return {"status": "success", "alerts_sent": len(results)}
```

3. **Tester le webhook**:
```bash
cd /root/Beamax-master/monitoring
python3 telegram_webhook.py
```

## 🔍 Métriques Personnalisées

### Exposer des Métriques depuis l'API

Utiliser `prometheus_client` pour exposer des métriques:

```python
from prometheus_client import Counter, Histogram, Gauge, generate_latest

# Définir des métriques
http_requests_total = Counter(
    'http_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status']
)

http_request_duration_seconds = Histogram(
    'http_request_duration_seconds',
    'HTTP request duration',
    ['method', 'endpoint']
)

business_tasks_total = Counter(
    'business_tasks_total',
    'Total business tasks',
    ['task_type']
)

# Instrumenter le code
@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time
    
    http_requests_total.labels(
        method=request.method,
        endpoint=request.url.path,
        status=response.status_code
    ).inc()
    
    http_request_duration_seconds.labels(
        method=request.method,
        endpoint=request.url.path
    ).observe(duration)
    
    return response

# Endpoint metrics
@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type="text/plain")
```

## 📊 Requêtes PromQL Utiles

### Performance API
```promql
# Taux de requêtes par seconde
rate(http_requests_total[5m])

# Latence P95
histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))

# Taux d'erreur
rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m])
```

### Système
```promql
# CPU Usage
100 - (avg(rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)

# Memory Usage
(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100

# Disk Usage
(1 - (node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"})) * 100
```

### Business
```promql
# Task completion rate
rate(business_tasks_completed_total[5m])

# Task success rate
rate(business_tasks_completed_total[1h]) / rate(business_tasks_total[1h]) * 100
```

## 🛠️ Maintenance

### Logs
```bash
# Voir les logs en temps réel
docker-compose -f docker-compose-monitoring.yml logs -f

# Logs d'un service spécifique
docker-compose -f docker-compose-monitoring.yml logs -f prometheus
docker-compose -f docker-compose-monitoring.yml logs -f grafana
```

### Redémarrage
```bash
# Redémarrer tous les services
docker-compose -f docker-compose-monitoring.yml restart

# Redémarrer un service spécifique
docker-compose -f docker-compose-monitoring.yml restart prometheus
```

### Mise à jour de la configuration
```bash
# Recharger la config Prometheus (sans redémarrage)
curl -X POST http://localhost:9090/-/reload

# Recharger Alertmanager
curl -X POST http://localhost:9093/-/reload
```

### Nettoyage
```bash
# Arrêter tous les services
docker-compose -f docker-compose-monitoring.yml down

# Arrêter et supprimer les volumes (ATTENTION: perte de données)
docker-compose -f docker-compose-monitoring.yml down -v
```

## 📦 Volumes et Données

Les données persistantes sont stockées dans des volumes Docker:
- `prometheus_data`: Données de métriques (retention: 15 jours par défaut)
- `grafana_data`: Dashboards et configurations Grafana
- `alertmanager_data`: État des alertes

### Backup
```bash
# Backup Grafana
docker run --rm -v monitoring_grafana_data:/data -v $(pwd):/backup alpine tar czf /backup/grafana-backup.tar.gz -C /data .

# Backup Prometheus
docker run --rm -v monitoring_prometheus_data:/data -v $(pwd):/backup alpine tar czf /backup/prometheus-backup.tar.gz -C /data .
```

## 🔧 Troubleshooting

### Prometheus ne scrape pas l'API
```bash
# Vérifier que l'API expose /metrics
curl http://localhost:8000/metrics

# Vérifier la config Prometheus
docker exec beamax-prometheus cat /etc/prometheus/prometheus.yml

# Vérifier les targets dans Prometheus UI
# http://MONITORING_HOST:9090/targets
```

### Grafana ne se connecte pas à Prometheus
```bash
# Vérifier que Prometheus est accessible
docker exec beamax-grafana wget -O- http://prometheus:9090/api/v1/status/config

# Vérifier les datasources dans Grafana UI
# Configuration > Data Sources
```

### Alertes ne sont pas envoyées
```bash
# Vérifier les alertes actives dans Prometheus
# http://MONITORING_HOST:9090/alerts

# Vérifier Alertmanager
# http://MONITORING_HOST:9093/#/alerts

# Tester le webhook
curl -X POST http://localhost:8000/api/v2/webhooks/alertmanager \
  -H "Content-Type: application/json" \
  -d '{"alerts":[{"status":"firing","labels":{"alertname":"test"}}]}'
```

## 📝 Checklist de Déploiement

- [ ] Network Docker `beamax-network` créé
- [ ] Configuration Telegram dans `.env` (optionnel)
- [ ] Services lancés: `docker-compose up -d`
- [ ] Tous les services "healthy": `docker-compose ps`
- [ ] Prometheus scrape l'API: http://MONITORING_HOST:9090/targets
- [ ] Grafana accessible: http://MONITORING_HOST:3002
- [ ] Login Grafana: admin / ${GRAFANA_ADMIN_PASSWORD}
- [ ] 3 dashboards visibles dans Grafana
- [ ] Webhook Telegram implémenté dans l'API
- [ ] Test alerte Telegram fonctionnel

## 🔗 Ressources

- [Prometheus Documentation](https://prometheus.io/docs/)
- [Grafana Documentation](https://grafana.com/docs/)
- [Node Exporter](https://github.com/prometheus/node_exporter)
- [Alertmanager](https://prometheus.io/docs/alerting/latest/alertmanager/)
- [PromQL Cheat Sheet](https://promlabs.com/promql-cheat-sheet/)

## 📧 Support

Pour toute question ou problème:
1. Vérifier les logs: `docker-compose logs -f`
2. Consulter ce README
3. Vérifier les issues GitHub du projet
