# ✅ Checklist d'Intégration - Monitoring BeaMax

## État Actuel du Déploiement

### ✅ Complété
- [x] Docker Compose créé et testé
- [x] Prometheus configuré et opérationnel
- [x] Grafana déployé avec 3 dashboards
- [x] Node Exporter pour métriques système
- [x] Alertmanager avec règles d'alerte
- [x] Ports ouverts dans le firewall (3002, 9090, 9093, 9100)
- [x] Network Docker configuré
- [x] Configuration de scraping API
- [x] Documentation complète

### ⏳ À Faire (Optionnel)

#### 1. Intégration Webhook Telegram (5 min)

**Étape 1**: Créer le bot
```bash
# 1. Ouvrir Telegram et chercher @BotFather
# 2. Envoyer: /newbot
# 3. Suivre les instructions
# 4. Copier le token
```

**Étape 2**: Obtenir le Chat ID
```bash
# 1. Envoyer un message à votre bot
# 2. Récupérer le chat ID:
curl https://api.telegram.org/bot<VOTRE_TOKEN>/getUpdates | jq '.result[0].message.chat.id'
```

**Étape 3**: Configurer
```bash
# Ajouter dans .env
echo "TELEGRAM_BOT_TOKEN=votre_token" >> /root/Beamax-master/.env
echo "TELEGRAM_CHAT_ID=votre_chat_id" >> /root/Beamax-master/.env
```

**Étape 4**: Intégrer dans l'API
```python
# Copier le contenu de monitoring/api_webhook_integration.py
# Ou ajouter simplement dans main.py:

@app.post("/api/v2/webhooks/alertmanager")
async def alertmanager_webhook(request: Request):
    payload = await request.json()
    alerts = payload.get('alerts', [])
    
    # Log ou traitement des alertes
    for alert in alerts:
        logger.warning(f"Alert: {alert.get('labels', {}).get('alertname')}")
    
    return {"status": "success", "alerts": len(alerts)}
```

**Étape 5**: Tester
```bash
# Redémarrer l'API
docker compose restart api

# Tester l'endpoint
curl http://localhost:8000/api/v2/webhooks/alertmanager \
  -H "Content-Type: application/json" \
  -d '{"alerts":[{"status":"firing","labels":{"alertname":"test"}}]}'
```

#### 2. Vérification Finale (2 min)

```bash
# Exécuter le script de test
cd /root/Beamax-master/monitoring
./test_stack.sh

# Vérifier l'accès Grafana
curl -I http://MONITORING_HOST:3002/login

# Vérifier les targets Prometheus
curl http://localhost:9090/api/v1/targets | jq '.data.activeTargets[].health'
```

#### 3. Accès Grafana (1 min)

1. Ouvrir http://MONITORING_HOST:3002
2. Login: `admin` / `${GRAFANA_ADMIN_PASSWORD}`
3. Menu (☰) > Dashboards > BeaMax
4. Ouvrir un dashboard pour vérifier les métriques

#### 4. Personnalisation (Optionnel)

**Ajouter des métriques business dans l'API**:
```python
from prometheus_client import Counter, Histogram

# Définir des métriques
tasks_total = Counter('business_tasks_total', 'Total business tasks', ['task_type'])
task_duration = Histogram('business_task_duration_seconds', 'Task duration')

# Utiliser dans le code
tasks_total.labels(task_type='data_processing').inc()

with task_duration.time():
    # Votre code business
    pass
```

**Ajuster les seuils d'alerte**:
```bash
# Éditer les règles
nano /root/Beamax-master/deploy/monitoring/prometheus/alerts.yml

# Recharger Prometheus
curl -X POST http://localhost:9090/-/reload
```

## 📊 URLs de Référence

| Service | URL | Notes |
|---------|-----|-------|
| **Grafana** | http://MONITORING_HOST:3002 | admin / ${GRAFANA_ADMIN_PASSWORD} |
| **Prometheus** | http://MONITORING_HOST:9090 | Métriques et requêtes |
| **Alertmanager** | http://MONITORING_HOST:9093 | État des alertes |
| **Node Exporter** | http://MONITORING_HOST:9100 | Métriques brutes |
| **API Metrics** | http://MONITORING_HOST:8000/metrics | Métriques API |

## 🔧 Commandes Utiles

```bash
# Voir le statut
cd /root/Beamax-master/monitoring
docker compose -f docker-compose-monitoring.yml ps

# Logs en temps réel
docker compose -f docker-compose-monitoring.yml logs -f

# Redémarrer un service
docker compose -f docker-compose-monitoring.yml restart grafana

# Arrêter la stack
docker compose -f docker-compose-monitoring.yml down

# Relancer la stack
docker compose -f docker-compose-monitoring.yml up -d
```

## 📚 Documentation

- `QUICKSTART.md` - Guide de démarrage rapide
- `README.md` - Documentation complète
- `DEPLOYMENT_REPORT.md` - Rapport de déploiement
- `api_webhook_integration.py` - Code webhook Telegram
- `telegram_webhook.py` - Module webhook standalone

## ✅ Validation Finale

Cocher quand complété:

- [ ] Grafana accessible et login OK
- [ ] 3 dashboards visibles et fonctionnels
- [ ] Métriques API visibles dans les dashboards
- [ ] Métriques système (CPU, RAM) visibles
- [ ] Alertes configurées dans Prometheus
- [ ] (Optionnel) Telegram configuré et testé
- [ ] Documentation lue et comprise

## 🎉 Félicitations !

Votre stack de monitoring est maintenant opérationnelle !

**Prochaines étapes recommandées**:
1. Personnaliser les dashboards selon vos besoins
2. Ajuster les seuils d'alerte
3. Ajouter des métriques business custom
4. Configurer les alertes Telegram
5. Mettre en place un backup des dashboards Grafana

Pour toute question, consulter la documentation ou les logs.
