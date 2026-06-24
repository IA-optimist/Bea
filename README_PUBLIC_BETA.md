# Béa — Private Beta README

> **Status: private beta / developer preview / experimental.**  
> Béa is experimental. Do not use it in production. It does not run autonomously.

## What Béa is

Béa is an experimental AI orchestration system. It can break down goals into missions, call tools, manage memory, and expose a FastAPI backend with web and Flutter frontends. The core cognitive pipeline (mission lifecycle, kernel contracts, auth middleware) is the most mature part of the repo. Many other surfaces are scaffolding or stubs.

## What Béa is not yet

- **Not production-ready.** Do not expose it to untrusted networks or real end-users.
- **Not fully autonomous.** Self-improvement is disabled by default for the private beta.
- **Not a finished SaaS.** Business handlers (build product, deploy, revenue tracking) are partially wired or static.
- **Not a security audit substitute.** Run it in isolated environments.

## Who this beta is for

5–10 technical testers who:

- can read Python and run a local FastAPI app;
- understand that crashes, misleading outputs, and partial features are expected;
- will follow the safety rules and report issues using the templates.

## Quick start (local)

```bash
# 1. Clone and switch to the beta branch
git clone https://github.com/IA-optimist/Bea.git
cd Bea
git checkout beta/private-readiness-kilo-kimi

# 2. Copy and edit the env file
cp .env.example .env
# Set ONE LLM provider key, JARVIS_SECRET_KEY, JARVIS_ADMIN_PASSWORD, JARVIS_API_TOKEN.
# Keep SELF_IMPROVE_ENABLED=false (default).

# 3. Install dependencies
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# 4. Optional: start Qdrant for memory
# docker run -d --name qdrant -p 6333:6333 qdrant/qdrant:v1.9.7

# 5. Run
python main.py

# 6. Verify health
curl http://localhost:8000/health
```

See [docs/BETA_TESTER_GUIDE.md](docs/BETA_TESTER_GUIDE.md) for the full walkthrough.

## Provider setup

Pick **one** cloud provider or use a local Ollama fallback:

- **OpenRouter** (recommended for variety): set `OPENROUTER_API_KEY=sk-or-...` and `MODEL_STRATEGY=openrouter`.
- **Anthropic**: set `ANTHROPIC_API_KEY=sk-ant-...`, `MODEL_STRATEGY=anthropic`.
- **OpenAI**: set `OPENAI_API_KEY=sk-...`, `MODEL_STRATEGY=openai`.
- **Ollama fallback**: set `MODEL_FALLBACK=ollama` and `OLLAMA_HOST=http://localhost:11434`.

Cloud keys are never logged or stored in memory by default. Always keep them in `.env` (git-ignored).

## Ollama fallback

If you do not want to use a cloud provider:

1. Install Ollama locally.
2. Pull a small model: `ollama pull mistral:7b` or `ollama pull tinyllama`.
3. In `.env`:
   ```
   MODEL_STRATEGY=ollama
   MODEL_FALLBACK=ollama
   OLLAMA_HOST=http://localhost:11434
   OLLAMA_MODEL_MAIN=mistral:7b
   ```
4. Restart Béa.

Local models are slower and may produce lower-quality reasoning.

## Run a simple mission

```bash
# 1. Login (uses the admin password from .env)
TOKEN=$(curl -s -X POST http://localhost:8000/auth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=$JARVIS_ADMIN_PASSWORD" | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 2. Submit a mission
curl -X POST http://localhost:8000/api/v3/missions \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"goal": "Summarize the Python language in one paragraph", "mode": "auto"}'

# 3. Read status
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v3/missions/<mission_id>
```

## Disable self-improvement

Self-improvement is **off by default** for the private beta. To double-check:

```bash
python -c "from config.settings import get_settings; print(get_settings().self_improve_enabled)"
# Expected: False
```

If you deliberately want to enable it, read [docs/PRIVATE_BETA_RUNBOOK.md](docs/PRIVATE_BETA_RUNBOOK.md) first and never enable `BEA_SKIP_IMPROVEMENT_GATE`.

## Shut down quickly

- If running from terminal: `Ctrl+C`.
- If running from Docker Compose: `docker compose down`.
- If something goes wrong: kill the `python main.py` process.

## Logs and redaction

Logs are written to `logs/` and printed to stdout. Secrets in env vars are not logged. Captured exceptions may contain tokens if you pass them in request bodies — **do not send secrets in mission goals or chat messages**.

## Feedback

Use the issue templates:

- Bug report: `.github/ISSUE_TEMPLATE/bug_report.yml`
- Beta feedback: `.github/ISSUE_TEMPLATE/beta_feedback.yml`
- Security issue: `.github/ISSUE_TEMPLATE/security_report.md`

Also read [docs/FEEDBACK_GUIDE.md](docs/FEEDBACK_GUIDE.md).

## Known limitations

See [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md) for the full list. Highlights:

- React frontend and React Native mobile apps are secondary/unsupported.
- HexStrike v2 is ~5% migrated.
- Business handlers (build product, deploy product, track revenue) are scaffolding.
- v1 API routes are deprecated.
- The Windows test suite has known failures.

## Privacy

See [docs/PRIVACY_FOR_TESTERS.md](docs/PRIVACY_FOR_TESTERS.md).  
**Summary**: do not put secrets, passwords, personal data, or customer data into Béa during the beta.

## Runbook

Operators and testers should read [docs/PRIVATE_BETA_RUNBOOK.md](docs/PRIVATE_BETA_RUNBOOK.md) before inviting anyone.

## Checklist before inviting a tester

- [ ] `python scripts/private_beta_gate.py --json` returns `ready_for_private_beta: true`.
- [ ] `ruff check .` passes.
- [ ] `.env` is git-ignored and filled with real random secrets.
- [ ] `SELF_IMPROVE_ENABLED=false` (or unset) in the tester's `.env`.
- [ ] The tester has read this README, [docs/PRIVACY_FOR_TESTERS.md](docs/PRIVACY_FOR_TESTERS.md), and [docs/BETA_TESTER_GUIDE.md](docs/BETA_TESTER_GUIDE.md).
- [ ] A private bug-report channel is ready.

## Glossary

- **Private beta**: a small, controlled test with technical users.
- **Developer preview**: features may change or break without warning.
- **Experimental**: the system can behave unpredictably.
