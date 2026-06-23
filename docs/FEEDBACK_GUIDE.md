# Béa — Feedback Guide

> How to write a useful bug report or feedback for the Béa Developer Preview.

Good feedback helps us fix issues fast. Bad feedback wastes everyone's time.
This guide shows you exactly what to include and what to exclude.

---

## 1. Before you report

1. **Check [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md)** — the issue may be
   already documented.
2. **Reproduce the issue** — try to trigger it at least twice.
3. **Note your environment** — OS, Python version, commit hash, provider.
4. **Redact secrets** — see [PRIVACY_FOR_TESTERS.md](PRIVACY_FOR_TESTERS.md).

## 2. What to include in every report

| Field | Why | Example |
|-------|-----|---------|
| **OS** | Reproduction environment | `Ubuntu 22.04 / WSL2` |
| **Python version** | Compatibility | `Python 3.11.9` |
| **Commit hash** | Exact code version | `git rev-parse --short HEAD` → `a1b2c3d` |
| **Command** | What you ran | `python scripts/run_api_local.py` |
| **Mission ID** | If applicable | `mission_id: 6ae60964-bae` |
| **Provider/model** | If visible in logs | `openrouter / gpt-oss-120b:free` |
| **Expected result** | What should have happened | `Valid Python file with test proof` |
| **Actual result** | What actually happened | `SyntaxError in generated file` |
| **Logs (redacted)** | Console output with secrets removed | See below |
| **Impact** | How severe | `Blocks all forge-builder missions` |

## 3. How to redact logs

Before pasting logs, remove or replace:

- API keys: `sk-or-v1-...` → `sk-or-v1-[REDACTED]`
- Bearer tokens: `Bearer eyJ...` → `Bearer [REDACTED]`
- Email addresses: `user@example.com` → `[EMAIL REDACTED]`
- Passwords: any value in `.env` → `[REDACTED]`
- Personal names in prompts: replace with `[USER]`

**Example redacted log:**

```
2026-06-23 01:23:45 INFO  [api] Provider: openrouter, model: gpt-oss-120b:free
2026-06-23 01:23:46 ERROR [forge-builder] SyntaxError in generated artifact
2026-06-23 01:23:46 DEBUG [forge-builder] artifact_path: workspace/sha256_file.py
2026-06-23 01:23:46 INFO  [mission] mission_id=6ae60964-bae status=FAILED
```

## 4. What NEVER to include

| Never share | Why |
|-------------|-----|
| API keys (`sk-...`, `sk-or-...`, `sk-ant-...`) | Can be used to incur charges |
| Bearer tokens / JWT | Can be used to impersonate you |
| `.env` file contents | Contains all your secrets |
| Real customer data | Privacy / GDPR violation |
| Personal phone numbers | Privacy violation |
| Personal addresses | Privacy violation |
| Private prompts with real names | Doxxing risk |

If you accidentally include a secret, **edit your issue immediately** and
rotate the key. See [PRIVACY_FOR_TESTERS.md](PRIVACY_FOR_TESTERS.md).

## 5. Choosing the right category

When you open an issue, pick the category that best matches the problem:

| Category | Symptoms |
|----------|----------|
| **API** | HTTP 500/404/403, endpoint not responding, auth failure |
| **Flutter** | App crash, UI bug, mobile-only issue |
| **Memory** | Béa forgets past missions, Qdrant connection error, seed issues |
| **Provider** | LLM call fails, timeout, model not found, rate limit |
| **Mission artifact** | Generated code has syntax error, JSON invalid, no test proof |
| **Docs** | Documentation is wrong, missing, or outdated |
| **Unknown** | You're not sure — we'll triage |

## 6. How to classify: API vs Provider vs Mission

Use this decision tree:

```
Did the HTTP request fail?
├── YES → Is it a 401/403? → API (auth)
├── YES → Is it a 500? → Check logs
│   ├── "openrouter" or "ollama" in error → Provider
│   ├── "qdrant" or "memory" in error → Memory
│   └── Other → API
└── NO → Did the mission produce a bad artifact?
    ├── YES → Mission artifact
    └── NO → Did Béa forget something? → Memory
```

## 7. Severity levels

| Severity | Meaning | Response time |
|----------|---------|---------------|
| **Critical** | Data loss, security breach, crashes on startup | Same day |
| **High** | Core feature broken (forge-builder, scout-research, shadow-advisor) | 1-2 days |
| **Medium** | Feature partially broken, workaround exists | 1 week |
| **Low** | Cosmetic, documentation, minor annoyance | Best effort |

**Do not** mark cosmetic issues as Critical.
