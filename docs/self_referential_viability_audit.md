# Self-Referential Viability Audit for Bea

## Status

READ-ONLY AUDIT  NO CODE CHANGES

## Central Question

Does Bea already contain a component `C` whose degradation mechanically weakens Bea's own ability to maintain, repair, or restore `C`?

This is not a question about importance, metrics, documentation, or human judgment. It is a question about a real closed causal loop in the code.

## Scientific Context

Heart Lab already ruled out the idea that a weight-floor or reinstatement thermostat demonstrated intrinsic persistence. Grounding Lab then tightened the standard: the key distinction is not simulated vs real, but declared vs self-referential structure. C6 and C8 are the main filters here: recovery must be possible in a real regime, but no term may be added whose only role is to manufacture the cost of degradation.

## Executive Verdict

NO_SELF_REFERENTIAL_VIABILITY_LOOP_FOUND

I found useful maintenance and learning machinery, but not a mechanically closed loop where a degraded component becomes harder to repair because that same component participates in its own restoration in a non-trivial, code-traceable way.

## Repository Scope

### Inspected

- `README.md`
- `ARCHITECTURE.md`
- `core/coding_agent/repo_map.py`
- `agent_memory/codebase.py`
- `core/repo_map/repo_map_service.py`
- `core/self_improvement/codebase_awareness.py`
- `core/self_improvement/code_patcher.py`
- `core/self_improvement/lesson_memory.py`
- `core/self_improvement/improvement_memory.py`
- `core/self_improvement/failure_collector.py`
- `core/self_improvement/human_gate.py`
- `core/self_improvement/observability.py`
- `core/self_improvement/promotion_pipeline.py`
- `core/self_improvement/research_loop.py`
- `core/self_improvement_loop.py`
- `core/self_improvement/improvement_loop.py`
- `core/self_improvement/goal_registry.py`
- `core/learning_loop.py`
- `core/improvement_memory.py`
- `core/evaluation_engine.py`
- `core/rollback_manager.py`
- `core/execution/recovery.py`
- `agent_security/verifier/policy.py`
- `agent_security/verifier/audit.py`
- `tests/core/repo_map/test_repo_map_service.py`
- `tests/agent_memory/test_memory.py`
- `tests/test_self_improvement_v3_integration.py`
- `tests/test_self_improvement_loop.py`
- `tests/test_self_improvement_v2.py`
- `tests/test_self_improvement_safety.py`
- `tests/test_engineering_discipline.py`
- `tests/test_sprint3_agent_coder.py`

### Not deeply inspected

- Most of `beamax_app/`
- Most `api/` routes outside the self-improvement and learning paths
- `kernel/`
- `core/business/`
- most integration adapters and UI code

## Candidate Summary Table

| Component | Files | Reads | Writes | Self-maintenance? | Degradation effect | Human dependency | C8 risk | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Repo map / codebase awareness | `core/coding_agent/repo_map.py`, `agent_memory/codebase.py`, `core/repo_map/repo_map_service.py`, `core/self_improvement/codebase_awareness.py` | Filesystem, AST, imports, memory store | Memory store facts | Partial | Less accurate code understanding and test suggestions | Strong | Low | WEAK_CANDIDATE |
| Lesson memory | `core/self_improvement/lesson_memory.py`, `core/self_improvement_loop.py`, `core/self_improvement/promotion_pipeline.py` | Past improvement lessons | JSON lesson file | Partial | Future strategy selection loses history | Strong | Low | WEAK_CANDIDATE |
| Improvement memory | `core/self_improvement/improvement_memory.py`, `core/self_improvement/research_loop.py`, `core/learning_loop.py` | Prior improvement records | SQLite / PG / JSON | Partial | Learning addon quality drops | Strong | Low | WEAK_CANDIDATE |
| Verifier policy and audit | `agent_security/verifier/policy.py`, `agent_security/verifier/audit.py` | Intent, target, metadata keys | Append-only audit log | No | Blocking and audit remain, but self-repair is not in scope | None to weak | Low | NOT_A_CANDIDATE |
| Rollback / recovery | `core/rollback_manager.py`, `core/execution/recovery.py` | Backups, build outputs | Backup files, retry decisions | No | Recovery options weaken if backups are incomplete | Strong | Low | NOT_A_CANDIDATE |

