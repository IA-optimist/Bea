# Bea Alpha Readiness

## Current Gate Status

- `smoke_e2e_cycle`: local fixture gate, no LLM required.
- `bea_eval`: expected to remain green after mission report ingestion.
- Provider runtime: outside this PR; this change does not touch providers.
- Code mission artifact gate: added for `needs_actions=True` missions.
- Code execution loop: helper added to strip markdown from Python blocks and
  validate syntax before accepting a materialized artifact.

## SHA256 Mission Review

Observed mission:

- `mission_id`: `6ae60964-bae`
- goal: `Ecris une fonction Python sha256_file(path) qui lit par chunks de 8192 bytes. Retourne le digest hex.`
- agent: `forge-builder` with memory/research support
- status recorded by mission state: `DONE`
- learning run status: `SUCCESS`
- duration evidence: latest completed goal entry reports about `71.8s`
- created artifact announced: `sha256_file.py`
- report JSON: not found in the local workspace inspection
- tests: not found

Actual artifact result:

- `C:\Users\maxen\Documents\Béa\workspace\sha256_file.py` exists.
- The original generated file contained Python followed by Markdown sections
  and a closing code fence.
- Running it with Python fails with `SyntaxError`.

Classification: `D. FAILED` as an exploitable code mission. If the UI or
mission state presents it as completed, that completion is weak because the
artifact is not executable and no test or ingestion-compatible report was
found.

## Forge-Builder Readiness

`forge-builder` is only alpha-ready for code when the extraction and syntax
gate are active. It can produce useful implementation text, and it can trigger
a file action, but the SHA256 mission proved that a materialized file can still
be invalid if Markdown leaks into the artifact.

The current PR raises the bar:

- `needs_actions=True` requires a verifiable artifact.
- Declared files must exist.
- Explicit code missions require test evidence and syntax validation.
- Text-only answers cannot be promoted to `COMPLETED`.
- The SHA256 smoke fixture proves source extraction, syntax validation, test
  execution, report generation, ingestion, and memory creation with no
  provider dependency.
- `provider_used` / `model_used` are now present in the SHA256 report fixture.

## Metadata Gap

`provider_used` and `model_used` are still lost on the historical runtime write
path in `core/executor/pipeline_auto.py` when `learning_runs.json` is written.
`LearningEngine.record_run()` persists what it receives; the missing metadata is
not created there. Fixing that requires a follow-up in the executor path, which
is outside this PR's scope.

## Remaining Risks

- The validator checks artifact presence and test evidence, not semantic code
  correctness by itself.
- A report can document a test command without this smoke executing that exact
  command.
- Runtime provider behavior remains covered by provider and alpha cycle gates,
  not by this PR.
- Existing historical mission records may still show optimistic statuses until
  re-run through the stricter gate.
- `learning_runs.json` still lacks provider/model on older runs until the
  executor write path is updated.
