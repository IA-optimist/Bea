# Dead-code notice — `agent_marketplace/`

**Status as of audit 2026-05-18 (P0 architecture):** orphaned module.

- **0 import from the rest of the repo.** Grep of `import.*agent_marketplace` / `from agent_marketplace` on the entire codebase (excluding this dir) returns zero hits.
- ~21 KB, lightweight compared to `mcp/hexstrike-ai/` but the same logic applies.

## Decision pending

Audit §6.3 recommends Sprint 3 to either:

1. **Document the intended consumer surface** (`README.md`, public exports in `__init__.py`) and wire it back to the runtime, OR
2. **Delete** if no consumer exists.

Until that decision is made, **do not import from this directory** in new code.

See `mcp/hexstrike-ai/_DEAD_CODE_NOTICE.md` for the parallel notice on the larger orphan.
