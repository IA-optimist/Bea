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

## Adding a new rule

Edit `core/evaluation/model_router.py`:

1. Add keywords to `_TASK_RULES` for the right `ModelClass`.
2. Update tests in `tests/core/evaluation/test_model_router.py`.
3. Keep protected-file and budget overrides at the top of `choose()`.

## Relationship to `MissionContext.model_class_hint`

`MissionContextBuilder` also proposes a class hint based on detected risks. The `ModelRouter` is the authoritative caller-owned decision; the context hint is advisory.
