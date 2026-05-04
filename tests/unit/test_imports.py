import sys; sys.path.insert(0, '/app' if __import__('os').path.exists('/app') else '.')
from kernel.evaluation.scorer import KernelScore
from kernel.execution.contracts import ExecutionStatus
ks = KernelScore(score=0.5, passed=True)
assert ks.confidence == 0.7 and ks.verdict == 'accept'
assert 'DONE' in [s.value for s in ExecutionStatus]
print('IMPORT CHECK: all modules load correctly')
