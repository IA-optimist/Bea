# Variables d'environnement — Béa

Variables requises et optionnelles pour l'API, le bot Telegram, et les services.
Sources : `config/settings.py`, `api/main.py`, `scripts/run_api_local.py`.

## Auth & Sécurité

| Variable | Défaut | Requis | Description |
|---|---|---|---|
| `BEA_API_TOKEN` | — | OUI | Token Bearer pour l'API REST (`Authorization: Bearer <token>`) |
| `BEA_ADMIN_PASSWORD` | — | OUI | Mot de passe pour le compte admin (cockpit + web UI) |
| `BEA_SECRET_KEY` | auto-généré | NON | Clé secrète pour la signature JWT ; auto-générée si vide |

## Réseau & API

| Variable | Défaut | Requis | Description |
|---|---|---|---|
| `BEA_API_BIND` | `127.0.0.1` | NON | Adresse d'écoute de l'API (mettre `0.0.0.0` pour accès réseau/Tailscale) |
| `BEA_PRODUCTION` | `0` | NON | `1`/`true` active le mode production (CORS strict, docs désactivées) |
| `CORS_ORIGINS` | `""` | NON | Liste d'origines CORS autorisées (séparées par virgule) |
| `ENABLE_API_DOCS` | `0` | NON | `1` expose `/docs` et `/redoc` (OpenAPI) — désactivé en prod |
| `ENABLE_STUB_ROUTES` | `false` | NON | `true` monte les routes stub/non-implémentées |

## Base de données

| Variable | Défaut | Requis | Description |
|---|---|---|---|
| `DATABASE_URL` | construit depuis POSTGRES_* | NON | URL complète PostgreSQL (prioritaire sur les vars individuelles) |
| `POSTGRES_HOST` | `postgres` | NON | Hôte PostgreSQL |
| `POSTGRES_USER` | `bea` | NON | Utilisateur PostgreSQL |
| `POSTGRES_PASSWORD` | — | OUI (prod) | Mot de passe PostgreSQL |
| `POSTGRES_DB` | `bea` | NON | Nom de la base |
| `WORKSPACE_DIR` | `./workspace` | NON | Dossier de travail local (SQLite, fichiers missions) |
| `BEA_ROOT` | auto-détecté | NON | Racine du projet Béa (fallback WORKSPACE_DIR) |

## Redis

| Variable | Défaut | Requis | Description |
|---|---|---|---|
| `REDIS_HOST` | `redis` | NON | Hôte Redis |
| `REDIS_PASSWORD` | — | NON | Mot de passe Redis |

## Qdrant (mémoire vectorielle)

| Variable | Défaut | Requis | Description |
|---|---|---|---|
| `QDRANT_HOST` | `qdrant` | NON | Hôte Qdrant |
| `QDRANT_API_KEY` | — | NON | Clé API Qdrant (Cloud uniquement) |
| `QDRANT_MCP_URL` | `http://qdrant-mcp:8000` | NON | URL du serveur MCP Qdrant |

## LLM — OpenRouter (provider principal)

| Variable | Défaut | Requis | Description |
|---|---|---|---|
| `OPENROUTER_API_KEY` | — | OUI | Clé API OpenRouter |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | NON | Base URL OpenRouter |
| `OPENROUTER_MODEL_FAST` | `mistralai/mistral-7b-instruct` | NON | Modèle rapide/économique |
| `OPENROUTER_MODEL_STANDARD` | `anthropic/claude-3.5-haiku` | NON | Modèle standard |
| `OPENROUTER_MODEL_STRONG` | `anthropic/claude-sonnet-4` | NON | Modèle fort pour les tâches complexes |

## LLM — Modèles par agent

| Variable | Défaut | Requis | Description |
|---|---|---|---|
| `ORCHESTRATOR_MODEL` | `anthropic/claude-sonnet-4.5` | NON | Modèle utilisé par le MetaOrchestrator |
| `ARCHITECT_MODEL` | `anthropic/claude-sonnet-4.5` | NON | Modèle de l'agent architecte |
| `CODER_MODEL` | `anthropic/claude-sonnet-4.5` | NON | Modèle de l'agent codeur |
| `SELF_IMPROVEMENT_MODEL` | `anthropic/claude-sonnet-4.5` | NON | Modèle pour la boucle d'auto-amélioration |
| `FAST_MODEL` | `openai/gpt-4o-mini` | NON | Modèle rapide (routing, classification) |
| `FALLBACK_MODEL` | `openai/gpt-4o-mini` | NON | Modèle de secours en cas d'échec |
| `VISION_MODEL` | `openai/gpt-4o-mini` | NON | Modèle vision (analyse photos/YouTube) |
| `ESCALATION_PROVIDER` | `claude` | NON | Provider d'escalade (`claude`, `openai`, `openrouter`) |
| `MODEL_STRATEGY` | `openai` | NON | Stratégie de routage principal |
| `MODEL_FALLBACK` | `ollama` | NON | Stratégie de fallback |

## LLM — Providers directs

