# Model Routing in Béa

Béa does not call a single large model for every task. The `ModelRouter` picks a **capability class** and leaves the actual provider resolution to the existing LLM factory.

## Capability classes

| Class | Typical task | Why |
|---|---|---|
| `SMALL_FAST` | Summary, classification, memory recall, simple search | Cheap, low latency, good enough for narrow cognitive tasks. |
| `MEDIUM_TOOL_USE` | Patch simple, edit file, call a tool, apply a diff | Balance of reasoning and instruction following for bounded edits. |
| `STRONG_REASONING` | Complex bug, refactor, multi-step reasoning | Needs deeper reasoning and context understanding. |
| `STRONG_CODE_REVIEW` | Security, self-improvement critical paths, protected files | Needs high scrutiny; usually requires human review downstream. |
| `LOCAL_FALLBACK` | Offline mode, strict cost budget, no cloud access | Uses smaller local models, accepts lower capability. |

## Default rules

```python
from core.evaluation.model_router import ModelRouter

router = ModelRouter()
decision = router.choose("summary of failed missions")
print(decision.model_class)   # SMALL_FAST

decision = router.choose("simple patch for typo")
print(decision.model_class)   # MEDIUM_TOOL_USE

decision = router.choose("debug race condition")
print(decision.model_class)   # STRONG_REASONING

decision = router.choose(
    "refactor auth",
    protected_files=["core/auth.py"],
)
print(decision.model_class)   # STRONG_CODE_REVIEW

decision = router.choose("complex bug", budget_cloud=False)
print(decision.model_class)   # LOCAL_FALLBACK
```

## Memory-aware routing

`ModelRouter` reads past `model_result` memories for the same `task_type`:

- If a class succeeds often (≥60% over ≥2 samples), it is favored over the default rule.
- If a class fails consistently (<34% over ≥3 samples), it is deprioritized.
- The evidence is returned in `RouterDecision.memory_evidence` so agents can explain the choice.

## Protected files

Any `protected_files` argument or task type containing `security`, `self-improvement`, `critical`, or `review` forces `STRONG_CODE_REVIEW`, unless `budget_cloud=False` forces `LOCAL_FALLBACK`.

## Why not one big model for everything?

- **Cost**: large models are 10–100× more expensive.
- **Latency**: simple tasks do not need long reasoning chains.
- **Safety**: critical paths must be routed explicitly, not left to a generic prompt.
- **Observability**: class-level routing is easy to log, evaluate, and improve.

## Real Limited Benchmark

`scripts/benchmark_model_roles.py` runs a deterministic SHA256 fixture against a
specific role and one or more providers.  It calls the LLM directly — bypassing
the meta-orchestrator and crew — to get a clean provider/model signal.

```bash
# Mock mode (no real LLM calls, always green):
python scripts/benchmark_model_roles.py --mock --json

# Real mode — forge-builder against OpenRouter and Ollama:
python scripts/benchmark_model_roles.py \
    --role forge-builder --real \
    --providers openrouter,ollama --json \
    --output workspace/model_role_benchmark_forge_builder.json
```

Each provider result includes: `artifact_ok`, `syntax_valid`, `test_proof`,
`score` (0.0–1.0), `passed` (score ≥ 0.7 and success), `duration_s`,
`error_category`, and `skipped` (with `skip_reason` when unavailable).

**Known results (2026-06-22):**
- `openai/gpt-oss-120b:free` via OpenRouter: score 1.0 — PASS (~14 s)
- `gemma4:12b` via Ollama: score 0.67 — near-pass; artifact + syntax OK,
  no `def test_` in output (model fills the SHA256 file but omits test file)

**Routing recommendation:** `forge-builder` should prefer OpenRouter
(`gpt-oss-120b:free`) for code missions requiring test evidence.  Use Ollama
as a latency fallback for simple artifact generation (no test requirement).

## Controlled Multi-Role Benchmark

`scripts/benchmark_model_roles.py --roles` extends the benchmark to three roles:
`forge-builder`, `scout-research`, and `shadow-advisor`.  Each role has its own
prompt and scoring criteria.  **This benchmark does not update the router
automatically.**  Results are informational only — no routing policy is applied.

