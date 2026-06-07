# 🚀 Quick Start - Monitoring Stack BeaMax

## Accès Immédiat

### 📊 Grafana
- **URL**: http://MONITORING_HOST:3002
- **Username**: admin
- **Password**: ${GRAFANA_ADMIN_PASSWORD}

### 🔍 Prometheus
- **URL**: http://MONITORING_HOST:9090
- **Targets**: http://MONITORING_HOST:9090/targets
- **Alerts**: http://MONITORING_HOST:9090/alerts

### 🔔 Alertmanager
- **URL**: http://MONITORING_HOST:9093

### 📈 Node Exporter
- **URL**: http://MONITORING_HOST:9100/metrics

## 📋 Dashboards Disponibles

Une fois connecté à Grafana, vous trouverez 3 dashboards pré-configurés:

1. **BeaMax - System Monitoring** (UID: `beamax-system`)
   - Métriques système: CPU, RAM, Disque, Network
   - État des conteneurs Docker
   - Load average

2. **BeaMax - API Monitoring** (UID: `beamax-api`)
   - Request Rate & Response Time
   - Error Rate & Success Rate
   - Top Endpoints & Slowest Endpoints
   - API Health Status

3. **BeaMax - Business Metrics** (UID: `beamax-business`)
   - Business Tasks & Success Rate
   - Agent Executions
   - Revenue & Cost Tracking
   - LLM API Calls & Cache Performance

## 🎯 Premiers Pas

### 1. Connexion à Grafana
```bash
# Ouvrir dans le navigateur
firefox http://MONITORING_HOST:3002

# Login: admin / ${GRAFANA_ADMIN_PASSWORD}
```

### 2. Navigation
- Cliquer sur l'icône "☰" (menu hamburger) en haut à gauche
- Sélectionner "Dashboards"
- Ouvrir le dossier "BeaMax"
- Cliquer sur un dashboard

### 3. Vérifier les Métriques
Les dashboards se mettent à jour automatiquement toutes les 10-30 secondes.

## 🔔 Configuration des Alertes Telegram

Pour recevoir les alertes sur Telegram:

### 1. Créer un Bot Telegram
```bash
# Ouvrir Telegram et chercher @BotFather
# Envoyer: /newbot
# Suivre les instructions
# Copier le token: 123456789:ABCdefGHIjklMNOpqrsTUVwxyz
```

### 2. Obtenir le Chat ID
```bash
# Envoyer un message à votre bot
# Visiter dans le navigateur:
curl https://api.telegram.org/bot<VOTRE_TOKEN>/getUpdates

# Trouver "chat":{"id":123456789}
```

### 3. Configurer dans .env
```bash
# Ajouter dans /root/Beamax-master/.env
echo "TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz" >> /root/Beamax-master/.env
echo "TELEGRAM_CHAT_ID=123456789" >> /root/Beamax-master/.env
```

### 4. Redémarrer l'API
```bash
cd /root/Beamax-master
docker compose restart api
```

## 🛠️ Commandes Utiles

### Statut des services
```bash
cd /root/Beamax-master/monitoring
docker compose -f docker-compose-monitoring.yml ps
```

### Logs
```bash
# Tous les services
docker compose -f docker-compose-monitoring.yml logs -f

# Service spécifique
docker compose -f docker-compose-monitoring.yml logs -f grafana
docker compose -f docker-compose-monitoring.yml logs -f prometheus
```

### Redémarrage
```bash
# Tous les services
docker compose -f docker-compose-monitoring.yml restart

# Service spécifique
docker compose -f docker-compose-monitoring.yml restart grafana
```

### Arrêt
```bash
docker compose -f docker-compose-monitoring.yml down
```

### Relancer
```bash
docker compose -f docker-compose-monitoring.yml up -d
```

## 📊 Exemples de Requêtes PromQL

Vous pouvez tester ces requêtes dans Prometheus (http://MONITORING_HOST:9090):

### CPU Usage
```promql
100 - (avg(rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)
```

### Memory Usage
```promql
(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100
```

### API Request Rate
```promql
rate(http_requests_total[5m])
```

### API P95 Latency
```promql
histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))
```

### Error Rate
```promql
rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m]) * 100
```

## ✅ Checklist de Vérification

- [ ] Grafana accessible sur http://MONITORING_HOST:3002
- [ ] Login avec admin / ${GRAFANA_ADMIN_PASSWORD} réussi
- [ ] 3 dashboards visibles dans le dossier BeaMax
- [ ] Dashboard System affiche des métriques CPU/RAM
- [ ] Dashboard API affiche request rate > 0
- [ ] Prometheus targets "UP" sur http://MONITORING_HOST:9090/targets
- [ ] (Optionnel) Alertes Telegram configurées

## 🆘 Dépannage Rapide

### Grafana ne charge pas
```bash
docker logs beamax-grafana --tail 50
docker restart beamax-grafana
```

### Pas de métriques API
```bash
# Vérifier que l'API expose /metrics
curl http://localhost:8000/metrics

# Vérifier les targets Prometheus
curl http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | {job: .labels.job, health: .health}'
```

### Dashboards vides
```bash
# Attendre 1-2 minutes que les premières métriques soient collectées
# Vérifier la datasource Prometheus dans Grafana
# Configuration > Data Sources > Prometheus
# Cliquer sur "Test" pour vérifier la connexion
```

## 📚 Documentation Complète

Voir [README.md](./README.md) pour la documentation détaillée.

---

**Support**: Consultez les logs avec `docker compose logs -f` en cas de problème.
