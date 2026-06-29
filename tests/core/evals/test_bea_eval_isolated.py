"""Tests for bea_eval --isolated flag.

These tests verify that --isolated mode:
- exits zero
- returns valid JSON with required fields
- does not pollute the global store (same results across two runs)
- reports zero failures
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
VENV_PYTHON = sys.executable


def _run_bea_eval(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [VENV_PYTHON, str(ROOT / "scripts" / "bea_eval.py"), "--json", "--isolated", *args],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        timeout=120,
    )


def test_isolated_exits_zero() -> None:
    r = _run_bea_eval()
    assert r.returncode == 0, f"Exit {r.returncode}\nstdout: {r.stdout[:300]}\nstderr: {r.stderr[:300]}"


def test_isolated_json_structure() -> None:
    r = _run_bea_eval()
    assert r.returncode == 0, f"Exit {r.returncode}: {r.stderr[:500]}"
    data = json.loads(r.stdout)
    assert "summary" in data, f"Missing 'summary' key: {list(data.keys())}"
    # overall_score lives inside summary (not top-level)
    assert "overall_score" in data["summary"], "Missing 'summary.overall_score'"
    assert "total" in data["summary"]
    assert "passed" in data["summary"]
    assert "failed" in data["summary"]


def test_isolated_does_not_pollute_global_store() -> None:
    """Running twice in isolated mode must give identical scores."""
    r1 = _run_bea_eval()
    r2 = _run_bea_eval()
    assert r1.returncode == 0, f"Run 1 failed: {r1.stderr[:300]}"
    assert r2.returncode == 0, f"Run 2 failed: {r2.stderr[:300]}"
    d1 = json.loads(r1.stdout)
    d2 = json.loads(r2.stdout)
    assert d1["summary"]["total"] == d2["summary"]["total"], (
        f"Store pollution detected: total {d1['summary']['total']} != {d2['summary']['total']}"
    )
    assert d1["summary"]["passed"] == d2["summary"]["passed"], (
        f"Store pollution detected: passed {d1['summary']['passed']} != {d2['summary']['passed']}"
    )


def test_isolated_failed_zero() -> None:
    r = _run_bea_eval()
    assert r.returncode == 0, f"Exit {r.returncode}: {r.stderr[:500]}"
    data = json.loads(r.stdout)
    failed = data["summary"]["failed"]
    assert failed == 0, (
        f"Expected 0 failures, got {failed}.\n"
        + "\n".join(
            f"  FAIL {res['eval_name']}: {res.get('error', '')}"
            for res in data.get("results", [])
            if not res.get("success")
        )
    )
