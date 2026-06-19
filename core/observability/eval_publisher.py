"""Evaluation score publisher.

Runs the deterministic harnesses on demand (or on schedule) and writes the
resulting scores to a JSON file. The v1 API exposes these scores via
``GET /api/v1/evaluations``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.self_improvement.benchmark_harness import run_bea_benchmark
from core.self_improvement.eval_harness import run_agent_harness


_DEFAULT_SCORE_FILE = Path("workspace") / "eval_scores.json"


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def publish_eval_scores(score_file: str | Path | None = None) -> dict[str, Any]:
    """Run agent + benchmark harnesses and persist scores.

    The benchmark harness uses a temporary workspace so it does not pollute
    the main workspace with benchmark artifacts.
    """
    workspace = Path(score_file).parent if score_file else _DEFAULT_SCORE_FILE.parent
    workspace.mkdir(parents=True, exist_ok=True)

    # Agent harness is fully deterministic and fast.
    agent_report = run_agent_harness().to_dict()

    # Component benchmark is treated as a new run, writing its own temporary files.
    benchmark_report = run_bea_benchmark().to_dict()

    payload = {
        "api_version": "1.0",
        "status": "ok",
        "agent_harness": agent_report,
        "benchmark": benchmark_report,
    }

    _atomic_write(Path(score_file) if score_file else _DEFAULT_SCORE_FILE, payload)
    return payload


def load_eval_scores(score_file: str | Path | None = None) -> dict[str, Any]:
    """Load the latest published scores (or a default placeholder)."""
    path = Path(score_file) if score_file else _DEFAULT_SCORE_FILE
    if not path.exists():
        return {
            "api_version": "1.0",
            "status": "not_run",
            "agent_harness": None,
            "benchmark": None,
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data.setdefault("api_version", "1.0")
        return data
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "api_version": "1.0",
            "status": f"load_error: {exc}",
            "agent_harness": None,
            "benchmark": None,
        }
