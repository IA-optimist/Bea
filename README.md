# Bea

Bea is a Developer Preview / Private Beta 0.1 agent platform built around a
policy kernel, a FastAPI runtime, mission orchestration, persistent memory, and
a gated self-improvement loop.

PUBLIC_BETA_READY: false

The repository is intentionally conservative about claims:

- `kernel/` is the policy and safety layer.
- `api/` exposes the runtime surface.
- `core/` holds orchestration, memory, and self-improvement logic.
- `executor/` and `connectors/` provide bounded tool execution.
- `tests/` and `scripts/validate_local.py` define the current validation gate.

## Status

The current truth of the project is tracked in [docs/STATUS.md](docs/STATUS.md).
Private Beta 0.1 can be considered only for 5-10 technical testers under
supervision. Public beta remains NO-GO.

## Local Setup

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e .
copy .env.example .env
python scripts/run_api_local.py
```

## Validation

```bash
python scripts/validate_local.py --quick
python scripts/check_client_v1_usage.py
python scripts/check_docs_truth.py
```

## Useful Entry Points

```bash
bea-api-local
bea-validate
bea-benchmark
```

## Safety Notes

- Self-improvement is disabled by default.
- Dangerous actions must stay gated or out of scope.
- Testers must not use real secrets, private data, medical data, financial data,
  or customer data.
- `RedisSessionStore` is required/recommended for multi-process or multi-worker
  use; `InMemorySessionStore` is only for local single-process testing.
