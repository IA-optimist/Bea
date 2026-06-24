# Béa — Private Beta Scope v0.1

> Status: **Developer Preview — Private Beta**
> Date: 2026-06-24

---

## Version cible
**0.1 private beta / developer preview**

Béa n'est pas stable, pas production-ready, pas autonome sans supervision.
C'est une preview technique pour des testeurs qui veulent comprendre et casser le système.

---

## Nombre de testeurs
**5 à 10 personnes maximum**

Cette limite est volontaire : Béa ne supporte pas plusieurs tenants, et chaque incident doit être traçable à un testeur.

---

## Public cible
Testeurs **techniques**, pas grand public :
- Développeurs Python / FastAPI
- Personnes habituées aux systèmes multi-agents
- Capables de lire des logs, des tracebacks et des rapports JSON
- À l'aise avec Docker, Python venv, et les variables d'environnement

---

## Surfaces autorisées

| Surface | Statut | Notes |
|---------|--------|-------|
| API locale (`localhost:8000`) | ✅ Recommandée | Configuration principale |
| Web cockpit (`/cockpit.html`) | ✅ Si API stable | Interface de contrôle basique |
| Telegram bot | ✅ Si configuré par l'owner | Requiert BEA_ADMIN_PASSWORD fort |
| Flutter APK (Pixel/Android) | ⚠️ Expérimental | Build CI OK, validation physique HUMAN_REQUIRED |
| OpenRouter (free tier) | ✅ Recommandé | `gpt-oss-120b:free` pour missions |
| Ollama local | ✅ Optionnel | `gemma4:12b` — limitations connues (forge-builder) |
| Déploiement contrôlé (Railway) | ⚠️ Owner uniquement | Pas de multi-tenant |

---

## Surfaces interdites ou hors scope

| Surface | Raison |
|---------|--------|
| Production multi-tenant | Pas d'isolation utilisateur sûre |
| Autonomie non supervisée (`BEA_CONTINUOUS_IMPROVEMENT=1`) | Désactivé par défaut, ne pas activer |
| Actions destructives sur systèmes tiers | Hors scope |
| Secrets réels dans les prompts | Voir `docs/TESTER_SAFETY_RULES.md` |
| Données sensibles réelles | Voir `docs/PRIVACY_FOR_TESTERS.md` |
| Claims publics sur la stabilité de Béa | Béa n'est pas stable |
| Internet public sans reverse proxy TLS | Rate-limiting actif mais insuffisant seul |
| Exploitation de systèmes tiers | Interdit |
| Cyber offensif | Interdit |

---

## Critères de sortie de bêta privée

Pour passer à une bêta publique, les critères suivants doivent être satisfaits :

- [ ] Mission simple (résumé README, explication architecture) : exécutée sans crash par 3+ testeurs
- [ ] Logs entièrement redactés (aucune fuite de token dans les logs testeurs)
- [ ] Auth active et testée : `/health` public, reste protégé
- [ ] Mémoire publique clean : `audit_memory_store.py --apply` exécuté, 0 item privé
- [ ] Feedback template utilisé : au moins 3 issues créées via templates GitHub
- [ ] Rollback documenté et testé : kill switch API fonctionnel
- [ ] APK validée sur device physique (checklist `docs/APK_PHYSICAL_DEVICE_VALIDATION.md`)
- [ ] Secrets historiques rotés (action propriétaire)
- [ ] `InMemorySessionStore` → `RedisSessionStore` pour multi-worker
- [ ] CORS configuré explicitement (pas de wildcard)

---

## Responsabilités

**Owner (Max) :**
- Gestion des tokens testeurs
- Surveillance des incidents
- Rollback si nécessaire
- Ne jamais partager BEA_ADMIN_PASSWORD

**Testeurs :**
- Tester dans un environnement local ou dédié
- Ne pas utiliser de données réelles
- Rapporter via templates GitHub
- Redacter les logs avant partage
