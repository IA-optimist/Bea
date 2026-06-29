# Execution Surface

This document records where Bea can start a process or execute code. The new
agentic ACI path is hardened, but the historical `core/` and `scripts/` surface
is not fully migrated behind ACI yet.

## Agentic Runtime Surface

| File | Function | Execution type | Risk | Mitigation |
| --- | --- | --- | --- | --- |
| `agent_runtime/sandbox.py` | `SandboxWrapper.run` | Docker sandbox or restricted subprocess fallback | Command execution | No shell, command metacharacters rejected, command allowlist, sanitized env, timeout, no secrets injected |
| `agent_runtime/executor.py` | `ACIExecutor.execute` | Action dispatch | Unauthorized tool/action execution | Deny-by-default registry, capability check, realm check, path scope, risk/approval gate, audit log |
| `agent_runtime/results.py` | `apply_patch_handler` | File modification | Wrong file or unsafe patch | Path traversal blocked, target mismatch blocked, empty/large patch blocked, context required, diff summary and hashes returned |
| `agent_github/mission_loop.py` | `build_pr_body` | GitHub PR preparation | Auto-merge or unreviewed PR | Draft-only body, tests required, verdict required, auto-merge explicitly disabled |

## Historical Surface Still Present

| File area | Execution type | Current risk | Current mitigation | Status |
| --- | --- | --- | --- | --- |
| `core/tool_executor.py` | Subprocess-backed tool execution | Runtime execution outside new ACI | Existing timeout and tests | Needs future ACI migration |
| `core/self_improvement/sandbox_executor.py` | Docker and subprocess test execution | Broad validation harness | Timeouts, Docker option, tests | Needs future ACI policy adapter |
| `core/business/*` | Git/deploy subprocess commands | Business automation side effects | Existing explicit commands and timeouts in places | Experimental/human-gated |
| `core/mcp/mcp_registry.py` | MCP process launch | Long-running child process | Timeout handling | Needs policy audit before beta expansion |
| `scripts/*.py` | CI, smoke, seed, validation commands | Local developer tooling | Fixed argv patterns in most cases | Developer tooling only, not agent action surface |
| `api/routes/dashboard.py` and `api/routes/monitoring.py` | Git/status subprocess reads | Local runtime introspection | Read-only fixed commands with timeout | Acceptable with continued redaction review |

## Current Rules

- New agentic actions must enter through `ACIExecutor`.
- Unknown actions are denied.
- Actions missing required capabilities are denied.
- Realms are explicit and checked when configured.
- Write paths are denied unless explicitly in `allowed_paths`.
- Secrets are redacted in action results and audit payload summaries.
- Network access is not granted by default in `SandboxPolicy`.
- Free shell execution is not part of the ACI contract.

## Known Gaps

- Not every historical `core/` subprocess call is routed through ACI.
- Some legacy business automation paths are still experimental and need a
  dedicated policy adapter before wider beta use.
- `apply_patch_handler` is intentionally minimal: it supports a single update
  patch shape and should be extended before replacing mature patch tooling.
