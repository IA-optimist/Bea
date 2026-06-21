"""bea eval — evaluation harness for memory-first agent coder."""
from core.evals.bea_eval import BeaEval, run_and_report, run_evals
from core.evals.models import EvalReport, EvalResult
from core.evals.report import generate_markdown

__all__ = ["BeaEval", "EvalReport", "EvalResult", "run_evals", "run_and_report", "generate_markdown"]
