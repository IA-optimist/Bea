# Béa — Multi-Agent AI OS

**Béa** is a self-improving AI operating system that autonomously builds and operates SaaS businesses.
She runs 24/7 on a Windows machine, thinks with Claude Codex (gpt-5.5), executes missions via a
parallel agent crew, and iteratively improves her own code through an improvement daemon.

> Live businesses built and operated by Béa: **[AutoContentFlow](https://autocontentflow-app-production.up.railway.app)** (SEO article generation) · **CVOptimIA** (CV/ATS optimization for the French market)

---

## What Béa can do

| Capability | Description |
|---|---|
| **Business missions** | Scan opportunities, build products, deploy to Railway, track revenue |
| **Research & analysis** | Parallel agent crew (scout-research / shadow-advisor / lens-reviewer) |
| **Code generation** | forge-builder agent writes and deploys production code |
| **Self-improvement** | Daemon detects weaknesses in execution metrics, proposes patches |
| **Memory** | Qdrant vector store + PostgreSQL + SQLite mission history |
| **Telegram bot** | Conversational interface + vision (photos, YouTube analysis) |
| **Mobile app** | Flutter Android APK (auto-login via Tailscale) |
| **590+ REST API routes** | Full FastAPI surface with JWT auth, rate limiting, WebSocket streams |

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│  Telegram bot · Flutter app · cockpit.html       │  ← Interfaces
├─────────────────────────────────────────────────┤
│  api/          FastAPI 590+ routes               │  ← API surface
├─────────────────────────────────────────────────┤
│  core/         MetaOrchestrator · missions       │
│                business engine · improvement     │  ← Orchestration
│                detector/daemon · LLM factory     │
├─────────────────────────────────────────────────┤
│  agents/       scout-research · shadow-advisor   │
│                lens-reviewer · forge-builder     │  ← Execution crew
│                bea-team                          │
├─────────────────────────────────────────────────┤
│  kernel/       evaluation · planning · learning  │
│                security gate · improvement gate  │  ← Pure policy layer
│                (zero imports from core/)         │
└─────────────────────────────────────────────────┘
```

**Kernel rule**: `kernel/` never imports from `core/`, `api/`, or `agents/`.
Enrichments flow in via inverted registration slots at boot.

### LLM routing

| Role | Model | Provider |
|---|---|---|
| Béa's reasoning (advisor, director) | Codex gpt-5.5 | ChatGPT Codex direct |
| Agent tasks (research, code) | gpt-oss-20b:free | OpenRouter |
| Fallback | gpt-oss-120b:free | OpenRouter |

---

## Running locally (Windows)

Béa runs natively on Windows — no WSL or Docker required for core operation.

### Prerequisites

- Python 3.12
- PostgreSQL 16+ with a `bea` user and `beamax` database
- Redis 7+
- Qdrant (Docker container on port 6333)
- A `.env` file at repo root (see [`docs/ENV_VARS.md`](docs/ENV_VARS.md))

### Quick start

```batch
git clone git@github.com:IA-optimist/Bea.git
cd Bea
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
REM Fill in BEA_API_TOKEN, BEA_ADMIN_PASSWORD, OPENROUTER_API_KEY, etc.
python scripts\run_api_local.py
```

The API binds to `127.0.0.1:8000` by default.
Set `BEA_API_BIND=0.0.0.0` for network access (Tailscale / LAN).

### Health check

```bash
curl -H "Authorization: Bearer <BEA_API_TOKEN>" http://127.0.0.1:8000/health
# → {"status":"ok","service":"beamax"}
```

---

## Key environment variables

| Variable | Purpose |
|---|---|
| `BEA_API_TOKEN` | Bearer token for all API calls |
| `BEA_ADMIN_PASSWORD` | Web cockpit + admin login |
| `OPENROUTER_API_KEY` | LLM calls via OpenRouter |
| `BEA_CONTINUOUS_IMPROVEMENT=1` | Enable auto-improvement daemon |
| `BEA_IMPROVEMENT_MODE` | `propose` (saves specs only) · `merge` (patches code + runs tests) |
| `BEA_AUTO_APPROVE_MEDIUM=1` | Auto-approve MEDIUM-risk actions |
| `TELEGRAM_BOT_TOKEN` | Béa's Telegram interface |
| `DATABASE_URL` | PostgreSQL connection string |
| `QDRANT_URL` | Qdrant vector store URL |

Full reference: [`docs/ENV_VARS.md`](docs/ENV_VARS.md)

---

## Auto-improvement daemon

When `BEA_CONTINUOUS_IMPROVEMENT=1`, a background daemon runs every 30 minutes:

1. **Detect** — reads `metrics_store` (in-memory mission/tool counters) and
   `workspace/tool_performance.jsonl` (persistent latency/failure rates)
2. **Rank** — scores weaknesses by expected value (impact × frequency × criticality)
3. **Propose** — in `propose` mode, writes a spec JSON to
   `workspace/self_improvement/proposals/`; in `merge` mode, applies the patch
   and runs Docker regression tests before promoting
4. **Gate** — kernel security gate blocks CRITICAL files, enforces 24h cooldown,
   caps consecutive failures at 3

---

## Businesses operated by Béa

### AutoContentFlow

SEO article generation SaaS — deployed on Railway, Stripe billing, async pipeline.

- URL: `https://autocontentflow-app-production.up.railway.app`
- Stack: Express (CommonJS) + PostgreSQL + Stripe + OpenRouter
- Status: live, Stripe test mode (→ live migration pending)

### CVOptimIA

CV / ATS optimization for the French job market — deployed on Railway, Stripe live.

- Stack: Express + PostgreSQL + Stripe + OpenRouter
- Status: live, Stripe live billing active

---

## Project layout

```
api/            FastAPI routes (590+ endpoints, 61 routers)
agents/         Parallel execution crew
business/       Autonomous SaaS engine (builder, finance, legal, playbooks)
core/           MetaOrchestrator, mission system, LLM factory, improvement daemon
executor/       Task queue, action runner, capability dispatch
kernel/         Pure policy layer (evaluation, planning, learning, security)
memory/         Vector + episodic + semantic memory adapters
scripts/        Launchers, CI helpers, Telegram bot runner
tests/          Unit + integration (400+ passing)
workspace/      Runtime state (missions, proposals, tool_performance.jsonl)
```

---

## CI

```bash
ruff check .                              # Lint (blocking)
pytest tests/ -n auto --dist=loadfile     # Tests
bash scripts/ci/check_lock_drift.sh       # Lock drift
```

GitHub Actions: `ci.yml` · `kernel_ci.yml` · `pre-commit.yml` · `flutter_apk.yml`

---

## Documentation

| Doc | Purpose |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Layered design + module map |
| [`docs/ENV_VARS.md`](docs/ENV_VARS.md) | All environment variables |
| [`docs/STATUS.md`](docs/STATUS.md) | Per-component maturity ratings |
| [`docs/AUTONOMY.md`](docs/AUTONOMY.md) | Auto-improvement operator guide |
| [`docs/API_REFERENCE.md`](docs/API_REFERENCE.md) | REST API endpoints |
| [`docs/DEPLOYMENT_GUIDE.md`](docs/DEPLOYMENT_GUIDE.md) | Production deployment |
| [`CHANGELOG.md`](CHANGELOG.md) | Release history |

---

## License

Private repository — all rights reserved. © 2026 IA-optimist.