## Detailed Candidate Analyses

### Candidate A: Repo map / codebase awareness

1. **Name**: repo-map and codebase-awareness stack.
2. **Normal role**: build a structural representation of the repository and use it to guide patch generation and test selection.
3. **Definition in code**:
   - `core/coding_agent/repo_map.py`: `build_repo_map`, `RepoMap`, `SymbolInfo`, `ImportInfo`
   - `agent_memory/codebase.py`: `CodebaseMemoryService`
   - `core/repo_map/repo_map_service.py`: `RepoMapService`
   - `core/self_improvement/codebase_awareness.py`: `CodebaseAwareness`
4. **Who writes C**:
   - `build_repo_map` writes the in-memory map.
   - `RepoMapService.persist()` writes repo facts and test maps into `OperationalMemoryStore`.
5. **Who reads C**:
   - `CodebaseMemoryService`, `RepoMapService`, `CodebaseAwareness`, `code_patch_generator`, `bea_eval`, tests.
6. **Who maintains C**:
   - `build_repo_map()` rebuilds from filesystem on demand.
   - `RepoMapService.persist()` refreshes memory facts.
7. **Does C participate in its own maintenance?**
   - **Partially**, but only in the weak sense that it can index files including itself.
   - It does not use the stored repo-map output to reconstruct itself.
8. **How can C degrade?**
   - stale snapshot, incomplete scan, parse errors, max-file truncation, fallback AST scan, stale test mapping.
9. **Mechanical effect of degradation**:
   - worse file understanding, weaker symbol ranking, weaker test suggestion, weaker consistency warnings.
10. **Does degradation make its own repair harder?**
   - **Partly**, because patch planning becomes less informed.
   - **Not strongly**, because rebuild comes from direct filesystem scanning, not from the repo-map artifact itself.
11. **Does the loop already exist?**
   - **No closed loop**.
12. **Auto-reference or trivial circularity?**
   - It is a self-describing index, not a self-healing organ.
13. **Human dependency**:
   - strong. Humans still decide what to fix and whether to trust the map.
14. **External metric dependency**:
   - no obvious health score or reward gate drives repair.
15. **C8 risk**:
   - low. No obvious coefficient whose only role is to create the cost of repo-map degradation.
16. **Evidence chain**:
   - `code_patch_generator.py` calls `CodebaseAwareness.check_consistency()`
   - `RepoMapService.persist()` stores repo facts and test maps
   - `CodebaseMemoryService.snapshot()` and `build_repo_map()` rebuild from files
   - none of these paths repair the repo map by consuming a degraded repo-map artifact.
17. **Strongest counter-hypothesis**:
   - this is only a code-understanding aid, not a maintenance loop.
18. **Verdict candidate**:
   - `WEAK_CANDIDATE`
19. **Why**:
   - it influences modification decisions, but the code does not show that its own degradation mechanically weakens its own restoration in a closed way.

### Candidate B: Lesson memory

1. **Name**: lesson memory for self-improvement cycles.
2. **Normal role**: store past attempts so future improvement cycles can reuse lessons.
3. **Definition in code**:
   - `core/self_improvement/lesson_memory.py`
   - `core/self_improvement_loop.py` re-exports and consumes it
   - `core/self_improvement/promotion_pipeline.py` records lessons
4. **Who writes C**:
   - `LessonMemory.store()`
   - `BeaImprovementLoop.run_cycle()`
   - `PromotionPipeline.record_lesson()`
5. **Who reads C**:
   - `BeaImprovementLoop.run_cycle()` calls `search()` and `get_success_rate()`
6. **Who maintains C**:
   - plain JSON load/save in `LessonMemory`
7. **Does C participate in its own maintenance?**
   - **No** in the strong sense.
8. **How can C degrade?**
   - missing file, partial write, truncated JSON, stale lessons, bad keywords.
