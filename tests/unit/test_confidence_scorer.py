import sys; sys.path.insert(0, '/app' if __import__('os').path.exists('/app') else '.')
from core.cognition.self_confidence import ConfidenceScorer
class FakeLLM:
    def invoke(self, m):
        class R: content = 'CONFIDENCE: 0.8\nREASONING: Good\nISSUES: none\nRETRY: false'
        return R()
r = ConfidenceScorer(FakeLLM()).score_output('Task', 'Detailed response.', None)
assert 0 <= r['confidence'] <= 1 and 'should_retry' in r
class NoopLLM: pass
r2 = ConfidenceScorer(NoopLLM()).score_output('Task', 'Output', None)
assert r2['confidence'] == 0.6 and r2['should_retry'] is False
print('CONFIDENCE SCORER: all tests passed')
