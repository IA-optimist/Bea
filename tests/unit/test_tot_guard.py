import sys; sys.path.insert(0, '/app' if __import__('os').path.exists('/app') else '.')
from core.cognition.tot_wrapper import should_use_tot

# Must NOT activate for short/simple tasks (< 100 chars)
assert not should_use_tot('Python: lire un CSV')
assert not should_use_tot('Explique Tree of Thought en 5 lignes')
assert not should_use_tot('What is 7 multiplied by 6')
assert not should_use_tot('architecture strategy')  # < 100 chars

# Must NOT activate for routing-tagged simple tasks
assert not should_use_tot('Build a system architecture [ROUTING:shape=plan,complexity=simple] details here extra content to reach 100 chars')

# SHOULD activate: long + keyword
assert should_use_tot('Design a comprehensive architecture for a distributed microservices system supporting 10M users with fault-tolerance and horizontal scaling')
assert should_use_tot('Build a roadmap strategy for migrating enterprise monolith to cloud-native microservices over 18 months with rollback plan for each phase')
assert should_use_tot('Design a system for large-scale autonomous agent orchestration supporting thousands of concurrent missions with causal planning and memory')

print('TOT GUARD: all tests passed')
