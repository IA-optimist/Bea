# Install Test Report — PHASE 1

Generated: 2026-06-27

## Docs lues

### README.md
- Présent. Contient une description générale du projet.
- **Bug P3**: README.md ne documente pas les étapes d'installation pour un testeur externe. Le README principal est orienté développeur, pas testeur beta.

### README_PUBLIC_BETA.md
- ✅ Clair. Contient: What Is Proved, Partially Validated, Experimental/Out of Scope, Human Required.
- **OK**: `PUBLIC_BETA_READY: false` en haut.
- **Bug P3**: Pas de commandes concrètes d'installation dans ce fichier. Il renvoie au Quickstart mais ne le résume pas.

### docs/TESTER_QUICKSTART.md
- ✅ Présent et concis.
- Commandes listées:
  ```
  python -m venv .venv
  .venv\Scripts\activate
  python -m pip install -e .
  copy .env.example .env
  python scripts/validate_local.py --quick
  python scripts/run_api_local.py
  ```
- **Bug P2**: La commande `python -m pip install -e .` suppose un `setup.py` ou `pyproject.toml` avec `[project]`. Vérification:
  ```
  setup.py: présent mais peut ne pas inclure toutes les deps runtime
  requirements.txt: ✅ présent (44 deps épinglées)
  requirements.lock: ✅ présent
  ```
  Un testeur externe qui suit exactement `pip install -e .` pourrait manquer des dépendances. La commande `pip install -r requirements.txt` serait plus sûre et n'est pas documentée dans le Quickstart.

- **Bug P3**: La commande `copy .env.example .env` est Windows-only. Sur Linux/macOS, c'est `cp`. Quickstart ne précise pas l'OS.

## Simulation installation propre

### Étapes simulées

1. `python -m venv .venv-test` → OK conceptuellement
2. `.venv-test\Scripts\activate` → OK Windows
3. `python -m pip install -r requirements.txt` → devrait fonctionner avec requirements.txt
4. `cp .env.example .env` → OK
5. Édition `.env` avec valeurs fictives:
   - `BEA_API_TOKEN=test-fake-token-1234`
   - `BEA_SECRET_KEY=fake-secret-key-xyz`
   - `OPENROUTER_API_KEY=DISABLED` (provider coupé)
6. `python scripts/validate_local.py --quick` → **PASSERAIT** (ne dépend pas des providers)
7. `python scripts/run_api_local.py` → **Lance l'API**

### Problèmes

1. **P2 — Installation doc incomplète**: `pip install -e .` ≠ `pip install -r requirements.txt`. Un testeur sur un venv propre aurait des ImportError.
2. **P3 — Commande Windows-only**: `copy` vs `cp`. Préciser l'OS dans le Quickstart.
3. **P3 — Migrations**: Pas de mention de migrations DB. Si PostgreSQL est utilisé, le testeur doit connaître l'adresse. Si SQLite fallback, c'est invisible.
4. **P3 — Docker vs local**: Le Quickstart dit de lancer l'API localement, mais la config Docker est dans `.env.example`. Un testeur junior sera confus.

## Verdict testeur junior

**Un testeur junior PEUT suivre le Quickstart mais heurtera 1-2 obstacles:**
- Dépendances manquantes si il fait `pip install -e .` sur un venv vide
- Confusion entre Docker et local si il lit .env.example (il y a des variables Docker)

**Note globale documentation installation: 3/5**
- Clair sur ce que c'est ✅
- Clair sur les prérequis ❌ (Python version, OS, Docker vs local)
- Commandes fonctionnelles ⚠️ (`pip install -e .` peut manquer des deps)
- Gestion erreurs ❌ (pas de section "si ça échoue")
- Testeur junior: difficile ❌

## Fichiers requis mais absents ou ambigus

| Fichier | Statut | Commentaire |
|---------|--------|-------------|
| `.env.example` | ✅ présent | Mais inclut des variables Docker qui confondent |
| `docs/TESTER_QUICKSTART.md` | ✅ présent | Trop court, manque gestion d'erreurs |
| `docs/BETA_TESTER_GUIDE.md` | ❓ à vérifier | Listé dans checklist mais non vérifié |
| `docs/FEEDBACK_GUIDE.md` | ✅ référencé | |
| `docs/TROUBLESHOOTING.md` | ✅ présent | |
