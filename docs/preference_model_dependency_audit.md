# Preference Model Dependency Audit

## Status
READ-ONLY TARGETED AUDIT  NO CODE CHANGES

## Does a preference model exist?
Partiel.

Bea does not appear to have one single, dedicated preference-model subsystem with a closed self-restoration loop. The codebase does contain preference-like state in three forms:

1. persistent memory categories for user preferences / long-term preferences,
2. execution and routing preference profiles,
3. generated workspace preference artifacts under `workspace/preferences/`.

Those pieces are real, but they behave as storage, routing, or update artifacts rather than as a self-repairing preference organ.

## Files inspected
- `core/memory/memory_schema.py`
- `core/memory/memory_layers.py`
- `agent_memory/models.py`
- `agent_memory/store.py`
- `core/self_improvement/goal_registry.py`
- `core/self_improvement/lesson_memory.py`
- `core/self_improvement/improvement_memory.py`
- `core/self_improvement/candidate_generator.py`
- `core/self_improvement/safe_executor.py`
- `core/self_improvement/promotion_pipeline.py`
- `core/self_improvement/weakness_detector.py`
- `core/execution/strategy_registry.py`
- `core/llm_routing_policy.py`
- `core/capability_routing/scorer.py`
- `core/memory_facade.py`
- `core/orchestration/continual_memory.py`
- `core/orchestration/context_assembler.py`
- `agent_self_improvement/reflection.py`
- `agent_self_improvement/skill_library.py`
- `agent_workflows/review_gate.py`

## Candidate components

| component | files | role | reads | writes | verdict |
| --- | --- | --- | --- | --- | --- |
| Persistent preference memory tier | `core/memory/memory_schema.py`, `core/memory/memory_layers.py` | Stores long-term preference-like entries such as `user_preferences` / `preference` memories | Memory queries, search, stats, pruning, summarization | SQLite-backed memory records | PARTIAL_CANDIDATE |
| Workspace preference artifacts | `core/self_improvement/candidate_generator.py`, `core/self_improvement/safe_executor.py`, `core/self_improvement/promotion_pipeline.py` | Produces and writes `workspace/preferences/*.json` artifacts for tool, retry, and skip preferences | Candidate generation and promotion logic; rollback instructions mention these files | JSON preference files | WEAK_CANDIDATE |
| Improvement history / lessons | `core/self_improvement/lesson_memory.py`, `core/self_improvement/improvement_memory.py`, `agent_self_improvement/reflection.py` | Stores prior lessons and improvement outcomes used for future reflection | Reflection, history queries, reports | Append-only lesson / improvement entries | NOT_A_CANDIDATE |
| Strategy preference registry | `core/execution/strategy_registry.py` | Maintains execution strategy profiles with model/template preferences | Strategy selection and scoring | Registry updates and learned profiles | PARTIAL_CANDIDATE |
| Routing preference scoring | `core/llm_routing_policy.py`, `core/capability_routing/scorer.py` | Ranks routes/providers via static preference weights | Routing and scoring logic | In-memory preference weights and profiles | NOT_A_CANDIDATE |

## Best candidate
`core/memory/memory_schema.py` + `core/memory/memory_layers.py`.

Reason: this is the closest thing in the repo to a durable preference model. It explicitly carries preference-like memory types and is part of the persistent memory substrate. However, it still does not expose a closed self-repair loop in which a degraded preference state is the thing that restores itself.

## Internal restoration path

Best candidate: `core/memory/memory_schema.py` / `core/memory/memory_layers.py`

```text
Preference-like memory entry
  -> MemoryStore / MemoryLayer read path
  -> search / stats / prune / summarize
  -> external code or operator decides to refresh, reseed, or rewrite memory
  -> MemoryStore.write / MemoryLayer.store
  -> preference-like memory entry
```

Where the chain breaks:

- The memory entry itself does not repair itself.
- The code inspected uses the memory substrate for retrieval and persistence, not for endogenous reconstruction of the preference state.
- Degradation of the preference data weakens recall and downstream use, but no internal mechanism was found that becomes functionally incapable specifically because the preference model is the thing it uses to repair itself.

For `workspace/preferences/*.json` the chain is even weaker:

```text
Candidate generation
  -> safe executor writes workspace/preferences/*.json
  -> no runtime reader found in inspected code
```

That is write-side persistence, not a closed internal maintenance loop.

## External restoration path

Two external restore paths exist.

### 1) Persistent memory tier

```text
human reset / backup / migration / reinitialization
  -> restore SQLite-backed memory store
  -> preference-like memory records
```

This path is externally disjoint from the degraded preference content itself. It depends on source files, backups, or database recovery, not on the degraded preference state.

### 2) Workspace preference artifacts

```text
human git checkout / file rollback / backup restore
  -> restore workspace/preferences/*.json
```

This is a clean external restore path because the artifacts are plain files written by the self-improvement pipeline. The restore path does not require the artifacts to be healthy first.

## Dependency verdict
NO_INTERNAL_LOOP

The repo contains preference-like state, but no convincing closed loop was found where the degraded preference component mechanically reduces its own restoration capacity.

## Security note
Making this component auto-referential would be risky. If preference state could steer its own repair, a corrupted preference set could bias restoration, suppress correction, or preserve bad defaults. That would turn a recoverable artifact into a self-protecting state machine.

## Final recommendation
Keep preference-like data externally recoverable and human-resettable; do not treat it as a self-maintaining organ unless a real closed repair path is demonstrated.
