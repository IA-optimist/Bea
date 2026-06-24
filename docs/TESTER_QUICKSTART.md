# Béa — Tester Quickstart

> **Developer Preview — Private Beta v0.1**
> 7 étapes pour commencer à tester en moins de 15 minutes.

---

## Étape 1 — Cloner le repo

```bash
git clone https://github.com/IA-optimist/Bea.git
cd Bea
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows PowerShell:
.venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

---

## Étape 2 — Configurer .env

```bash
cp .env.example .env
```

Éditer `.env` et remplir **uniquement** ces valeurs minimales :

```bash
# LLM — OpenRouter free tier suffit pour tester
OPENROUTER_API_KEY=sk-or-v1-your-key-here

# Auth admin
BEA_ADMIN_PASSWORD=un-mot-de-passe-fort-que-vous-choisissez
BEA_SECRET_KEY=your-random-32-char-hex-key

# Base de données Docker
DATABASE_URL=postgresql://bea:bea@localhost:5432/beamax
REDIS_URL=redis://localhost:6379/0

# NE PAS activer pour les tests :
# BEA_CONTINUOUS_IMPROVEMENT=1  ← laisser désactivé
# BEA_SKIP_IMPROVEMENT_GATE     ← ne jamais utiliser
```

**Ne jamais committer votre .env.** Il est dans `.gitignore`.

---

## Étape 3 — Lancer l'API

```bash
# Démarrer Docker (Postgres, Redis, Qdrant)
docker compose up -d

# Migrations base de données
python -m core.db.migrate

# Seed mémoire publique (neutre, sans données privées)
python scripts/seed_bea_memory.py --profile public

# Démarrer l'API
python scripts/run_api_local.py
```

---

## Étape 4 — Vérifier /health

```bash
curl http://localhost:8000/health
```

Réponse attendue :
```json
{"status": "ok", "version": "0.1.0-dev-preview"}
```

---

## Étape 5 — Lancer une mission test SAFE

Obtenir un token d'accès :
```bash
curl -X POST http://localhost:8000/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "votre-BEA_ADMIN_PASSWORD"}'
```

Soumettre une mission safe :
```bash
TOKEN="votre-token-jwt"

curl -X POST http://localhost:8000/api/v3/missions \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"goal": "Résume le README du projet.", "mode": "auto"}'
```

### Missions SAFE recommandées

Ces missions sont sans risque et couvrent les cas nominaux :

```
"Résume le README du projet."
"Explique l'architecture du repo."
"Propose une amélioration documentaire."
"Analyse une erreur de test fictive : AssertionError at line 42."
"Génère un plan de correction sans modifier le code."
```

### Missions à ÉVITER pendant la bêta

Voir `docs/TESTER_SAFETY_RULES.md` pour la liste complète.

---

## Étape 6 — Vérifier que les logs sont redactés

```bash
# Vérifier que les secrets n'apparaissent pas dans les logs
grep -r "sk-or-v1-" logs/ 2>/dev/null || echo "OK: no raw keys in logs"
grep -r "Bearer " logs/ 2>/dev/null | head -3
```

Les logs doivent montrer `[REDACTED]` à la place des secrets.

---

## Étape 7 — Envoyer votre feedback

Utiliser les templates GitHub :
- **Bug** : `.github/ISSUE_TEMPLATE/bug_report.yml`
- **Feedback** : `.github/ISSUE_TEMPLATE/beta_feedback.yml`
- **Incident sécurité** : `.github/ISSUE_TEMPLATE/security_report.md`

**Toujours redacter les logs avant de les coller dans une issue.**
Voir `docs/FEEDBACK_GUIDE.md` pour le format complet.

---

## Problèmes courants

| Symptôme | Cause probable | Solution |
|----------|---------------|----------|
| `/health` renvoie 503 | Docker non démarré | `docker compose up -d` |
| `401 Unauthorized` | Token manquant ou expiré | Refaire `/auth/token` |
| Mission bloquée en `PENDING` | Pas de provider LLM | Vérifier `OPENROUTER_API_KEY` |
| `qdrant connection refused` | Qdrant non démarré | `docker compose up -d qdrant` |

Voir `docs/TROUBLESHOOTING.md` pour plus de détails.