```bash
# Multi-role real benchmark:
python scripts/benchmark_model_roles.py --real \
    --roles forge-builder,scout-research,shadow-advisor \
    --providers openrouter,ollama --json \
    --output workspace/model_role_benchmark_multi_role.json
```

### Scoring criteria per role

| Role | Criteria (each 1/3) | passed threshold |
|------|---------------------|-----------------|
| `forge-builder` | artifact_ok · syntax_valid · test_proof | score ≥ 0.7 |
| `scout-research` | no_timeout · structured_output · useful_answer | score ≥ 0.7 |
| `shadow-advisor` | json_valid · schema_valid · no_markdown | score ≥ 0.7 |

### success vs passed vs skipped

- **skipped** — provider was unavailable or unknown; not a quality signal.
  Never used to infer that the model is bad.
- **success** — a response was obtained (no crash, no timeout for scout-research).
- **passed** — response met the quality bar (score ≥ 0.7).

A provider being skipped does not lower its score in `best_by_role` — skipped
entries are excluded from the summary entirely.

### Known results (2026-06-22)

| Role | Provider | Model | Score | Passed |
|------|----------|-------|-------|--------|
| forge-builder | openrouter | gpt-oss-120b:free | 1.0 | ✅ |
| forge-builder | ollama | gemma4:12b | 0.0 | ❌ (artifact_invalid — no section markers) |
| scout-research | openrouter | gpt-oss-120b:free | 1.0 | ✅ |
| scout-research | ollama | gemma4:12b | 1.0 | ✅ |
| shadow-advisor | openrouter | gpt-oss-120b:free | 1.0 | ✅ |
| shadow-advisor | ollama | gemma4:12b | 0.33 | ❌ (json_invalid — markdown wrapper) |

**Experimental recommendations** (not wired into router):
- `forge-builder`: prefer OpenRouter — Ollama misses the `=== file.py ===` format.
- `scout-research`: both providers acceptable — gemma4 produces structured output.
- `shadow-advisor`: prefer OpenRouter — gemma4 wraps JSON in markdown, breaking parse.

## Adding a new rule

Edit `core/evaluation/model_router.py`:

1. Add keywords to `_TASK_RULES` for the right `ModelClass`.
2. Update tests in `tests/core/evaluation/test_model_router.py`.
3. Keep protected-file and budget overrides at the top of `choose()`.

## Relationship to `MissionContext.model_class_hint`

`MissionContextBuilder` also proposes a class hint based on detected risks. The `ModelRouter` is the authoritative caller-owned decision; the context hint is advisory.

## Advisory Mode

The advisory mode reads benchmark results and produces non-prescriptive provider/model
recommendations per role. **The router is not updated automatically. Advisory output
requires human review before any routing change.**

### Command

```bash
python scripts/model_routing_advice.py \
    --input workspace/model_role_benchmark_multi_role.json --json
```

### Output fields (per role)

| Field | Meaning |
|---|---|
| `preferred_provider` | Provider with the best score (null if all skipped) |
| `preferred_model` | Model slug that produced the best result |
| `score` | Score of the best result (0–1) |
| `passed_count` | Providers that passed the quality threshold (score ≥ 0.7) |
| `failed_count` | Providers with a real response but below threshold |
| `skipped_count` | Providers that were unavailable — never counted as failures |
| `confidence` | Always `"low"` until multiple independent runs exist |
| `runtime_enforced` | Always `false` — advisory is informational only |

### Understanding success vs passed vs skipped

- `success=true` — the provider returned a response (no crash/timeout).
- `passed=true` — the response met the quality bar (score ≥ 0.7).
- `skipped=true` — the provider was unavailable; the model is not implicated.
- A skipped provider is **never** counted in `failed_count`.

### Current advisory results (2026-06-22)

From `workspace/model_role_benchmark_multi_role.json`:

| Role | Preferred provider | Score | Passed | Reason |
|---|---|---|---|---|
| forge-builder | openrouter `gpt-oss-120b:free` | 1.0 | 1/2 | Ollama failed artifact validation |
| scout-research | openrouter `gpt-oss-120b:free` | 1.0 | 2/2 | Both passed; OpenRouter faster |
| shadow-advisor | openrouter `gpt-oss-120b:free` | 1.0 | 1/2 | Ollama produced invalid JSON |

These results are **informational observations from one benchmark run**, not routing policies.
