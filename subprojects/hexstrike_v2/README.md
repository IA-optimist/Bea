# HexStrike V2

This directory is the future standalone home of the HexStrike V2 penetration-
testing framework. During the Bea consolidation (Task 6.6) the vendored module
at `mcp/hexstrike_v2/` is flagged for extraction.

## Status

- Core tool categories: recon, scanning, web, exploitation, network.
- Risk levels and approval hooks exist but still default to local execution.
- `psutil` is intentionally not declared as a dependency here until external
  review of the process-manager module is complete.

## Migration plan

1. Copy or move `mcp/hexstrike_v2/` to this package root.
2. Fix any Bea-specific imports (e.g. `core.connectors.hexstrike`).
3. Add tests under `tests/` and CI workflow.
4. Publish `hexstrike-v2` as its own package.
5. In Bea, replace `mcp/hexstrike_v2` usage with the external package and remove
   the vendored copy.
