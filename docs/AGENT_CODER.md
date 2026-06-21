# Agent Coder

The coding agent loop is deliberately conservative. It prepares code changes in
an isolated git worktree, runs targeted checks, writes reports, and then waits
for human review. It does not merge automatically.

## Cycle

1. Receive a mission with `title`, `description`, optional `target_files`,
   `risk_level`, and optional `requested_tests`.
2. Reject the mission if any requested target is protected.
3. Verify the repository supports git worktrees.
4. Create a unique branch and worktree for the mission.
5. Apply the supplied patch inside the worktree only.
6. Detect changed files with `git status --porcelain`.
7. Select targeted tests:
   - explicit `requested_tests` win;
   - `core/coding_agent/*` maps to `tests/coding_agent`;
   - `api/routes/*` maps to `tests/api` when present;
   - `core/self_improvement/*` maps to `tests/self_improvement`;
   - `core/memory/*` maps to `tests/memory`;
   - `scripts/*` maps to `tests/scripts`;
   - otherwise the safe fallback is `tests/test_sprint3_agent_coder.py`.
8. Run lint and targeted tests in the worktree.
9. Write JSON and Markdown reports under `workspace/coding_agent/runs/<run_id>/`.
10. Stop for human review.

## Statuses

- `PLANNED`: run object created.
- `WORKTREE_CREATED`: isolated worktree exists.
- `PATCH_APPLIED`: patch was applied in the worktree.
- `TESTING`: lint/tests are running.
- `NEEDS_FIX`: patch is recoverable, but lint or tests failed.
- `READY_FOR_REVIEW`: patch, lint, tests, and security gate passed.
- `REJECTED`: protected path or security gate violation.
- `FAILED`: tool failure such as Git/worktree unavailable or patch application crash.
- `ROLLED_BACK`: reserved for explicit cleanup flows.

## Security Rules

- The agent never edits `main` or the current checkout directly.
- Every code mission must use a git worktree.
- Protected paths are checked before and after patch application.
- `READY_FOR_REVIEW` is not a merge signal. A human must inspect the diff and
  create or approve the PR.
- Failed Git/worktree setup returns `FAILED`, never `READY_FOR_REVIEW`.
- Protected files return `REJECTED`, never `READY_FOR_REVIEW`.

## Local Usage

```python
from pathlib import Path
from core.coding_agent.worktree_loop import CodingAgentRunner, MissionInput

runner = CodingAgentRunner(repo_root=Path.cwd())
mission = MissionInput(
    title="Fix small parser bug",
    description="Apply a reviewed diff and run targeted tests.",
    target_files=["core/coding_agent/parser.py"],
    risk_level="medium",
    requested_tests=["tests/test_sprint3_agent_coder.py"],
)
run = runner.run(mission, unified_diff=reviewed_diff)
print(run.status)
print(run.report_path)
```

## Reading Reports

Each run writes:

- `report.json`: machine-readable mission, run status, changed files, tests,
  lint result, security gate result, rollback instructions, human actions, and
  mission-learning fields (`mission_id`, `goal`, `mission_type`, `success`,
  `agents_used`, `tools_used`, `plan_steps`, `complexity`, `error_category`,
  `duration_s`).
- `report.md`: human-readable review note with the same core facts.

The rollback section contains the worktree removal and branch deletion commands.
Run them only after preserving any work you still need.

## Human Review Remains Mandatory

The loop can prove that a patch was isolated and checked. It cannot decide that
the product, security, or architecture impact is acceptable. A human reviewer
must inspect the diff, decide whether to open a PR, and merge only after normal
review.
