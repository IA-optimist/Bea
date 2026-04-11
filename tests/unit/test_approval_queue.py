import sys; sys.path.insert(0, '/app' if __import__('os').path.exists('/app') else '.')
from core.approval_queue import submit_for_approval, RiskLevel, AUTO_APPROVE_LEVELS
assert RiskLevel.WRITE_LOW in AUTO_APPROVE_LEVELS
assert RiskLevel.READ in AUTO_APPROVE_LEVELS
r = submit_for_approval('Test', RiskLevel.WRITE_LOW, 'test', 'none', 'none', 'ci', {})
assert r['approved'] is True and r.get('auto') is True and r.get('pending') is False
print('APPROVAL QUEUE: all tests passed')
