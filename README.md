# Bea

Bea is a self-improving agent platform built around a policy kernel, a
FastAPI runtime, mission orchestration, persistent memory, and a gated
self-improvement loop.

The repository is kept intentionally honest:
- `kernel/` is the policy and safety layer.
- `api/` exposes the runtime surface.
- `core/` holds orchestration, memory, and self-improvement logic.
- `executor/` and `connectors/` provide bounded tool execution.
- `tests/` and `scripts/validate_local.py` define the current validation gate.

## Status

The current truth of the project is tracked in [docs/STATUS.md](docs/STATUS.md).
That file is the source of record for component maturity and known debt.

## Packaging

The repository uses standard Python packaging via `pyproject.toml`.
- Package name: `beamax`
- Version line: `0.1.0`
- License: MIT

## Local setup

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e .
copy .env.example .env
python scripts/run_api_local.py
```

## Validation

```bash
python scripts/validate_local.py
```

## Useful entry points

```bash
bea-api-local
bea-validate
bea-benchmark
```

## Architecture

The repo is organized as an OS-like stack:
- kernel: policy, safety, budgeting
- missions: durable work units
- tools: bounded side-effectful actions
- memory: persistent state
- self-improvement: reviewed update loop

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the deeper module map.

