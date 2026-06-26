from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_docs_truth_gate_passes() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check_docs_truth.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stdout + result.stderr
