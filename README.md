# JARVIS MAX — AI Agent Orchestration System

> Multi-agent autonomous system: planning, secure execution,
> persistent memory, self-improvement — controlled via the Jarvis app or API.

---

## Quick Start — Proven Path (verified 2026-04-01)

```bash
# 1. Install dependencies
pip install -r requirements.txt
pip install langchain-anthropic   # if using Anthropic key

# 2. Configure env
cp .env.example .env
# Edit .env — minimum required:
#   ANTHROPIC_API_KEY=sk-ant-...   (or OPENROUTER_API_KEY / OPENAI_API_KEY)
#   MODEL_FALLBACK=anthropic       (required when using Anthropic without OpenRouter)
#   JARVIS_SECRET_KEY=<openssl rand -hex 32>
#   JARVIS_ADMIN_PASSWORD=<password>

# 3. Start Qdrant
docker run -d -p 6333:6333 qdrant/qdrant:v1.9.7

# 4. Start the API
python main.py

# 5. Verify (must exit 0)
JARVIS_ADMIN_PASSWORD=<password> bash scripts/verify_boot.sh
```

**See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full architecture reference.**
**See [docs/DB_RECONCILIATION_PLAN.md](docs/DB_RECONCILIATION_PLAN.md) for database setup.**

---

## Architecture

```
Jarvis App / API (port 8000)  ← PRIMARY INTERFACE
  └── MetaOrchestrator  ← SINGLE orchestration entry point
        ├── Planner      → steps + objective_context + difficulty
        ├── AgentCrew    → 9 agents (P1 → P2 → P3)
        ├── RiskEngine   → LOW (auto) / MEDIUM / HIGH (API approval)
        ├── Executor     → atomic actions + backup + rollback
        └── Self-Improvement → weakness → candidates → score → execute
              (core/self_improvement/ — MAX=1, COOLDOWN=24h)
```

**Couches du code source :**
```
api/                  → FastAPI + routes (50+ routers, v1/v2/v3)
core/                 → Orchestration + planner + memory + self-improvement (359 py files)
core/self_improvement/→ CANONICAL self-improvement pipeline (weakness→patch→test→score→promote)
kernel/               → Capability registry, policy, memory interfaces, kernel contracts
agents/               → 36 agents + crew parallèle + kernel bridge
security/             → SecurityLayer (6 active rules) + audit trail + policy ruleset
business/             → Business orchestration layer (assisted, not autonomous)
tests/                → 4900+ passing unit tests; 700+ CI-gated; smoke tests require --run-infra-tests
```

> **Maturity note:** This is an **internal beta** platform. The core orchestration,
> mission lifecycle, and LLM execution path are proven. Business and cyber layers
> are LLM-assisted scaffolding, not production automation.
> **Qdrant is required** for the core mission path. Redis, Postgres, n8n, Ollama are optional.

> Voir [ARCHITECTURE.md](ARCHITECTURE.md) pour le schéma complet des couches.
> Voir [RELEASE_READINESS.md](docs/RELEASE_READINESS.md) pour l'état de maturité actuel.

---

## Stack Docker

| Service      | Rôle                        | Port  |
|--------------|-----------------------------|-------|
| jarvis_core  | Orchestrateur Python        | 8000  |
| postgres     | Base de données principale  | —     |
| redis        | Cache / sessions            | —     |
| qdrant       | Mémoire vectorielle         | 6333  |
| ollama       | LLM local                   | 11434 |
| n8n          | Automatisation workflows    | 5678  |
| open_webui   | Interface modèles locaux    | 3001  |

---

## API Endpoints

> **v3 is the canonical API.** v1/v2 routes remain for compatibility.

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v3/missions` | Submit a mission (canonical) |
| GET | `/api/v3/missions/{mission_id}` | Mission status |
| POST | `/api/v3/missions/{mission_id}/approve` | Approve pending action |
| POST | `/api/v3/missions/{mission_id}/reject` | Reject pending action |
| GET | `/api/v3/missions` | List all missions |
| GET | `/api/v2/status` | System status |
| GET | `/api/v2/agents` | Agent registry |
| POST | `/api/v2/self-improve/run` | Trigger self-improvement |
| GET | `/health` | Health check |
| GET | `/kernel/status` | Kernel runtime status |

> Legacy aliases: `/api/v2/missions/submit`, `/api/v1/mission/run`, `/api/mission`

### Approval Flow

For MEDIUM/HIGH risk actions, JarvisMax requests approval via the API:
- `POST /api/v3/missions/{mission_id}/approve` → execute
- `POST /api/v3/missions/{mission_id}/reject` → cancel

> Note: `/api/v2/tasks/{id}/approve` is a **legacy path** (still active, single-step only).
> Canonical: use `/api/v3/missions/{id}/approve` (3-step: MissionSystem + MetaOrchestrator + SQLite persist).

---

## Risk Levels

| Level | Examples | Behavior |
|-------|----------|----------|
| 🟢 LOW | Read, create workspace, analyze | Auto-executed |
| 🟡 MEDIUM | Modify files, scripts | Approval required |
| 🔴 HIGH | Delete, install, network | Approval required |

---

## Les 9 agents

The LLM used per agent is configured by the active provider strategy (see `.env.example`).
The default path uses your configured `ANTHROPIC_API_KEY` or `OPENROUTER_API_KEY`.
ScoutResearch and ForgeBuilder are proven active; LensReviewer has intermittent failures (KL-005).

| Agent            | Rôle                        | Status (2026-04-01) |
|------------------|-----------------------------|---------------------|
| AtlasDirector    | Chef d'orchestre / planning | Active |
| ScoutResearch    | Recherche et synthèse       | ✅ Proven active |
| MapPlanner       | Plans et roadmaps           | Active |
| ForgeBuilder     | Code, scripts, fichiers     | ✅ Proven active |
| LensReviewer     | Contrôle qualité            | ✅ Resolved (KL-005 — priority waves wired, Cycle 11) |
| VaultMemory      | Mémoire long terme          | Active (requires Qdrant) |
| ShadowAdvisor    | Perspectives alternatives   | Active |
| PulseOps         | Préparation d'actions       | Active |
| NightWorker      | Missions longues            | Active |

---

## Workspace

```
workspace/
├── projects/     ← Projets créés par Jarvis
├── reports/      ← Rapports et analyses
├── missions/     ← Résultats Night Worker
│   └── <session_id>/
│       ├── cycle_01.json
│       ├── cycle_02.json
│       └── rapport_final.md
├── patches/      ← Patches auto-amélioration
└── .backups/     ← Backups avant modification
```

---

## Configuration LLM

Model selection is driven by `MODEL_STRATEGY` + `MODEL_FALLBACK`. The model router
(`core/model_intelligence/selector.py`) picks the best available model per task class.
Evidence accumulates in `data/model_performance.json` from real usage.

**Proven configurations:**
- `MODEL_STRATEGY=anthropic` + `ANTHROPIC_API_KEY` → all agents use Claude (Haiku by default)
- `MODEL_STRATEGY=openrouter` + `OPENROUTER_API_KEY` → routes to any of 348 available models
- Ollama (local): supported via `MODEL_STRATEGY=ollama` but not on the proven E2E path

---

## Modules avancés

### n8n Bridge

```python
from tools.n8n.bridge import N8nBridge
bridge = N8nBridge(settings)

