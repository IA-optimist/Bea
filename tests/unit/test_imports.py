import sys; sys.path.insert(0, '/app' if __import__('os').path.exists('/app') else '.')
from kernel.evaluation.scorer import KernelEvaluator, KernelScore, get_evaluator
from kernel.execution.contracts import ExecutionResult, ExecutionStatus
from core.cognition.self_confidence import ConfidenceScorer
from core.cognition.tot_wrapper import should_use_tot
from core.approval_queue import submit_for_approval, RiskLevel, AUTO_APPROVE_LEVELS
ks = KernelScore(score=0.5, passed=True)
assert ks.confidence == 0.7 and ks.verdict == 'accept'
assert 'DONE' in [s.value for s in ExecutionStatus]
print('IMPORT CHECK: all modules load correctly')
