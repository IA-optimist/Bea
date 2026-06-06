"""Smoke harness for the FastAPI 0.109 → 0.115 bump (audit C4 prep).

Run with the side-venv that has fastapi==0.115.x installed::

    .venv-c4-prep/Scripts/python.exe scripts/c4_fastapi_115_smoke.py

Tries to import a graded list of modules (cheap to expensive). Captures
the first ImportError / AttributeError / Pydantic ValidationError per
module and prints a JSON report so we can build the migration plan from
real data instead of guessing.

Exit code is always 0 — this is a discovery tool, not a gate.
"""
from __future__ import annotations

import importlib
import json
import sys
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


# Ordered from cheap to load to expensive (more transitive imports).
MODULES_TO_PROBE = [
    # Config + auth helpers
    "config.settings",
    "api.auth",
    "api.token_utils",
    "api._deps",
    # New stuff I just landed
    "api.jwt_v2",
    "core._logging_helpers",
    # Routes — cheap ones first
    "api.routes.auth",
    "api.routes.system_readiness",
    "api.routes.economic",
    "api.routes.business",
    # Models flagged by the v1 audit
    "models.project",
    "core.agent_factory",
    # Heavy: the app factory itself
    "api.main",
]


def probe(name: str) -> dict:
    try:
        importlib.import_module(name)
    except BaseException as exc:  # noqa: BLE001 — we want everything
        tb = traceback.format_exc(limit=12)
        return {
            "ok": False,
            "exc_type": type(exc).__name__,
            "exc_msg": str(exc)[:300],
            "traceback_tail": tb.splitlines()[-6:],
        }
    return {"ok": True}


def main() -> int:
    results: dict[str, dict] = {}
    for name in MODULES_TO_PROBE:
        results[name] = probe(name)

    ok = sum(1 for r in results.values() if r["ok"])
    ko = len(results) - ok
    summary = {
        "fastapi_version": __import__("fastapi").__version__,
        "starlette_version": __import__("starlette").__version__,
        "pydantic_version": str(__import__("pydantic").VERSION),
        "modules_ok": ok,
        "modules_failed": ko,
    }
    sys.stdout.write(json.dumps(
        {"summary": summary, "results": results},
        indent=2, ensure_ascii=False,
    ))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
