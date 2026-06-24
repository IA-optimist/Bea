# Béa — Environment Variables

> Complete reference for all environment variables used by Béa.

## Quick start

| Use case | Template | Command |
|----------|----------|---------|
| Local dev | `.env.example.local` | `cp .env.example.local .env` |
| Production | `.env.example.production` | `cp .env.example.production .env` |

**Never** commit `.env` to git.

## Critical variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `BEA_PRODUCTION` | Yes | `false` | Set to `true` only in production. Enables strict guards (rate-limit enforcement, Redis requirement). |
| `BEA_SECRET_KEY` | Yes | — | JWT signing key. Generate: `openssl rand -hex 32` |
| `BEA_API_TOKEN` | Yes | — | API bearer token. Generate: `python3 -c "import secrets; print(secrets.token_urlsafe(40))"` |
| `BEA_ADMIN_PASSWORD` | Yes | — | Admin route password. Generate: `openssl rand -base64 24` |
| `DATABASE_URL` | Yes | — | PostgreSQL connection URL |
| `REDIS_URL` | Yes | — | Redis connection URL (required in production) |

## LLM Providers

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENROUTER_API_KEY` | One provider | — | OpenRouter API key (`sk-or-v1-...`) |
| `OPENROUTER_MODEL_FAST` | No | `openai/gpt-oss-20b:free` | Fast model for simple tasks |
| `OPENROUTER_MODEL_STANDARD` | No | `openai/gpt-oss-20b:free` | Standard model |
| `OPENROUTER_MODEL_STRONG` | No | `openai/gpt-oss-120b:free` | Strong model for complex tasks |
| `OLLAMA_HOST` | No | `http://127.0.0.1:11434` | Ollama server URL (local fallback) |
| `OLLAMA_MODEL_MAIN` | No | `gemma4:12b` | Main Ollama model |
| `OLLAMA_MODEL_FAST` | No | `gemma4:12b` | Fast Ollama model |
| `OPENAI_API_KEY` | No | — | OpenAI API key (alternative provider) |
| `ANTHROPIC_API_KEY` | No | — | Anthropic API key (alternative provider) |

## API & Security

| Variable | Default | Description |
|----------|---------|-------------|
| `BEA_CORS_ORIGINS` | `http://localhost:3000,...` | Comma-separated allowed origins. **Never use `*` in production.** |
| `BEA_RATE_LIMIT_ENABLED` | `true` | Enable/disable rate-limiting. **Must be `true` in production.** |
| `BEA_RATE_LIMIT_PER_MINUTE` | `60` | Requests per IP per minute |
| `BEA_API_URL` | `http://127.0.0.1:8000` | Base URL of the API |

## Policy Session Store

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `POLICY_SESSION_STORE` | No | `memory` | Session backend for PolicyEngine: `memory` (dev/test) or `redis` (beta/prod). **Must be `redis` in production.** |
| `POLICY_SESSION_TTL_SECONDS` | No | `3600` | Session TTL in seconds. Sessions are evicted after this delay. |

**Production rule**: `BEA_PRODUCTION=true` + `POLICY_SESSION_STORE=memory` → **startup blocked**.  
`POLICY_SESSION_STORE=redis` + Redis unreachable → **startup blocked** (fail-closed).  
`InMemorySessionStore` is single-process only — not safe for multi-worker deployments.

## Self-improvement

| Variable | Default | Description |
|----------|---------|-------------|
| `BEA_CONTINUOUS_IMPROVEMENT` | `0` | Enable self-improvement loop. **Leave disabled for beta.** |
| `BEA_SKIP_IMPROVEMENT_GATE` | (unset) | **DANGER**: Bypasses operator approval. Never set in any environment. |
| `BEA_IMPROVEMENT_MODE` | `propose` | Improvement mode (`propose` or `auto`) |

## Memory

| Variable | Default | Description |
|----------|---------|-------------|
| `QDRANT_URL` | `http://127.0.0.1:6333` | Qdrant vector store URL |
| `QDRANT_API_KEY` | — | Qdrant API key (if required) |
| `BEA_FTS_DB` | `workspace/memory_fts.db` | Full-text search SQLite database path |

## Safety rules

1. `BEA_PRODUCTION=true` + `BEA_RATE_LIMIT_ENABLED=false` → **startup blocked**
2. `BEA_PRODUCTION=true` + Redis unreachable → **startup blocked**
3. `BEA_CORS_ORIGINS=*` + `BEA_PRODUCTION=true` → **blocked by CORS middleware**
4. `BEA_SKIP_IMPROVEMENT_GATE` set to any value → **dangerous, never use**
