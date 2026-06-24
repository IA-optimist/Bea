"""
Tests for the private-beta readiness gate script.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
GATE = REPO_ROOT / "scripts" / "private_beta_gate.py"


def _run_gate() -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GATE), "--json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def test_gate_exits_zero_in_beta_branch():
    result = _run_gate()
    assert result.returncode == 0, f"stderr: {result.stderr}"


def test_gate_reports_private_beta_ready():
    result = _run_gate()
    assert result.returncode == 0, f"stderr: {result.stderr}"
    data = json.loads(result.stdout)
    assert data["ready_for_private_beta"] is True
    assert data["ready_for_public_beta"] is False
    assert data["checks"]["self_improve_default"] is False
    assert data["checks"]["bea_skip_gate_default"] is False


def test_gate_has_no_secret_scan_blockers():
    result = _run_gate()
    assert result.returncode == 0
    data = json.loads(result.stdout)
    secret_blockers = [b for b in data["blockers"] if b["category"] == "secret_scan"]
    assert secret_blockers == []


def test_gate_has_no_dangerous_claim_blockers():
    result = _run_gate()
    assert result.returncode == 0
    data = json.loads(result.stdout)
    claim_blockers = [b for b in data["blockers"] if b["category"] == "dangerous_claim"]
    assert claim_blockers == []
