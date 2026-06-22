# Béa — Troubleshooting

> Common issues and fixes for the Béa Developer Preview.

---

## API won't start

### Error: `Address already in use: 0.0.0.0:8000`

Another process is using port 8000.

```bash
# Find and kill the process
# Linux/macOS:
lsof -i :8000
kill -9 <PID>

# Windows:
netstat -ano | findstr :8000
taskkill /PID <PID> /F
```

### Error: `ModuleNotFoundError: No module named 'core'`

You are not in the project root or the virtual environment is not activated.

```bash
cd /path/to/Bea
source .venv/bin/activate  # Linux/macOS
.venv\Scripts\Activate.ps1  # Windows
```

### Error: `DATABASE_URL not set`

You haven't copied `.env.example` to `.env` or the file is empty.

```bash
cp .env.example .env
# Edit .env with your database URL
```

---

## Docker / Qdrant issues

### Error: `ConnectionRefusedError: Qdrant not reachable`

Qdrant is not running.

```bash
docker compose up -d
docker compose ps  # Verify qdrant is "running"
```

### Error: `psycopg2.OperationalError: could not connect to server`

Postgres is not running or credentials are wrong.

```bash
docker compose up -d postgres
docker compose logs postgres  # Check for errors
```

---

## Provider errors

### Error: `openrouter.AuthenticationError: Invalid API key`

Your OpenRouter API key is invalid or expired.

1. Check your key at https://openrouter.ai/keys
2. Update `.env`: `OPENROUTER_API_KEY=sk-or-v1-your-new-key`
3. Restart the API

### Error: `openrouter.RateLimitError: 429 Too Many Requests`

You've hit the OpenRouter rate limit (common on free tier).

- Wait 60 seconds and retry
- Or configure Ollama as a fallback in `.env`

### Error: `ollama.ClientError: model not found`

The configured Ollama model is not installed.

```bash
ollama pull gemma4:12b
# Or whatever model you specified in .env
```

---

## Mission failures

### Mission status: `FAILED` with `artifact_invalid`

The generated code has a syntax error. This is common with weaker models
(e.g., Ollama `gemma4:12b`).

- Switch to OpenRouter for forge-builder missions
- Check the artifact in `workspace/` to see the actual error

### Mission status: `FAILED` with `json_invalid`

The provider returned non-JSON output for a shadow-advisor mission.

- Switch to OpenRouter (Ollama `gemma4:12b` struggles with JSON)
- Check if the model supports structured output

### Mission status: `TIMEOUT`

The provider took too long to respond.

- Check your internet connection
- Try a different model (smaller models are faster)
- Increase `MISSION_TIMEOUT` in `.env` (default: 300s)

---

## Memory issues

### Béa doesn't remember past missions

Possible causes:
1. Qdrant is not running → `docker compose up -d`
2. Memory was not seeded → `python scripts/seed_bea_memory.py --profile public`
3. You're using a fresh database → run some missions first

### `bea_eval` times out

The local memory store is too large (100k+ items).

```bash
# Use a fresh store for testing
rm workspace/operational_memory.db
python scripts/seed_bea_memory.py --profile public
python scripts/bea_eval.py --json
```

---

## Still stuck?

1. Check [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md)
2. Search [existing issues](https://github.com/IA-optimist/Bea/issues)
3. Open a new issue using the [bug report template](https://github.com/IA-optimist/Bea/issues/new/choose)
4. See [FEEDBACK_GUIDE.md](FEEDBACK_GUIDE.md) for what to include
