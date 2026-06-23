# Béa — Rollback Plan

> Comment effectuer un rollback sûr pendant la Developer Preview / Public Beta limitée.

---

## Critères de rollback immédiat

Rollback **immédiat** si l'un de ces cas se présente:

- L'API ne démarre pas sur `origin/main`
- Une fuite de secret est confirmée (voir [INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md))
- Toutes les missions échouent (> 90% sur 10 missions consécutives)
- La mémoire publique contient des données privées détectées par l'audit
- Un test critique (`pytest-hardening`) casse sur `main`

---

## 1. Rollback code (git)

```bash
# Identifier le dernier commit stable
git log --oneline -10

# Revenir au commit précédent (non destructif)
git checkout <stable-commit-hash>
# Ou revenir d'un commit:
git checkout HEAD~1

# Redémarrer l'API
python scripts/run_api_local.py
```

**Alternative:** Revert un merge commit spécifique:

```bash
git revert -m 1 <merge-commit-hash>
git push origin main
```

Ne jamais `git push --force` sur `main`.

## 2. Rollback release (tag)

```bash
# Lister les tags
git tag -l

# Revenir à un tag stable
git checkout <stable-tag>
python scripts/run_api_local.py
```

## 3. Rollback config (.env)

Garder toujours une backup de la dernière config fonctionnelle:

```bash
# Avant tout changement de config:
cp .env .env.backup

# Pour restaurer:
cp .env.backup .env
# Redémarrer l'API
```

**Points critiques à vérifier après rollback de config:**
- `OPENROUTER_API_KEY` est valide
- `BEA_API_TOKEN` est défini
- `BEA_CONTINUOUS_IMPROVEMENT=0`
- `BEA_CORS_ORIGINS` ne contient pas `*`

## 4. Rollback APK

L'APK v3 n'est pas encore validé en CI. Si l'APK casse:

1. L'API v1 est toujours disponible (rollback Flutter)
2. Demander aux testeurs d'utiliser l'API directement (curl)
3. Ne pas forcer une mise à jour APK tant que v3 n'est pas validée

## 5. Rollback memory seed (public)

Le seed public est non destructif — il ajoute des items mais n'en supprime jamais.

```bash
# Vérifier le seed actuel
python scripts/seed_bea_memory.py --report --profile public

# Si le seed public contient des données privées (bug):
# 1. NE PAS utiliser --apply (désactivé)
# 2. Identifier les items problématiques:
python scripts/audit_memory_store.py --dry-run --privacy-scan --json

# 3. Restaurer le seed depuis la version précédente:
git checkout <stable-commit> -- scripts/seed_bea_memory.py
python scripts/seed_bea_memory.py --report --profile public

# 4. Si des items privés ont été seedés dans le store local:
#    Ne PAS supprimer manuellement sans backup.
#    Faire un backup d'abord:
cp workspace/operational_memory.db workspace/operational_memory.db.backup
#    Puis nettoyer manuellement via SQL si nécessaire:
#    sqlite3 workspace/operational_memory.db
#    DELETE FROM memory_items WHERE title = 'titre problématique';
```

## 6. Règles de sécurité pour les rollbacks

| Règle | Pourquoi |
|-------|----------|
| **Toujours backup avant rollback** | Ne pas perdre de données |
| **Ne jamais `--force` push sur main** | Écrase l'historique |
| **Ne jamais `docker compose down -v`** | Supprime les volumes (Postgres, Qdrant) |
| **Ne jamais rollback en écrasant des données privées** | Les données privées des testeurs doivent être préservées |
| **Documenter le rollback** | Postmortem obligatoire |

## 7. Après un rollback

1. **Vérifier la santé:** `curl http://localhost:8000/health`
2. **Vérifier les gates:** `python scripts/validate_local.py --quick`
3. **Notifier les testeurs** si le rollback affecte leur expérience
4. **Ouvrir un incident:** utiliser le template incident_report.yml
5. **Postmortem** dans les 48h: voir [INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md)
