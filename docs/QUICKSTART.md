# BeaMax — Quick Start

> Get BeaMax running locally in 5 minutes.

---

## Prerequisites

- **Python 3.11+** (3.12 recommended)
- **Docker** (for Qdrant — required for memory)
- **At least one LLM API key**: Anthropic, OpenAI, or OpenRouter

---

## 1. Clone and configure

```bash
git clone https://github.com/UniTy01/Beamax-master.git
cd Beamax-master
cp .env.example .env
```

Edit `.env` and set the **minimum required** values:

```bash
# Pick ONE LLM provider
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-haiku-4-5-20251001
MODEL_STRATEGY=anthropic
MODEL_FALLBACK=anthropic

# Or OpenAI:
# OPENAI_API_KEY=sk-...
# MODEL_STRATEGY=openai

# Or OpenRouter:
# OPENROUTER_API_KEY=sk-or-...
# MODEL_STRATEGY=openrouter

# Auth (REQUIRED in production)
BEA_SECRET_KEY=$(openssl rand -hex 32)
BEA_ADMIN_PASSWORD=admin
BEA_API_TOKEN=$(openssl rand -hex 32)

# Vector store
QDRANT_HOST=localhost
QDRANT_PORT=6333
```

---

## 2. Start Qdrant

```bash
docker run -d --name qdrant -p 6333:6333 qdrant/qdrant:v1.9.7
```

Verify:
```bash
curl http://localhost:6333/health
```

---

## 3. Install Python dependencies

```bash
# Core dependencies
pip install -r requirements.txt

# LLM provider (pick one matching your .env)
pip install langchain-anthropic    # for Anthropic
# pip install langchain-openai     # for OpenAI / OpenRouter
```

---

## 4. Run

```bash
python main.py
```

Expected output:
```
[info] kernel_booted version=1.0.0 capabilities=19 uptime_s=0.05
[info] kernel_policy_registered source=core.policy_engine
[info] kernel_planner_registered source=core.planner
[info] meta_orchestrator_registered_with_kernel
[info] core_classifier_registered_with_kernel
[info] kernel_lesson_storage_registered
[info] kernel_facade_memory_registered
[info] uvicorn running on http://0.0.0.0:8000
```

---

## 5. Verify

```bash
# Health check (no auth needed)
curl http://localhost:8000/health

# Readiness probe (Docker healthcheck endpoint)
curl http://localhost:8000/api/v3/system/readiness
```

Expected response:
```json
{
  "ok": true,
  "ready": true,
  "status": "ready",
  "probes": {
    "llm_key": true,
    "qdrant": true,
    "orchestrator": true
  }
}
```

---

## 6. First mission

### Login to get a JWT

```bash
curl -X POST http://localhost:8000/auth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=admin"
```

Save the `access_token` from the response.

### Submit a mission

```bash
TOKEN="<paste-jwt-here>"

curl -X POST http://localhost:8000/api/v3/missions \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "goal": "Summarize the Python language in one paragraph",
    "mode": "auto"
  }'
```

Response:
```json
{
  "mission_id": "msn_abc123",
  "status": "CREATED",
  "created_at": "2026-04-08T14:30:00Z"
}
```

### Check mission status

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v3/missions/msn_abc123
```

---

## 7. Use the web SPA

Open in your browser:
```
http://localhost:8000/
```

(Redirects to `/app.html` — the canonical French SPA.)

Login with:
- Username: `admin`
- Password: (whatever you set in `BEA_ADMIN_PASSWORD`)

---

## Docker stack (one command)

For a full stack with Postgres, Redis, Qdrant, Caddy:

```bash
docker-compose up -d
```

Services:
- `beamax-api` (port 8000)
- `postgres` (with pgvector)
- `redis` (rate limiting + cache)
- `qdrant` (port 6333, vector memory)
- `caddy` (TLS reverse proxy)
- `ollama` (optional, GPU)

Stop:
```bash
docker-compose down
```

Logs:
```bash
docker-compose logs -f beamax-api
```

---

## Production checklist

Before deploying to production, set `BEA_PRODUCTION=true` and ensure:

- [ ] `BEA_SECRET_KEY` is a real random value (not `change-me-in-production`)
- [ ] `BEA_ADMIN_PASSWORD` is set
- [ ] `BEA_API_TOKEN` is set
- [ ] At least one LLM provider key is configured
- [ ] `QDRANT_API_KEY` is set (for production Qdrant)
- [ ] `POSTGRES_PASSWORD` is set (if using Postgres)
- [ ] `REDIS_PASSWORD` is set (if using Redis for rate limiting)
- [ ] `CORS_ORIGINS` is restricted to known frontend origins
- [ ] HTTPS is enabled (Caddy / nginx in front)
- [ ] `ENABLE_API_DOCS=0` (disables `/docs`, `/redoc`)
- [ ] `SELF_IMPROVE_ENABLED=false` (forced off in production by default)

`enforce_production_secrets()` will hard-fail at startup if secrets are missing.

---

## Troubleshooting

### "No LLM key configured"
Set at least one of `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY` in `.env`. Or set `DRY_RUN=true` for testing without an LLM.

### "Qdrant connection refused"
Make sure Qdrant is running on the host/port in `.env`:
```bash
docker ps | grep qdrant
curl http://localhost:6333/health
```

### "Module not found: structlog" / "langchain_anthropic"
```bash
pip install structlog langchain-anthropic
```
Some dependencies are not in `requirements.txt` — see [STATUS.md](STATUS.md) for known dependency issues.

### "Module not found: psutil" (when importing hexstrike_v2)
```bash
pip install psutil
```
HexStrike v2 is a refactor in progress and not in default `requirements.txt`.

### Tests fail
Run only the gate tests first:
```bash
python -m pytest tests/test_terminal_state_truth.py \
                 tests/test_canonical_mission_persistence.py \
                 tests/test_kernel.py \
                 tests/test_cognitive_upgrade.py \
                 -q
```
Should be **802/802 pass**. Full suite has ~170 known stale failures (see [CODE_REVIEW.md](CODE_REVIEW.md)).

### Mission stays in CREATED forever
Check logs for `kernel_booted` and `meta_orchestrator_registered_with_kernel`. If those are missing, the kernel/orchestrator failed to register.

---

## Next steps

- Read [ARCHITECTURE.md](ARCHITECTURE.md) to understand the mission lifecycle
- Read [API_REFERENCE.md](API_REFERENCE.md) for all endpoints
- Read [STATUS.md](STATUS.md) to understand what is PROVEN vs SCAFFOLDING
- Read [CODE_REVIEW.md](CODE_REVIEW.md) for the latest audit findings
