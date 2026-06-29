from __future__ import annotations

from agent_cyber.evals.models import (
    CyberEvalAgentOutput,
    CyberEvalScore,
    CyberEvalTask,
)

_VERDICT_PTS = 40.0
_CLASS_PTS = 25.0
_LOC_FILE_PTS = 15.0
_LOC_FUNC_PTS = 10.0
_EVIDENCE_PTS = 5.0
_REMEDIATION_PTS = 5.0


class CyberEvalScorer:
    def score(
        self,
        task: CyberEvalTask,
        output: CyberEvalAgentOutput,
    ) -> CyberEvalScore:
        verdict_correct = output.vulnerable == task.expected_vulnerable
        verdict_score = 1.0 if verdict_correct else 0.0

        # If verdict wrong, cap total at 10pts (partial credit only)
        max_total = 100.0 if verdict_correct else 10.0

        # Class score
        best_class_match = any(
            c.vuln_class == task.expected_vuln_class for c in output.candidates
        )
        class_score = 1.0 if best_class_match else 0.0

        # Location score — check file and function matches
        expected_files = {loc.get("file") for loc in task.expected_locations if loc.get("file")}
        expected_funcs = {loc.get("function") for loc in task.expected_locations if loc.get("function")}
        candidate_files: set[str] = set()
        candidate_funcs: set[str] = set()
        for c in output.candidates:
            for loc in c.locations:
                if loc.get("file"):
                    candidate_files.add(loc["file"])
                if loc.get("function"):
                    candidate_funcs.add(loc["function"])

        file_match = bool(expected_files & candidate_files) if expected_files else True
        func_match = bool(expected_funcs & candidate_funcs) if expected_funcs else False
        raw_loc = (
            (_LOC_FILE_PTS if file_match else 0.0) +
            (_LOC_FUNC_PTS if func_match else 0.0)
        ) / (_LOC_FILE_PTS + _LOC_FUNC_PTS)
        location_score = min(raw_loc, 1.0)

        # Evidence score
        has_evidence = any(c.evidence_refs for c in output.candidates)
        evidence_score = 1.0 if has_evidence else 0.0

        # Remediation score
        has_remediation = any(c.remediation for c in output.candidates)
        remediation_score = 1.0 if has_remediation else 0.0

        # Total
        raw_total = (
            verdict_score * _VERDICT_PTS +
            class_score * _CLASS_PTS +
            location_score * (_LOC_FILE_PTS + _LOC_FUNC_PTS) +
            evidence_score * _EVIDENCE_PTS +
            remediation_score * _REMEDIATION_PTS
        )
        total_score = min(raw_total, max_total)

        return CyberEvalScore(
            task_id=task.task_id,
            verdict_score=verdict_score,
            class_score=class_score,
            location_score=location_score,
            evidence_score=evidence_score,
            remediation_score=remediation_score,
            total_score=total_score,
        )
