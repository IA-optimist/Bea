from __future__ import annotations

from pathlib import Path


def test_pr_smoke_workflow_contains_expected_commands():
    workflow = Path(".github/workflows/pr-smoke.yml").read_text(encoding="utf-8")

    assert "pull_request:" in workflow
    assert "push:" in workflow
    assert "branches: [main]" in workflow
    assert "ruff check ." in workflow
    assert "python scripts/bea_eval.py --json" in workflow
    assert "python scripts/smoke_e2e_cycle.py --fixture sha256 --skip-bea-eval --json" in workflow
    assert "python scripts/validate_local.py --quick" in workflow
    assert "OPENROUTER_API_KEY" not in workflow
    assert "ollama" not in workflow.lower()
