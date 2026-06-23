# Béa — Incident Response

> Procédure de réponse aux incidents pendant la Developer Preview / Public Beta limitée.

---

## Processus général (tous incidents)

```
1. STOP EXPOSURE     → Arrêter la cause immédiate
2. PRESERVE EVIDENCE → Capturer logs, commit, config (redacted)
3. REVOKE SECRETS    → Rotater clés/tokens si compromis
4. ROTATE CREDENTIALS→ Générer nouvelles clés
5. NOTIFY TESTERS    → Si l'incident les affecte
6. PATCH             → Corriger le code/config
7. POSTMORTEM        → Documenter dans les 48h
```

---

## Type 1: Fuite de secret (API key, token)

**Critères:** Une clé API, un token, ou un mot de passe apparaît dans les logs,
un artifact, ou un memory item.

### Étapes

1. **STOP:** Arrêter l'API immédiatement (`Ctrl+C`)
2. **PRESERVE:**
   ```bash
   cp logs/api.log /tmp/incident_logs.txt
   cp .env /tmp/incident_env.txt  # NE JAMAIS partager ce fichier
   git rev-parse HEAD > /tmp/incident_commit.txt
   ```
3. **REVOKE:** Aller sur le dashboard du provider (OpenRouter, etc.) et révoquer
   la clé exposée
4. **ROTATE:** Générer une nouvelle clé et mettre à jour `.env`
5. **NOTIFY:** Si des testeurs ont pu voir la clé, les notifier de ne pas l'utiliser
6. **PATCH:**
   - Vérifier le redacteur: `core/observability/redactor.py`
   - Identifier pourquoi le secret n'a pas été redacted
   - Ajouter le pattern manquant au redacteur
7. **POSTMORTEM:** Documenter quel secret, où il est apparu, et comment empêcher la récurrence

**Ne JAMAIS** poster un secret exposé dans une issue GitHub publique.
Utiliser le template `security_report.md` (privé) ou GitHub Security Advisories.

---

## Type 2: Fuite de données personnelles

**Critères:** Des données personnelles (nom, email, téléphone) apparaissent dans
un artifact, un memory item, ou des logs partagées.

### Étapes

1. **STOP:** Arrêter l'API
2. **PRESERVE:** Capturer les logs (redacted)
3. **AUDIT:**
   ```bash
   python scripts/audit_memory_store.py --dry-run --privacy-scan --json
   ```
4. **NOTIFY:** Notifier la personne concernée si identifiable
5. **PATCH:**
   - Supprimer l'item du store local (avec backup préalable)
   - Vérifier le seed: `python scripts/seed_bea_memory.py --report --profile public`
   - Si l'item vient du seed public: rollback le seed (voir [ROLLBACK_PLAN.md](ROLLBACK_PLAN.md))
6. **POSTMORTEM:** Comment la donnée a-t-elle été ingérée?

---

## Type 3: Faux SUCCESS / artifact invalide

**Critères:** Une mission est marquée `DONE` / `SUCCESS` mais l'artifact est
invalide (syntax error, JSON cassé, fichier manquant).

### Étapes

1. **PRESERVE:**
   ```bash
   # Capturer le mission_id et l'artifact
   ls workspace/artifacts/
   grep "mission_id" logs/api.log | tail -5
   ```
2. **VERIFY:**
   ```bash
   # Vérifier l'artifact manuellement
   python workspace/artifacts/<file>.py  # SyntaxError?
   python -m json.tool <artifact>.json   # JSONDecodeError?
   ```
3. **PATCH:**
   - Si le gate d'artifact a un bug: corriger le gate
   - Si le provider a retourné du code invalide marqué comme valide: renforcer la validation
   - Ajouter un test de régression
4. **NOTIFY:** Si le testeur a reçu un faux SUCCESS, l'informer que l'artifact est invalide
5. **POSTMORTEM:** Pourquoi le gate n'a pas attrapé l'erreur?

---

## Type 4: Hallucination massive du provider

**Critères:** Le provider retourne des résultats farfelus, du contenu inventé,
des fichiers qui n'existent pas, ou des réponses hors-sujet à grande échelle.

### Étapes

1. **STOP:** Arrêter l'API ou suspendre les missions
2. **VERIFY:**
   - Vérifier le modèle utilisé dans les logs (`model_used`)
   - Vérifier le statut du provider (changement de modèle silencieux?)
3. **PATCH:**
   - Forcer un modèle spécifique dans `.env` au lieu de laisser le provider choisir
   - Ajouter des guardrails de validation plus stricts
4. **NOTIFY:** Notifier les testeurs que les résultats récents peuvent être peu fiables
5. **POSTMORTEM:** Quel modèle a causé l'hallucination? Ajouter à KNOWN_LIMITATIONS.md

---

## Type 5: Abuse / rate-limit

**Critères:** Un testeur ou un script envoie trop de requêtes, cause des 429,
ou tente d'abuser de l'API.

### Étapes

1. **STOP:** Bloquer l'IP ou le token si possible
2. **VERIFY:**
   ```bash
   grep "429" logs/api.log | tail -20
   grep "rate_limit" logs/api.log | tail -20
   ```
3. **PATCH:**
   - Renforcer `BEA_RATE_LIMIT_PER_MINUTE`
   - Vérifier que `BEA_CORS_ORIGINS` ne contient pas `*`
4. **NOTIFY:** Contacter le testeur si identifiable
5. **POSTMORTEM:** Le rate-limit était-il correctement configuré?

---

## Type 6: Bug critique API (500 sur endpoint clé)

**Critères:** Un endpoint critique (`/api/v3/missions`, `/health`) retourne 500.

### Étapes

1. **STOP:** Si l'erreur affecte tous les testeurs, rollback (voir [ROLLBACK_PLAN.md](ROLLBACK_PLAN.md))
2. **PRESERVE:**
   ```bash
   grep "500" logs/api.log | tail -20
   git rev-parse HEAD
   ```
3. **VERIFY:**
   ```bash
   curl -s -H "Authorization: Bearer $BEA_API_TOKEN" \
     http://localhost:8000/api/v3/missions
   ```
4. **PATCH:** Corriger le bug, ajouter un test de régression
5. **POSTMORTEM:** Pourquoi le test n'a pas attrapé l'erreur?

---

## Type 7: Bug critique APK

**Critères:** L'APK crash au démarrage ou un flux critique est cassé.

### Étapes

1. **STOP:** Demander aux testeurs d'utiliser l'API directement (curl)
2. **VERIFY:**
   - L'API v1 fonctionne encore (rollback Flutter)
   - L'API v3 répond correctement
3. **PATCH:** Corriger le bug Flutter, reconstruire l'APK
4. **POSTMORTEM:** Voir [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) — APK non validé en CI

---

## Template de postmortem

```markdown
## Postmortem: [titre de l'incident]

**Date:** YYYY-MM-DD
**Severity:** Critical / High / Medium / Low
**Incident type:** Secret leak / Data leak / False success / Hallucination / Abuse / API bug / APK bug

### Résumé
1-2 phrases décrivant l'incident.

### Timeline
- HH:MM — Détection
- HH:MM — Stop exposure
- HH:MM — Rotation des secrets (si applicable)
- HH:MM — Patch déployé
- HH:MM — Notification testeurs

### Impact
- Combien de testeurs affectés?
- Combien de missions échouées?
- Données compromises? (oui/non/détails redacted)

### Cause racine
Qu'est-ce qui a causé l'incident?

### Actions correctives
- [ ] Court terme: ...
- [ ] Moyen terme: ...
- [ ] Long terme: ...

### Leçons apprises
- ...
```
