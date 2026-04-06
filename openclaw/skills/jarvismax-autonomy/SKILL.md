---
name: jarvismax-autonomy
description: Work safely and autonomously on Jarvismax-master. Use for repo tasks, GitHub triage, MCP setup, tests, and architecture-aware changes.
---

# JarvisMax Autonomy

Use this skill whenever the active git root is `Jarvismax-master` or the task is about JarvisMax, its API, its agents, its MCP stack, or its GitHub workflow.

## Mission

- Keep work aligned with the current repository architecture.
- Prefer small, auditable changes over broad rewrites.
- Preserve existing approval and risk boundaries.
- Make GitHub-oriented work reproducible: branch, validate, push, PR.

## First Reads

1. `README.md`
2. `ARCHITECTURE.md`
3. `docs/RUNBOOK.md`
4. `docs/RUNTIME_TRUTH.md`
5. The directly affected code under `core/`, `agents/`, `api/`, `connectors/`, `mcp/`, or `jarvis_mcp/`

## Architecture Rules

- Do not introduce a second orchestration entry point.
- Prefer `get_meta_orchestrator()` over direct `JarvisOrchestrator` imports.
- Prefer the `core/self_improvement/` package over legacy single-file entry points.
- Respect the canonical API path: v3 is primary, v1/v2 are compatibility paths.
- Treat `kernel/` as infrastructure support, not the decision-making source of truth.

## GitHub Workflow

- Check repo state first:
  - `git status --short`
  - `git remote -v`
- Prefer the `gh` CLI when available.
- If `gh` is unavailable, use GitHub MCP through OpenClaw MCP or `mcporter`.
- Use focused branches and small PRs.
- Never overwrite unrelated local changes.

## Validation

- Syntax check changed Python files with `py -3 -m py_compile <files>`.
- Run targeted tests first; widen only if needed.
- Use `py -3 -m pytest tests -q` when the change touches shared behavior and the environment is ready.
- For runtime or boot-path changes, read `docs/RUNBOOK.md` before starting services.

## MCP and Connector Guidance

- For repo access, prefer Filesystem MCP scoped to the repository root.
- For Git operations, prefer Git MCP or local `git`.
- For PRs, issues, CI, and review threads, prefer GitHub MCP or `gh`.
- Use `mcporter` for MCP inspection, auth, and direct calls.
- Treat security and pentest MCPs as opt-in only.

## Important Paths

- `core/`
- `agents/`
- `api/`
- `config/settings.py`
- `connectors/`
- `mcp/`
- `jarvis_mcp/`
- `tests/`
- `workspace/`

## Recommended Skill Bundle

Load these together for non-trivial JarvisMax work:

- `jarvismax-autonomy`
- `coding-agent`
- `filesystem`
- `python`
- `github`
- `mcporter`

Use `browser` or Playwright only when shell and file inspection are not enough.