9. **Mechanical effect of degradation**:
   - fewer remembered lessons, weaker strategy filtering.
10. **Does degradation make its own repair harder?**
   - **Only weakly**: loss of history weakens future choice, but repair of the lesson file itself is not mediated by lesson content.
11. **Does the loop already exist?**
   - **No**.
12. **Auto-reference or trivial circularity?**
   - It is a memory store for improvement attempts, not a self-maintenance organ.
13. **Human dependency**:
   - strong. Humans still arbitrate improvement paths and review pipeline outputs.
14. **External metric dependency**:
   - it uses success rates, but as a strategy filter, not as a self-healing trigger.
15. **C8 risk**:
   - low. No dedicated "damage" coefficient.
16. **Evidence chain**:
   - `BeaImprovementLoop.run_cycle()` loads past lessons and may skip a strategy if `get_success_rate()` is low
   - it then stores a new lesson after the cycle
   - the storage path is a direct JSON file, not a self-repair mechanism.
17. **Strongest counter-hypothesis**:
   - degraded lessons merely reduce optimization quality.
18. **Verdict candidate**:
   - `WEAK_CANDIDATE`
19. **Why**:
   - this is historical guidance, not self-referential viability.

### Candidate C: Improvement memory

1. **Name**: improvement memory / learning memory.
2. **Normal role**: track past improvement feedback and feed it back into future agent prompts and escalation checks.
3. **Definition in code**:
   - `core/self_improvement/improvement_memory.py`
   - `core/learning_loop.py`
   - `core/self_improvement/research_loop.py`
4. **Who writes C**:
   - `SelfImprovementMemory.record()`
   - `ResearchLoop._store_learning()`
   - `LearningLoop` reads it indirectly for prompt addons
5. **Who reads C**:
   - `LearningLoop.get_agent_system_prompt_addon()`
   - `LearningLoop.generate_weekly_report()`
   - `LearningLoop.get_global_lessons()`
6. **Who maintains C**:
   - SQLite / PG / JSON persistence depending on path
7. **Does C participate in its own maintenance?**
   - **No**.
8. **How can C degrade?**
   - backend unavailable, stale rows, missing table, partial writes, bad fetches.
9. **Mechanical effect of degradation**:
   - weaker prompt learning, weaker escalation logic, worse cross-agent lesson retrieval.
10. **Does degradation make its own repair harder?**
   - **No direct evidence**.
11. **Does the loop already exist?**
   - **No**.
12. **Auto-reference or trivial circularity?**
   - the memory is used to improve agents, not to repair itself.
13. **Human dependency**:
   - strong. The memory only informs future decisions.
14. **External metric dependency**:
   - it uses improvement scores and rates, but not as a self-repair trigger.
15. **C8 risk**:
   - low.
16. **Evidence chain**:
   - `ResearchLoop._store_learning()` records outcomes in improvement memory
   - `LearningLoop._build_addon()` reads top feedback and formats prompt addons
   - no path uses that memory to repair the memory subsystem itself.
17. **Strongest counter-hypothesis**:
   - this is just a general learning log.
18. **Verdict candidate**:
   - `WEAK_CANDIDATE`
19. **Why**:
   - the structure is useful, but not self-referential in the requested causal sense.

### Candidate D: Verifier policy and audit

1. **Name**: verifier policy and verifier audit log.
2. **Normal role**: deny-by-default action filtering and append-only auditing.
3. **Definition in code**:
   - `agent_security/verifier/policy.py`
   - `agent_security/verifier/audit.py`
4. **Who writes C**:
   - policy writes decisions; audit appends log entries.
5. **Who reads C**:
   - the verifier policy reads `ActionIntent` only; audit log is for inspection.
6. **Who maintains C**:
   - essentially nobody inside the verifier loop. The audit log is append-only.
7. **Does C participate in its own maintenance?**
   - **No**.
8. **How can C degrade?**
   - log truncation, policy drift, missing coverage, stale allowlists.
9. **Mechanical effect of degradation**:
   - weaker safety decisions or weaker audit visibility.
10. **Does degradation make its own repair harder?**
   - not shown in code.
