# Béa — Beta Tester Guide

> For the private beta only. Read [README_PUBLIC_BETA.md](../README_PUBLIC_BETA.md) first.

## What you will do as a tester

1. Run Béa locally (or in your own isolated environment).
2. Configure one LLM provider.
3. Submit a few simple missions.
4. Report what works, what crashes, and what confuses you.
5. **Never submit secrets or personal data.**

## Before you start

- You need Python 3.11+ (3.12 recommended).
- You need Git.
- Optional: Docker for Qdrant.
- You must be comfortable editing a `.env` file.

## Step-by-step local setup

### 1. Clone and checkout the beta branch

```bash
git clone https://github.com/IA-optimist/Bea.git
cd Bea
git checkout beta/private-readiness-kilo-kimi
```

### 2. Create your `.env`

```bash
cp .env.example .env
```

Edit `.env` and fill the **minimum** required values:

```bash
# Pick ONE provider and set its key
OPENROUTER_API_KEY=sk-or-...          # or ANTHROPIC_API_KEY / OPENAI_API_KEY
MODEL_STRATEGY=openrouter             # or anthropic / openai
MODEL_FALLBACK=ollama

# Auth secrets — generate real random values
JARVIS_SECRET_KEY=<openssl rand -hex 32>
JARVIS_ADMIN_PASSWORD=<strong unique password>
JARVIS_API_TOKEN=jv-<openssl rand -hex 32>

# Optional vector memory
QDRANT_HOST=localhost
QDRANT_PORT=6333
```

Keep `SELF_IMPROVE_ENABLED=false` (default).

### 3. Install dependencies

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If you chose Anthropic, also run:

```bash
python -m pip install langchain-anthropic
```

### 4. Optional: start Qdrant

```bash
docker run -d --name qdrant -p 6333:6333 qdrant/qdrant:v1.9.7
```

Without Qdrant, memory-dependent features may fall back to SQLite or return empty results.

### 5. Start Béa

```bash
python main.py
```

Expected last log line:

```
[info] uvicorn running on http://0.0.0.0:8000
```

## Your first mission

### 1. Get a token

```bash
curl -X POST http://localhost:8000/auth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=<your-admin-password>"
```

Save the `access_token`.

### 2. Submit a mission

```bash
curl -X POST http://localhost:8000/api/v3/missions \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "goal": "List three pros and three cons of Python async/await",
    "mode": "auto"
  }'
```

You will get a `mission_id`.

### 3. Poll for status

```bash
curl -H "Authorization: Bearer <token>" \
  http://localhost:8000/api/v3/missions/<mission_id>
```

Statuses you may see: `CREATED`, `RUNNING`, `DONE`, `FAILED`, `ABORTED`.

## What to test during the beta

- Simple Q&A missions.
- A mission that asks Béa to read a public URL (if network tools are enabled).
- Login via the SPA at `http://localhost:8000/`.
- Submitting the same mission twice to check idempotency.
- Turning on Ollama fallback.
- Checking that unauthenticated requests to `/api/v3/missions` return `401`.

## What NOT to test during the beta

- Do **not** connect Béa to production accounts, databases, or APIs.
- Do **not** run `scripts/activate_si_v3.sh` unless explicitly asked by the core team.
- Do **not** enable `BEA_SKIP_IMPROVEMENT_GATE` or `SELF_IMPROVE_ENABLED=true` without operator approval.
- Do **not** submit real passwords, API keys, personal data, or customer data.

## How to report a bug

Use `.github/ISSUE_TEMPLATE/bug_report.yml`. Include:

- Your OS.
- Commit SHA (`git rev-parse HEAD`).
- Launch mode (`python main.py`, Docker, etc.).
- Provider used (OpenRouter / Anthropic / OpenAI / Ollama).
- Endpoint or surface (API / Web / Flutter / Memory / Provider / Mission / Docs).
- Exact reproduction steps.
- Expected vs observed behavior.
- Redacted logs.
- A screenshot if it helps.
- Confirmation that you removed any secret or private data.

## Getting help

First read [docs/TROUBLESHOOTING.md](TROUBLESHOOTING.md).  
If you are stuck, ask in the private beta channel before opening a public issue.

## Daily checklist

Before each testing session:

- [ ] I pulled the latest `beta/private-readiness-kilo-kimi` branch.
- [ ] I checked `python scripts/private_beta_gate.py --json`.
- [ ] My `.env` is correct and git-ignored.
- [ ] I will not paste secrets into the chat or mission inputs.
