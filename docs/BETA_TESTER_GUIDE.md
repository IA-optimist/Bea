# Béa — Beta Tester Guide

> **Status: Developer Preview (limited)**
> Not yet stable for production use. APIs and behaviour may change between releases.

This guide is for technical beta testers who want to install Béa locally, run
test missions, and provide useful feedback. No prior Béa experience required.

---

## 1. Prerequisites

| Requirement | Minimum | Recommended |
|-------------|---------|-------------|
| Python | 3.11 | 3.12 |
| Docker Desktop | Running (Postgres, Redis, Qdrant) | Latest |
| LLM API key | OpenRouter free tier (`sk-or-v1-...`) | OpenRouter paid for reliability |
| Ollama | Optional (local fallback) | `gemma4:12b` or similar |
| OS | Linux, macOS, Windows (WSL2) | Linux / WSL2 |
| Git | Any recent version | Latest |

## 2. Installation

```bash
# Clone the repository
git clone https://github.com/IA-optimist/Bea.git
cd Bea

# Create virtual environment
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows:
.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Copy environment template
cp .env.example .env
```

## 3. Configuration (safe defaults)

Edit `.env` and set **only** these values for testing:

```bash
# LLM provider — OpenRouter free tier is sufficient for testing
OPENROUTER_API_KEY=sk-or-v1-your-key-here
MODEL_STRATEGY=openrouter

# Database — use Docker
DATABASE_URL=postgresql://bea:bea@localhost:5432/bea
REDIS_URL=redis://localhost:6379/0

# DO NOT enable these for testing:
# BEA_CONTINUOUS_IMPROVEMENT=0  (leave disabled)
# BEA_SKIP_IMPROVEMENT_GATE     (never use)
```

**Never** commit your `.env` file. It is already in `.gitignore`.

## 4. Start services

```bash
# Start Docker dependencies (Postgres, Redis, Qdrant)
docker compose up -d

# Run database migrations
python -m core.db.migrate

# Seed public memory (safe, neutral project facts only)
python scripts/seed_bea_memory.py --profile public

# Start the API
python scripts/run_api_local.py
```

Verify the API is running:

```bash
curl http://localhost:8000/health
# Expected: {"status": "ok"}
```

## 5. Recommended test scenarios

### Scenario 1: Code generation (forge-builder)

Submit a mission asking Béa to write a simple Python function:

```
Goal: Write a Python function sha256_file(path) that reads a file in 8192-byte
chunks and returns the hex digest.
Expected: A .py file with valid syntax and a test proof.
```

**What to check:**
- Does the generated code compile?
- Is there a test proof?
- Is the artifact saved in `workspace/`?

### Scenario 2: Research analysis (scout-research)

Submit a mission asking Béa to analyze a local document:

```
Goal: Summarize the architecture decisions in docs/ARCHITECTURE.md
Expected: A structured summary with sections (Introduction, Methodology, Conclusion).
```

**What to check:**
- Is the output structured?
- Does it reference real content from the file?
- Is the duration reasonable (< 60s)?

### Scenario 3: Structured advice (shadow-advisor)

Submit a mission asking for JSON-formatted advice:

```
Goal: Return a JSON object with keys "advice" and "confidence" about whether
to use OpenRouter vs Ollama for code generation.
Expected: Valid JSON with the required keys.
```

**What to check:**
- Is the output valid JSON?
- Does it contain both required keys?
- Is the advice reasonable?

### Scenario 4: Memory retrieval

After running scenarios 1-3, check that Béa remembers past missions:

```
Goal: What did you learn from previous missions about code generation?
Expected: Béa references specific past mission results.
```

### Scenario 5: Provider fallback

If you have Ollama installed, temporarily disable your OpenRouter key and
verify Béa falls back to Ollama:

```bash
# Temporarily rename your key in .env
# OPENROUTER_API_KEY=disabled
# Restart the API and submit a mission
```

**What to check:**
- Does Béa gracefully fall back?
- Is the fallback logged?
- Does the mission still complete (possibly with lower quality)?

## 6. What is out of scope for beta testing

- **Production deployment** — Béa is not production-ready. Do not expose the
  API to the public internet without rate-limiting and auth.
- **Self-improvement loop** — `BEA_CONTINUOUS_IMPROVEMENT` must stay disabled.
  Do not test the self-improvement gate unless explicitly asked.
- **Multi-tenant isolation** — not yet validated. Do not test with multiple
  users on the same instance.
- **APK mobile build** — Flutter v3 migration is in progress. The APK may not
  build. Do not report APK build failures unless you are on the mobile testing
  track.
- **Performance benchmarking** — Béa has not been stress-tested. Do not run
  high-concurrency load tests.

## 7. How to stop Béa cleanly

```bash
# Stop the API (Ctrl+C in the terminal running run_api_local.py)

# Stop Docker services
docker compose down

# Optional: clean up workspace artifacts
rm -rf workspace/artifacts/*.py
```

## 8. Where to get help

- **Bugs and issues:** [Open a GitHub issue](https://github.com/IA-optimist/Bea/issues/new/choose)
- **Feedback:** See [docs/FEEDBACK_GUIDE.md](FEEDBACK_GUIDE.md)
- **Privacy:** See [docs/PRIVACY_FOR_TESTERS.md](PRIVACY_FOR_TESTERS.md)
- **Known limitations:** See [docs/KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md)
- **Troubleshooting:** See [docs/TROUBLESHOOTING.md](TROUBLESHOOTING.md)
