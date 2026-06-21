# LLM Providers — Béa

Guide de configuration et diagnostic des providers LLM.

## Providers disponibles

| Provider | Variable clé | Usage |
|---|---|---|
| **OpenRouter** | `OPENROUTER_API_KEY` | Provider cloud principal (routing multi-modèles) |
| **Ollama** | `OLLAMA_HOST` | Provider local (gemma4:12b recommandé) |
| **Codex direct** | auth via Hermes | Cerveau Béa (bot Telegram) |
| **OpenAI** | `OPENAI_API_KEY` | Fallback cloud optionnel |
| **Anthropic** | `ANTHROPIC_API_KEY` | Fallback cloud optionnel |

---

## Configurer OpenRouter

1. Créer un compte sur [openrouter.ai](https://openrouter.ai)
2. Générer une clé API dans *Settings → API Keys*
3. Ajouter dans `.env` :
   ```
   OPENROUTER_API_KEY=sk-or-v1-...
   ```

**Modèles recommandés (gratuits) :**
```env
OPENROUTER_MODEL_FAST=openai/gpt-oss-20b:free
OPENROUTER_MODEL_STANDARD=openai/gpt-oss-20b:free
OPENROUTER_MODEL_STRONG=openai/gpt-oss-120b:free
ORCHESTRATOR_MODEL=openai/gpt-oss-120b:free
```

**Ne jamais commiter `.env`** — il est dans `.gitignore`.

---

## Configurer Ollama

1. Installer Ollama : <https://ollama.com/download>
2. Démarrer le service (Windows — se relance automatiquement au boot) :
   ```cmd
   ollama serve
   ```
   Sur Windows, Ollama tourne généralement en arrière-plan après installation.
   Vérifier qu'il écoute bien :
   ```cmd
   curl http://127.0.0.1:11434/api/version
   ```
   Réponse attendue : `{"version":"..."}`
3. Lister les modèles disponibles :
   ```cmd
   ollama list
   ```
4. Télécharger le modèle recommandé (RTX 5070 Blackwell, 12 B) :
   ```cmd
   ollama pull gemma4:12b
   ```
5. Vérifier l'installation :
   ```cmd
   ollama list
   # gemma4:12b   ...   xxxx MB
   ```
6. Configurer dans `.env` :
   ```
   OLLAMA_HOST=http://127.0.0.1:11434
   OLLAMA_MODEL_MAIN=gemma4:12b
   OLLAMA_MODEL_FAST=gemma4:12b
   OLLAMA_MODEL_CODE=gemma4:12b
   ```

---

## Différence CLI vs Bea_API service

| Contexte | Chargement `.env` | Comportement |
|---|---|---|
| **`bea_api_service.cmd`** | Automatique (Windows CMD `set`) | OpenRouter + Ollama disponibles |
| **Terminal CLI nu** | ❌ Manuel requis | Échoue si env non exporté |
| **`scripts/run_api_local.py`** | Manuel via `.env` | Dépend de l'export |

### Exporter les variables en CLI (bash/WSL)

```bash
set -a; source .env; set +a
python scripts/provider_healthcheck.py
```

### Exporter en PowerShell / CMD

```cmd
for /f "tokens=1,2 delims==" %i in (.env) do set %i=%j
python scripts\provider_healthcheck.py
```

### Pourquoi CLI échoue souvent

- `OPENROUTER_API_KEY` absent → `_build_openrouter()` retourne `None`
- `OLLAMA_HOST` pointe vers `http://ollama:11434` (hostname Docker) non résolvable en local
- Résultat : `RuntimeError: Aucun LLM disponible pour le rôle '...'`

**Solution** : exporter les variables manuellement **ou** utiliser `bea_api_service.cmd`.

### Crash Unicode Windows (`UnicodeEncodeError`)

Sur les consoles Windows avec un code page non-UTF-8 (cp1252, cp850…), les anciens
symboles `✓` / `✗` pouvaient crasher le script. Depuis **PR #96**, `provider_healthcheck.py`
détecte automatiquement l'encodage de la console et affiche `OK`/`FAIL` à la place.
Si malgré tout un crash se produit :

```cmd
set PYTHONIOENCODING=utf-8
python scripts\provider_healthcheck.py
```

---

## Diagnostic provider

```bash
# Texte lisible
python scripts/provider_healthcheck.py

# JSON machine-readable
python scripts/provider_healthcheck.py --json
```

### Sortie exemple — READY

```
======================================================
  Béa — LLM Provider Health Check  [READY] ✓
======================================================

  OpenRouter key present : present
  OpenRouter usable      : yes

  Ollama reachable       : yes
  Ollama host used       : http://127.0.0.1:11434
  Ollama models          : gemma4:12b

  Default provider       : openrouter
  Fallback provider      : ollama
  Final status           : READY
======================================================
```

### Sortie exemple — DEGRADED

```
  Final status           : DEGRADED
  Hints:
    Mode dégradé: OpenRouter absent, Ollama disponible (gemma4:12b).
    Les rôles cloud utiliseront Ollama en fallback.
```

### Sortie exemple — UNAVAILABLE

```
  Final status           : UNAVAILABLE
  Hints:
    Aucun provider LLM disponible. Configurer OPENROUTER_API_KEY
    ou démarrer Ollama (ollama serve).
```

> **UNAVAILABLE n'est pas un échec CI.** Les gates projet (ruff, pytest, coverage)
> passent indépendamment des providers. UNAVAILABLE signifie que les **missions LLM**
> ne peuvent pas s'exécuter à ce moment — il faut configurer au moins un provider.

### Fallback attendu

```
Aucun provider → UNAVAILABLE (RuntimeError à l'exécution de mission)
Ollama seul    → DEGRADED (missions locales OK, rôles cloud bridgés sur Ollama)
OpenRouter     → READY   (rôles cloud + fallback Ollama si configuré)
```

---

## Comportement de fallback

```
OpenRouter disponible
  └─→ utiliser OpenRouter (rôles cloud)
      └─→ fallback Ollama si OpenRouter échoue (rôles CLOUD_PREFERRED)

OpenRouter absent, Ollama disponible
  └─→ DEGRADED : Ollama pour tous les rôles non-LOCAL_ONLY
      └─→ gemma4:12b recommandé

Aucun provider disponible
  └─→ UNAVAILABLE : RuntimeError explicite avec hint de configuration
```

### Rôles LOCAL_ONLY (jamais de cloud)

- `code`, `vision`, `uncensored` : toujours Ollama, jamais de fallback cloud

### Auto-découverte Ollama

Si `OLLAMA_HOST=http://ollama:11434` (hostname Docker) est configuré mais
injoignable, Béa essaie automatiquement `http://127.0.0.1:11434` puis
`http://localhost:11434` avant de déclarer Ollama indisponible.

---

## Provider recommandé en local

**gemma4:12b via Ollama** — modèle GPU local optimisé pour RTX 5070 Blackwell.

```bash
ollama pull gemma4:12b
```

Configurer dans `.env` :
```
OLLAMA_MODEL_MAIN=gemma4:12b
OLLAMA_MODEL_FAST=gemma4:12b
OLLAMA_MODEL_CODE=gemma4:12b
```

---

## Sécurité

- **Ne jamais commiter** `OPENROUTER_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`
- Le diagnostic `provider_healthcheck.py` n'affiche jamais les valeurs de clés
- Les logs indiquent seulement la présence/absence de la clé (`yes/no`)
- En cas de doute : révoquer et régénérer la clé sur le portail du provider
