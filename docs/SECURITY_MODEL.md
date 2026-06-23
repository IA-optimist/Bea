# Bea Security Model

## Authentication and Authorization

- All API endpoints protected by bearer token (`BEA_API_TOKEN` env var).
- Admin routes require `JARVIS_ADMIN_PASSWORD` / `BEA_ADMIN_PASSWORD`.
- Rate limiting: `BEA_RATE_LIMIT_PER_MINUTE` (default 60), per-IP via `slowapi`.
- CORS: `BEA_CORS_ORIGINS` controls allowed origins; wildcard requires explicit opt-in.

## Sandbox and Executor

- Code execution uses Docker sandbox (`DockerSandbox`) by default: isolated container, no host FS.
- Metacharacter injection protection in shell commands.
- Agent output validated before promotion (artifact gates).

## Logs and Observability

### What is logged

Structured log fields emitted per mission:
`mission_id`, `mission_type`, `status`, `provider_used`, `model_used`, `agent_used`,
`duration_ms`, `error_category`, `artifact_status`, `validation_status`, `rate_limited`,
`fallback_used`, `timestamp`.

### What is never logged

- **Prompts and LLM responses**: never stored in logs or learning_runs.json by default.
- **API keys**: redacted via `core/observability/redactor.py`.
- **Bearer tokens**: redacted (pattern `Bearer <16+ chars>`).
- **Bea tokens** (`bea-<16+ chars>`): redacted.
- **Email addresses**: redacted.
- **Long opaque strings** (40+ alphanumeric chars): redacted as potential secrets.

### Redactor

`core/observability/redactor.py` provides `redact(str)` and `redact_dict(dict)`:

- `redact_dict` preserves observability metadata keys (`mission_id`, `provider_used`, etc.)
- `redact_dict` always redacts keys containing: `api_key`, `token`, `password`, `secret`,
  `bearer`, `authorization`, `prompt`, `response`, `content`.
- Callable without importing executor (no circular imports).

### Mission status report

`python scripts/mission_status_report.py --json` produces a privacy-safe JSON summary
of `workspace/learning_runs.json`. Prompts and responses are never included.

## Self-Improvement Gates

See `docs/security/self_improvement_policy.md` for the gate kernel policy.
- `BEA_CONTINUOUS_IMPROVEMENT=1` enables the improvement daemon.
- `BEA_OPERATOR_APPROVE_IMPROVEMENT=1` lifts R4 gate (keeps cooldown + failure cap).
- Zones marked CRITICAL block automatic patching.

## Secrets Management

- Secrets in `.env` (gitignored). Never committed.
- `BEA_API_TOKEN` is the main bearer token for API access.
- LLM provider keys: `OPENROUTER_API_KEY`, `MISTRAL_API_KEY`, `CODESTRAL_API_KEY`.
- Refresh tokens for Codex provider stored in `AppData/Local/bea/codex_auth.json`.

See also: `docs/security/` for detailed audits.
