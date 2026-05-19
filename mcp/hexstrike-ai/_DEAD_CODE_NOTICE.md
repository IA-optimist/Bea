# Dead-code notice — `mcp/hexstrike-ai/`

**Status as of audit 2026-05-18 (P0 architecture):** orphaned vendored module.

- **0 import from the rest of the repo.** Grep of `import.*hexstrike` / `from.*hexstrike` on the entire codebase (excluding this dir) returns zero hits.
- **~12,000 LOC** of vendored code, dominated by `hexstrike_mcp.py` (~5,469 LOC) and `router_tools.py` (~4,122 LOC).
- **Security flag:** `command_execution.py:131-138` runs `subprocess.Popen(shell=True)` with no sanitisation (gated only by `HEXSTRIKE_EXEC_ENABLED=1`). RCE by design if activated. Audit §4.1 P1.

## Decision pending

The audit (`Audit_Jarvismax_2026-05-18.docx` §6.3) recommends Sprint 3 act on this directory with two options:

1. **Isolate as a submodule** (`vendor/hexstrike-ai`) with an explicit wrapper — keeps the code reachable for security research but out of the main import path.
2. **Delete purely** — removes ~12k LOC and the latent RCE surface entirely. Recoverable from git history if ever needed.

Until that decision is made, **do not import from this directory** in new code. The directory is excluded from ruff (`ruff.toml`) and the .pre-commit hooks.

The same notice applies mutatis mutandis to `agent_marketplace/` (also 0 imports, 21 KB).