| Variable | Défaut | Requis | Description |
|---|---|---|---|
| `OPENAI_API_KEY` | — | NON | Clé API OpenAI |
| `OPENAI_MODEL` | `gpt-4o` | NON | Modèle OpenAI standard |
| `OPENAI_MODEL_FAST` | `gpt-4o-mini` | NON | Modèle OpenAI rapide |
| `ANTHROPIC_API_KEY` | — | NON | Clé API Anthropic (Claude direct) |
| `ANTHROPIC_MODEL` | `claude-3-5-sonnet-20241022` | NON | Modèle Claude (direct API) |
| `GOOGLE_API_KEY` | — | NON | Clé API Google (Gemini) |
| `GOOGLE_MODEL` | `gemini-1.5-pro` | NON | Modèle Gemini |

## LLM — Ollama (local)

| Variable | Défaut | Requis | Description |
|---|---|---|---|
| `OLLAMA_HOST` | `http://ollama:11434` | NON | URL du serveur Ollama |
| `OLLAMA_MODEL_MAIN` | `mistral:7b` | NON | Modèle principal Ollama |
| `OLLAMA_MODEL_CODE` | `deepseek-coder-v2:16b` | NON | Modèle de code Ollama |
| `OLLAMA_MODEL_FAST` | `mistral:7b` | NON | Modèle rapide Ollama |
| `OLLAMA_MODEL_VISION` | `llava:7b` | NON | Modèle vision Ollama |

## LLM — Hermes/Codex (gateway locale)

| Variable | Défaut | Requis | Description |
|---|---|---|---|
| `CODEX_BASE_URL` | `http://127.0.0.1:8642/v1` | NON | URL de la gateway Hermes locale |
| `CODEX_MODEL` | `hermes-agent` | NON | Modèle exposé par la gateway |
| `CODEX_API_KEY` | `none` | NON | Clé API de la gateway (souvent `none` en local) |

## Telegram Bot

| Variable | Défaut | Requis | Description |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | — | OUI (bot) | Token BotFather pour le bot Telegram de Béa |
| `TELEGRAM_CHAT_ID` | — | NON | Chat ID pour les alertes de monitoring |
| `TELEGRAM_ALLOWED_USERS` | — | NON | Liste d'user IDs autorisés (séparés par virgule) |

## Fonctionnalités

| Variable | Défaut | Requis | Description |
|---|---|---|---|
| `BEA_CONTINUOUS_IMPROVEMENT` | `0` | NON | `1` active le daemon d'auto-amélioration (tourne toutes les 30 min) |
| `BEA_IMPROVEMENT_MODE` | `propose` | NON | `propose` = sauvegarde les specs sans modifier le code ; `merge` = applique le patch + tests Docker de régression |
| `BEA_REPO_ROOT` | `.` (CWD) | NON | Chemin absolu vers la racine du repo — nécessaire si le process ne démarre pas depuis le repo (ex. `C:\Users\maxen\DOCUME~1\BA00F6~1`) |
| `BEA_OPERATOR_APPROVE_IMPROVEMENT` | `0` | NON | `1` approuve automatiquement les améliorations R4 (garde cooldown 24h + cap échecs) |
| `BEA_SKIP_IMPROVEMENT_GATE` | `0` | NON | `1` bypasse TOTALEMENT la gate d'amélioration (dangereux, tests seulement) |
| `BEA_AUTO_APPROVE_MEDIUM` | `0` | NON | `1` approuve automatiquement les actions à risque medium |
| `BEA_AUTONOMY_PAUSED` | `0` | NON | `1` met en pause le daemon d'autonomie |
| `BEA_AUTONOMY_DAILY_USD_MAX` | `50` | NON | Budget LLM journalier maximum (USD) |
| `BEA_AUTONOMY_DAILY_TOKENS_MAX` | `5000000` | NON | Budget tokens journalier maximum |
| `BEA_MODE` | `local` | NON | Mode de déploiement (`local`, `docker`, `cloud`) |

## Identité

| Variable | Défaut | Requis | Description |
|---|---|---|---|
| `BEA_NAME` | `BeaMax` | NON | Nom affiché de l'agent |
| `BEA_VERSION` | `1.0.0` | NON | Version affichée |

## Embeddings & Observabilité

| Variable | Défaut | Requis | Description |
|---|---|---|---|
| `EMBEDDING_PROVIDER` | `local` | NON | Provider d'embeddings (`local`, `openai`, `huggingface`) |
| `HUGGINGFACE_API_KEY` | — | NON | Clé HuggingFace (pour les modèles HF) |
| `LANGFUSE_HOST` | `http://langfuse:3000` | NON | URL du serveur Langfuse (traces LLM) |
| `LANGFUSE_PUBLIC_KEY` | — | NON | Clé publique Langfuse |
| `LANGFUSE_SECRET_KEY` | — | NON | Clé secrète Langfuse |

## Intégrations externes

| Variable | Défaut | Requis | Description |
|---|---|---|---|
| `N8N_HOST` | `http://n8n:5678` | NON | URL du serveur n8n (automatisations) |
| `N8N_BASIC_AUTH_USER` | `admin` | NON | Utilisateur n8n |
| `N8N_BASIC_AUTH_PASSWORD` | — | NON | Mot de passe n8n |
| `COMPOSIO_API_KEY` | — | NON | Clé API Composio (outils externes MCP) |
| `GITHUB_MCP_URL` | `http://github-mcp:3000` | NON | URL du serveur MCP GitHub |
| `MCP_SERVER_HOST` | `0.0.0.0` | NON | Adresse d'écoute du serveur MCP interne |
