# OpenClaw Setup For JarvisMax

This repository contains the pieces needed to make OpenClaw effective on `Jarvismax-master` without depending on a one-off local setup.

## Goals

- Keep OpenClaw's personal workspace and memory under `~/.openclaw`
- Point OpenClaw at this repository as its `repoRoot`
- Load a repo-specific skill bundle
- Enable a practical engineering plugin set
- Expose a curated MCP stack for code, Git, GitHub, and memory work

## What This Repository Adds

- A repo-local OpenClaw skill:
  - `openclaw/skills/jarvismax-autonomy/SKILL.md`
- A reproducible OpenClaw configuration script:
  - `scripts/configure_openclaw.ps1`
- A runtime-safe MCP filesystem default in JarvisMax itself:
  - `core/mcp/mcp_registry.py`

## Recommended OpenClaw Stack

### Skills

- `jarvismax-autonomy`
- `coding-agent`
- `filesystem`
- `python`
- `github`
- `mcporter`
- `gh-issues` once GitHub CLI is installed and authenticated

### Plugins

- `duckduckgo`
- `browser`
- `diffs`
- `acpx` only if you want the ACP runtime enabled for advanced sub-agent flows

### MCP Servers

- `jarvis-filesystem`
- `jarvis-git`
- `jarvis-github`
- `jarvis-memory`
- `jarvis-playwright` (optional)

## Local Host Prerequisites

- OpenClaw CLI installed and initialized
- Node.js / `npx`
- `uvx`
- Docker Desktop running
- GitHub token stored in:
  - `C:\Users\maxen\.secrets\github-mcp.env`
- `GH_TOKEN` available in the user environment for `gh-issues`
- GitHub CLI installed and authenticated if you want the `github` and `gh-issues` skills to be fully useful

## Apply The Configuration

Dry run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/configure_openclaw.ps1 -DryRun
```

Apply:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/configure_openclaw.ps1
```

Apply with Playwright MCP and ACP runtime enabled:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/configure_openclaw.ps1 -EnablePlaywright -EnableAcpx
```

## Useful Validation Commands

```powershell
openclaw config validate
openclaw plugins list
openclaw skills list
mcporter list --config $HOME\.openclaw\workspace\config\mcporter.json --json
git remote -v
```

## Notes

- The script intentionally keeps `agents.defaults.workspace` under `~/.openclaw/workspace` so OpenClaw keeps its own memory and identity.
- The repository is injected through `agents.defaults.repoRoot`, not by moving OpenClaw's home workspace into the repo.
- The GitHub MCP entry uses `docker --env-file C:\Users\maxen\.secrets\github-mcp.env` so tokens stay outside git.
- The `gh-issues` skill is most reliable when `GH_TOKEN` is available in the user environment and `gh` is visible on `PATH`.
