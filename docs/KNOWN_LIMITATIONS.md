# Béa — Known Limitations

> Current limitations of the Béa Developer Preview. Check this list before
> reporting a bug — it may be a known issue.

---

## Runtime & Routing

| Limitation | Details | Workaround |
|------------|---------|------------|
| Router is advisory only | `runtime_enforced=false` — the router recommends but does not automatically switch providers/models | Manually set `MODEL_STRATEGY` in `.env` |
| No CI enforcement of benchmark | Benchmark results are not gated in CI | Run `python scripts/benchmark_model_roles.py --mock --json` locally |
| `model_used` may be inaccurate | OpenRouter may route to a different model server-side | Check OpenRouter dashboard for actual model used |
| Chat fast-path doesn't track `model_used` | Sessions using the fast-path skip model tracking | Use mission-based interactions for accurate tracking |

## Providers

| Limitation | Details | Workaround |
|------------|---------|------------|
| External providers can fail | OpenRouter may rate-limit, timeout, or return errors | Configure Ollama as fallback |
| Ollama `gemma4:12b` fails on forge-builder | `artifact_invalid` — generated code has syntax errors | Use OpenRouter for code generation |
| Ollama `gemma4:12b` fails on shadow-advisor | `json_invalid` — JSON output is malformed | Use OpenRouter for structured advice |
| Codex direct (OAuth) may be expired | `codex_direct` provider requires valid OAuth token | Use OpenRouter instead |

## Memory

| Limitation | Details | Workaround |
|------------|---------|------------|
| Qdrant requires Docker | Memory features fail without Qdrant running | `docker compose up -d` before starting Béa |
| Large local stores slow down `bea_eval` | Stores with 100k+ items cause timeout | Use a fresh store or fixture for testing |
| Public seed is minimal | Only 8 neutral project facts in `--profile public` | Seed additional public facts if needed |
| `--apply` is disabled | Destructive memory cleanup is not available | Manual cleanup via SQL if absolutely needed |

## API

| Limitation | Details | Workaround |
|------------|---------|------------|
| No rate-limiting | API has no built-in rate limiter | Do not expose to public internet |
| v1 endpoints maintained | `/api/v1` kept for Flutter rollback until APK v3 validated | Use `/api/v2` or `/api/v3` for new integrations |
| No multi-tenant isolation | Multiple users on same instance is not safe | One instance per tester |

## Mobile

| Limitation | Details | Workaround |
|------------|---------|------------|
| APK v3 not validated in CI | Flutter v3 migration complete but build not tested in CI | Test API directly; do not rely on APK |
| v1 stream endpoints critical | `/api/v1/missions/{id}/stream` still needed until Flutter migration done | Do not remove v1 endpoints |

## Self-improvement

| Limitation | Details | Workaround |
|------------|---------|------------|
| Disabled by default | `BEA_CONTINUOUS_IMPROVEMENT=0` | Leave disabled for beta testing |
| Gate bypass is dangerous | `BEA_SKIP_IMPROVEMENT_GATE` skips operator approval | **Never use this flag** |
| No autonomous promotion | Patches require manual REVIEW or REJECT | Review patches manually |

## Security

| Limitation | Details | Workaround |
|------------|---------|------------|
| No production hardening | Not deployed with TLS, WAF, or DDoS protection | Use behind a reverse proxy if needed |
| Unsigned patches possible | Signature validation exists but is not enforced in all paths | Only accept patches from trusted sources |

## What is NOT a bug

- Ollama producing lower quality output than OpenRouter (expected)
- `bea_eval` timeout on a very large local store (use a fresh store)
- v1 endpoints still present (intentional for Flutter rollback)
- Router not auto-switching providers (advisory only by design)
