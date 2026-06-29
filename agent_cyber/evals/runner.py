from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from agent_cyber.evals.models import (
    CandidateFinding,
    CyberEvalAgentOutput,
    CyberEvalScore,
    CyberEvalTask,
)
from agent_cyber.evals.scorer import CyberEvalScorer

_FIXTURES_DIR = Path(__file__).parent / "fixtures"


class CyberEvalRunner:
    """Loads tasks from YAML fixtures and scores them."""

    def __init__(self) -> None:
        self._scorer = CyberEvalScorer()

    def load_task(self, fixture_path: Path) -> CyberEvalTask:
        with open(fixture_path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return CyberEvalTask(**data)

    def load_all_fixtures(self) -> list[CyberEvalTask]:
        tasks: list[CyberEvalTask] = []
        for path in sorted(_FIXTURES_DIR.glob("*.yaml")):
            tasks.append(self.load_task(path))
        return tasks

    def run_fixture(self, task: CyberEvalTask) -> CyberEvalAgentOutput:
        """
        v1: simulates a minimal agent output from the task definition.
        Returns an output claiming the expected class at expected locations.
        Used for harness integration tests — real agent output comes in v2.
        """
        candidates = [
            CandidateFinding(
                vuln_class=task.expected_vuln_class,
                confidence=0.85,
                locations=task.expected_locations[:1],
                reason=f"Static analysis detected {task.expected_vuln_class} pattern",
                evidence_refs=["simulated-evidence-001"],
                remediation=f"Remediate {task.expected_vuln_class} pattern following OWASP guidance",
            )
        ] if task.expected_vulnerable else []

        return CyberEvalAgentOutput(
            task_id=task.task_id,
            vulnerable=task.expected_vulnerable,
            confidence=0.85,
            candidates=candidates,
        )

    def run_all(
        self,
        tasks: Optional[list[CyberEvalTask]] = None,
    ) -> list[tuple[CyberEvalTask, CyberEvalAgentOutput, CyberEvalScore]]:
        if tasks is None:
            tasks = self.load_all_fixtures()
        results = []
        for task in tasks:
            output = self.run_fixture(task)
            score = self._scorer.score(task, output)
            results.append((task, output, score))
        return results