# Créer un workflow HTTP
wf = await bridge.create_simple_http_workflow("Mon workflow", "https://api.example.com")

```

### Browser Automation (Playwright)

```python
from tools.browser.scraper import BrowserTool
async with BrowserTool(settings) as browser:
    text    = await browser.get_text("https://example.com")
    results = await browser.search_and_scrape("intelligence artificielle")
    data    = await browser.extract_structured(url, {"title": "h1", "price": ".price"})
```

### System Observer

```python
from observer.watcher import SystemObserver
obs     = SystemObserver(settings)
snap    = await obs.snapshot_workspace()     # État du workspace
changes = await obs.detect_changes(since_minutes=60)  # Fichiers modifiés
analysis = await obs.analyze_logs(n=50)     # Analyse des logs
```

---

## Ajouter un agent personnalisé

```python
from agents.crew import BaseAgent, AgentCrew
from core.state import JarvisSession

class MyAgent(BaseAgent):
    name, role = "my-agent", "research"

    def system_prompt(self) -> str:
        return "Tu es un agent spécialisé en..."

    def user_message(self, session: JarvisSession) -> str:
        return f"Mission : {session.mission_summary}"

# Enregistrer dans le crew
crew = AgentCrew(settings)
crew.add(MyAgent(settings))
```

---

## Variables .env clés

See `.env.example` for the full documented list. Minimum for a working run:

| Variable                    | Description                       | Required |
|-----------------------------|-----------------------------------|----------|
| `ANTHROPIC_API_KEY`         | Anthropic API key (proven path)    | One LLM key required |
| `OPENROUTER_API_KEY`        | OpenRouter key (preferred for prod)| One LLM key required |
| `OPENAI_API_KEY`            | OpenAI API key                    | One LLM key required |
| `MODEL_FALLBACK`            | Fallback provider when primary has no key | Required if using Anthropic without OpenRouter |
| `QDRANT_HOST`               | Qdrant hostname (`localhost` dev)  | ✅ |
| `JARVIS_SECRET_KEY`         | JWT signing secret (32+ chars)     | ✅ |
| `JARVIS_ADMIN_PASSWORD`     | Admin user password                | ✅ |
| `DRY_RUN`                   | `true` = stub LLM responses        | — |

---

## Debugging

```bash
# Logs en temps réel
docker compose logs -f jarvis

# Logs d'un service
docker compose logs -f ollama

# API health
curl http://localhost:8000/health

# Dernières actions
curl http://localhost:8000/logs?n=20

# Snapshot workspace
curl http://localhost:8000/workspace

# Redémarrer uniquement Jarvis (sans toucher aux autres services)
docker compose restart jarvis

# Accéder au shell du conteneur
docker compose exec jarvis bash

# Voir les modèles Ollama
docker compose exec ollama ollama list
```

---

## Roadmap évolutive

Voir [ROADMAP.md](docs/ROADMAP.md) pour la roadmap complète.

Prochaines étapes clés :
- Synchronisation guards FORBIDDEN_SELF_MODIFY ↔ PROTECTED_FILES
- Dashboard web (monitoring objectifs + workspace)

---

## Docs

| Document | Description |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Schéma complet des couches, pipeline, SI loop |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Phases complétées et prochaines étapes |
| [CHANGELOG.md](CHANGELOG.md) | Historique des changements |
| [docs/RUNBOOK.md](docs/RUNBOOK.md) | Setup, deployment, operations |
| [docs/RUNTIME_TRUTH.md](docs/RUNTIME_TRUTH.md) | Proven capabilities (updated each cycle) |
| [docs/RELEASE_READINESS.md](docs/RELEASE_READINESS.md) | État de maturité actuel |
