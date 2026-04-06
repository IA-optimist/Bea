# OpenClaw AI Lab

This repository can provision a specialist OpenClaw roster so the user can work with JarvisMax as if it were a small AI lab instead of a single generic assistant.

Important constraint:

- OpenClaw personas are workspace-scoped because `IDENTITY.md`, `SOUL.md`, and `AGENTS.md` live in the workspace root.
- If every agent shares the exact same OpenClaw workspace root, they collapse into the same persona.
- The practical design is:
  - separate OpenClaw home workspaces per specialist
  - one shared project context: `Jarvismax-master`
  - one shared consultation bus inside the repo: `workspace/ai-lab`

## Roster

- `lab-director`: decomposition, prioritization, cross-stream coordination
- `lab-architect`: architecture, boundaries, interfaces, refactor strategy
- `lab-ml-engineer`: models, prompts, MCP, evaluations, autonomous behaviors
- `lab-senior-dev`: implementation, bug fixing, refactoring, delivery
- `lab-researcher`: technical investigation, source-first research, unknown reduction
- `lab-reviewer`: code review, regressions, risk, merge readiness
- `lab-qa`: testing strategy, reproduction, regression coverage
- `lab-devops`: Docker, CI, runtime health, deployment, observability
- `lab-security`: hardening, secrets, approvals, security review
- `lab-data`: storage, schemas, migrations, persistence, retrieval

## Provision The Lab

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_openclaw_ai_lab.ps1
```

The script:

- creates isolated OpenClaw agents
- gives each one a dedicated workspace under `~/.openclaw/lab/<agent-id>/workspace`
- creates a shared lab consultation bus under `workspace/ai-lab`
- writes role-specific `IDENTITY.md`, `SOUL.md`, `AGENTS.md`, `TOOLS.md`, `USER.md`, `MEMORY.md`
- removes the temporary `lab-probe` test agent if present
- reapplies the JarvisMax OpenClaw config via `scripts/configure_openclaw.ps1`

For a fast refresh of the shared lab files without reapplying identities or the base OpenClaw config:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_openclaw_ai_lab.ps1 -SkipIdentity -SkipConfigure
```

The full provision can take a few minutes because OpenClaw updates agent metadata one by one.

## Invoke An Agent

Examples:

```powershell
openclaw agent --agent lab-architect --message "Map the canonical orchestration path for JarvisMax"
openclaw agent --agent lab-ml-engineer --message "Audit the MCP and model-routing stack for weak spots"
openclaw agent --agent lab-senior-dev --message "Implement the fix in core/mcp/mcp_registry.py and validate it"
openclaw agent --agent lab-reviewer --message "Review the current diff and list the highest-risk regressions"
openclaw agent --agent lab-director --message "Split this feature into architecture, implementation, tests, and rollout streams"
```

## Notes

- The agents share the same repository target through `agents.defaults.repoRoot`.
- They keep separate OpenClaw home workspaces so their memory and identity stay specialized.
- They collaborate through the shared repo bus in `workspace/ai-lab`.
- The existing OpenClaw Telegram channel can be bound to `lab-director` as the lab front door.
- In that setup, `lab-director` is the single Telegram-facing entry point and interprets specialist prefixes like `/architect`, `/ml`, `/dev`, `/research`, `/review`, `/qa`, `/ops`, `/security`, and `/data`.
- Use direct `--agent` targeting when you want to talk to a specialist locally from the CLI.