11. **Does the loop already exist?**
   - **No**.
12. **Auto-reference or trivial circularity?**
   - the design is intentionally anti-self-modifying.
13. **Human dependency**:
   - strong for policy changes; audit is meant for later review.
14. **External metric dependency**:
   - no.
15. **C8 risk**:
   - low.
16. **Evidence chain**:
   - `VerifierPolicy.evaluate()` can halt or deny actions targeting verifier/security/audit targets
   - `VerifierAuditLog.record()` stores metadata only
   - nothing here rebuilds or repairs the verifier from its own degraded state.
17. **Strongest counter-hypothesis**:
   - this is a governance boundary, not a viability loop.
18. **Verdict candidate**:
   - `NOT_A_CANDIDATE`
19. **Why**:
   - the subsystem protects itself from modification instead of using itself to restore itself.

### Candidate E: Rollback / recovery

1. **Name**: rollback manager and recovery helpers.
2. **Normal role**: save backups and provide restoration after experiments or failures.
3. **Definition in code**:
   - `core/rollback_manager.py`
   - `core/execution/recovery.py`
4. **Who writes C**:
   - backup creation writes copies of target files.
5. **Who reads C**:
   - rollback routines read the backup metadata and restore files.
6. **Who maintains C**:
   - the experiment or self-improvement pipeline creates the rollback points.
7. **Does C participate in its own maintenance?**
   - **No**.
8. **How can C degrade?**
   - missing backups, incomplete target list, stale metadata.
9. **Mechanical effect of degradation**:
   - fewer restore options for changed files.
10. **Does degradation make its own repair harder?**
   - **Not shown**. It only weakens recovery of other files.
11. **Does the loop already exist?**
   - **No**.
12. **Auto-reference or trivial circularity?**
   - ordinary restoration tooling.
13. **Human dependency**:
   - strong.
14. **External metric dependency**:
   - none.
15. **C8 risk**:
   - low.
16. **Evidence chain**:
   - rollback points are created for experiments
   - restore operations copy file backups back to target paths
   - there is no code path where the rollback manager restores itself through its own damaged state.
17. **Strongest counter-hypothesis**:
   - the presence of backups is only operational safety, not self-referential viability.
18. **Verdict candidate**:
   - `NOT_A_CANDIDATE`
19. **Why**:
   - restoration exists, but not self-restoration.

## Evidence Chains

### Repo map / codebase awareness

```text
core/self_improvement/code_patcher.py
  -> CodebaseAwareness.check_consistency()
  -> reads sibling conventions and file structure
  -> may influence patch generation warnings
  -> could affect changes to repo-map-related code

agent_memory/codebase.py
  -> build_repo_map()
  -> scans filesystem directly
  -> rebuilds the index from source files, not from stored repo-map state
```

This is a dependency chain, not a closed viability loop.

### Lesson memory

```text
core/self_improvement_loop.py::BeaImprovementLoop.run_cycle()
  -> LessonMemory.search()
  -> strategy skip / fallback selection
  -> LessonMemory.store()
```

The lesson log informs future choices, but the code does not show that lesson-memory degradation makes lesson-memory restoration harder in a mechanical self-referential way.

### Improvement memory

```text
core/self_improvement/research_loop.py::_store_learning()
  -> get_improvement_memory().record()

core/learning_loop.py::_build_addon()
  -> get_improvement_memory().get_top_feedback()
  -> prompt addon for future agents
```

The memory improves future agents. It does not repair itself.

## Conclusion

Bea already has:

- code understanding tools
- lesson memory
- improvement memory
- rollback/recovery infrastructure
- a strict verifier

But these are separate utilities, not a closed self-referential viability loop in the sense defined by the audit.

The strongest pattern is:

- representation helps maintenance of nearby code
- memory helps future decisions
- recovery helps revert failures

What is missing is the stronger causal chain:

- component `C`
- whose degradation mechanically weakens the system's ability to restore `C`
- without relying on an external score, an arbitrary penalty, or a human deciding that `C` matters.

That chain was not found in the inspected code.
