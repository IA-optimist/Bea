# Contributing to Bea

This repository is optimized for stability first. Keep changes small, testable,
and aligned with the consolidation plan in `docs/superpowers/plans/`.

## Setup

- Python 3.11 or newer
- `pip install -e .`
- `python scripts/validate_local.py`

## Working rules

- Do not add new top-level packages unless the architecture docs are updated in
  the same change.
- Prefer the existing module boundaries over introducing new abstractions.
- Security-sensitive code must fail closed.
- Silent exception swallowing is not acceptable in touched code. Log the error
  with enough context or re-raise it.

## Validation

Run the local gate before opening a PR:

```bash
python scripts/validate_local.py
```

If your change touches the frontend, also run the relevant build or browser
check for that surface.

## Packaging

- `pyproject.toml` is the packaging source of record.
- The release line is `0.x` until the public API is frozen.
- Keep `LICENSE`, `README.md`, and `docs/STATUS.md` aligned with the package
  truth.

## Pull requests

- One logical change per PR.
- Add tests for behavior changes.
- Update docs when public behavior changes.

