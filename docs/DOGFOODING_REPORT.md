# Dogfooding Report: Coding Agent Worktree Loop

This run validated the coding-agent loop on five small, controlled missions.
The loop now creates a worktree, applies a patch, runs targeted checks, and
writes a reviewable report without touching the main checkout.

## Summary

- Missions attempted: 5
- Missions completed `READY_FOR_REVIEW`: 5
- Missions completed `NEEDS_FIX` or `FAILED`: 0 in the final set
- Final review signal: human review still required

## Mission Log

| Mission | Objective | Files changed | Tests run | Result | Notes |
| --- | --- | --- | --- | --- | --- |
| mission-1 | Fix `sprint3_worktree` CLI task_id parsing | `scripts/sprint3_worktree.py` | `tests/test_sprint3_agent_coder.py` | `READY_FOR_REVIEW` | Removed the CLI crash on `run-gates`, `diff`, and `rollback`. |
| mission-2 | Harden coding-agent test selection | `core/coding_agent/worktree_loop.py` | `tests/coding_agent/test_worktree_loop.py` | `READY_FOR_REVIEW` | Added `tests/coding_agent` routing and requested-test normalization. |
| mission-3b | Add coding-agent selector regressions with fix | `core/coding_agent/worktree_loop.py`, `tests/coding_agent/test_worktree_loop.py` | `tests/coding_agent/test_worktree_loop.py` | `READY_FOR_REVIEW` | Regression tests now cover coding-agent routing and deduplication together with the code change. |
| mission-4b | Add CLI coverage for sprint3 worktree commands with fix | `scripts/sprint3_worktree.py`, `tests/test_sprint3_agent_coder.py` | `tests/test_sprint3_agent_coder.py` | `READY_FOR_REVIEW` | Regression test now covers `create`, `run-gates`, `diff`, and `rollback`. |
| mission-5 | Document coding-agent test selection for its own files | `docs/AGENT_CODER.md` | `tests/test_sprint3_agent_coder.py` | `READY_FOR_REVIEW` | Documentation now matches the selector behavior. |

## What Broke During Dogfooding

- Plain `git apply` rejected valid Windows-generated diffs in this repo.
- The loop now applies patches with `--ignore-space-change`, which makes the
  patch step tolerant of local line-ending and spacing differences.
- Standalone test-only missions failed when the dependent code change was not
  included in the same mission. Bundling the code and its regression test into
  one self-contained mission resolved that.

## Lessons

- The loop is usable on small docs/tests/scripts work, but patch application
  must be Windows-tolerant.
- A mission should carry its own fix plus regression test when the test depends
  on the new behavior.
- The `READY_FOR_REVIEW` status is the right end state; merge remains manual.

## Commands Run

- `python -m pytest tests\\coding_agent\\test_worktree_loop.py tests\\test_sprint3_agent_coder.py -q`
- `python -m ruff check core\\coding_agent\\worktree_loop.py scripts\\sprint3_worktree.py tests\\coding_agent\\test_worktree_loop.py tests\\test_sprint3_agent_coder.py docs\\AGENT_CODER.md`
- `python scripts/validate_local.py`
- `python -m build --wheel`

