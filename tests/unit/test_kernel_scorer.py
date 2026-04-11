import sys; sys.path.insert(0, '/app' if __import__('os').path.exists('/app') else '.')
from kernel.evaluation.scorer import get_evaluator
ev = get_evaluator()
s = ev.evaluate('Test goal', '', 'direct_answer', 'ci-001')
assert s.score == 0.0 and s.retry_recommended
s2 = ev.evaluate('Explain python', 'Python is a high-level language. It supports OOP and is widely used for data science and AI.', 'direct_answer', 'ci-002')
assert s2.score > 0.4
s3 = ev.evaluate('Write python function', 'def hello():\n    import os\n    return os.getcwd()', 'implementation', 'ci-003')
assert 'code_present' in s3.signals
d = s2.to_dict()
for k in ('score', 'passed', 'confidence', 'retry_recommended', 'verdict', 'weaknesses'):
    assert k in d
print('KERNEL SCORER: all tests passed')
