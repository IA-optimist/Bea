"""Markdown report generation for bea eval runs."""
from __future__ import annotations

import time
from typing import Any

from core.evals.models import EvalReport


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def _families(report: EvalReport) -> dict[str, dict[str, Any]]:
    """Group results by eval name prefix (family)."""
    families: dict[str, dict[str, Any]] = {}
    for r in report.results:
        family = r.eval_name.split("-")[0] if "-" in r.eval_name else "other"
        if family not in families:
            families[family] = {"total": 0, "passed": 0, "failed": 0, "score": 0.0}
        families[family]["total"] += 1
        families[family]["score"] += r.score
        if r.success:
            families[family]["passed"] += 1
        else:
            families[family]["failed"] += 1
    return families


def generate_markdown(report: EvalReport) -> str:
    """Convert an EvalReport into a readable Markdown summary."""
    total = len(report.results)
    passed = sum(1 for r in report.results if r.success)
    failed = total - passed
    overall = report.overall_score()
    families = _families(report)

    lines: list[str] = [
        "# Bea Eval Report",
        "",
        f"- **Run ID**: `{report.run_id}`",
        f"- **Generated**: {_now()}",
        f"- **Evaluations**: {total}",
        f"- **Passed**: {passed}",
        f"- **Failed**: {failed}",
        f"- **Overall score**: {overall:.2f}",
        "",
        "## Results",
        "",
        "| Eval | Status | Score | Duration | Model class |",
        "|------|--------|-------|----------|-------------|",
    ]

    for r in report.results:
        status = "PASS" if r.success else "FAIL"
        model = r.model_class_selected or "-"
        lines.append(f"| {r.eval_name} | {status} | {r.score:.2f} | {r.duration_ms}ms | {model} |")

    lines.extend(["", "## Score by family", ""])
    for family, stats in sorted(families.items()):
        avg = stats["score"] / max(stats["total"], 1)
        lines.append(
            f"- **{family}**: {stats['passed']}/{stats['total']} passed, avg score {avg:.2f}"
        )

    failing = [r for r in report.results if not r.success]
    if failing:
        lines.extend(["", "## Failing evals", ""])
        for r in failing:
            lines.append(f"- `{r.eval_name}`: {r.error or 'no error message'}")
    else:
        lines.extend(["", "## Failing evals", "", "All evals passed."])

    lines.extend(["", "## Recommendations", ""])
    worst_family: str | None = None
    worst_avg = 1.0
    for family, stats in families.items():
        avg = stats["score"] / max(stats["total"], 1)
        if avg < worst_avg:
            worst_avg = avg
            worst_family = family
    if worst_family and worst_avg < 0.8:
        lines.append(
            f"- Family `{worst_family}` has the lowest average score ({worst_avg:.2f}). "
            "Consider adding more memory seeds or improving retrieval ranking."
        )
    if any(r.model_class_selected == "STRONG_CODE_REVIEW" and r.success for r in report.results):
        lines.append(
            "- Protected-file / security routing is active. Keep verifying these paths with human review."
        )
    if failed == 0:
        lines.append("- Suite is green. Good baseline for active-memory model router.")

    return "\n".join(lines) + "\n"
