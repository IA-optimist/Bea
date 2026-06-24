# Béa — Troubleshooting (Private Beta)

> Quick fixes for common problems during the private beta.

## "No LLM key configured"

**Cause**: No cloud LLM key is set and `DRY_RUN` is not enabled.

**Fix**: Set one of `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `OPENROUTER_API_KEY` in `.env`, or set `DRY_RUN=true` for offline testing.

## "Authentication system not configured" (503)

**Cause**: `JARVIS_REQUIRE_AUTH=true` (default) but neither `JARVIS_API_TOKEN` nor `JARVIS_SECRET_KEY` is set.

**Fix**: Add both to `.env`:

```bash
JARVIS_SECRET_KEY=<openssl rand -hex 32>
JARVIS_API_TOKEN=jv-<openssl rand -hex 32>
```

## Login returns 401 even with correct password

**Cause**: `JARVIS_ADMIN_PASSWORD` is empty and `JARVIS_SECRET_KEY` is wrong, or the token is expired.

**Fix**: Restart Béa after editing `.env`. Tokens are signed with `JARVIS_SECRET_KEY`; changing it invalidates existing tokens.

## "Qdrant connection refused"

**Cause**: Qdrant is not running or `QDRANT_HOST`/`QDRANT_PORT` are wrong.

**Fix**:

```bash
docker run -d --name qdrant -p 6333:6333 qdrant/qdrant:v1.9.7
curl http://localhost:6333/health
```

Then set `QDRANT_HOST=localhost` in `.env`.

## Self-improvement warning at startup

**Message**: `SELF_IMPROVE_ENABLED overridden to false in JARVIS_PRODUCTION mode`.

**Meaning**: This is expected and safe. Self-improvement is disabled by default in production and for the private beta.

## Mission stays in `CREATED` forever

**Cause**: Kernel or orchestrator failed to boot.

**Fix**: Look for these lines in the logs:

- `[info] kernel_booted`
- `[info] meta_orchestrator_registered_with_kernel`

If they are missing, restart and check for import errors.

## Windows-specific failures

If you run the full test suite on Windows, expect failures related to:

- `grep` not found in `test_beta_architecture.py` and `test_devin_bugs.py`.
- `UnicodeDecodeError` from files opened with the default encoding.
- `PermissionError` from unclosed temporary files.
- Path separators (`api\access_enforcement.py` vs `api/access_enforcement.py`).

These are known. CI runs on Linux; use `bash scripts/ci/local_ci.sh` on WSL when possible.

## How to get clean logs

1. Stop Béa.
2. Delete or archive `logs/`.
3. Start Béa with `PYTHONUNBUFFERED=1` and pipe to a file.
4. Reproduce the issue.
5. Copy the relevant log lines, replacing any secret with `REDACTED`.

## Emergency stop

- Terminal: `Ctrl+C`.
- Docker Compose: `docker compose down`.
- Process kill (`kill -9` on Linux / Task Manager on Windows) if frozen.

## Still stuck?

Open a bug report with:

- `git rev-parse HEAD`
- Your OS
- The exact command/output sequence
- Redacted logs
