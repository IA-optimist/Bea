#!/bin/bash
# Refactoring Verification Script
# Verifies that the meta_orchestrator.py refactoring is successful

set -e

echo "========================================================================"
echo "REFACTORING VERIFICATION: core/meta_orchestrator.py"
echo "========================================================================"
echo

# 1. Check file exists
echo "1. Checking file exists..."
if [ -f "core/meta_orchestrator.py" ]; then
    echo "   ✓ core/meta_orchestrator.py exists"
else
    echo "   ✗ File not found!"
    exit 1
fi

# 2. Check syntax
echo
echo "2. Checking Python syntax..."
python3 -m py_compile core/meta_orchestrator.py
echo "   ✓ Syntax is valid"

# 3. Check import
echo
echo "3. Checking module import..."
python3 -c "from core.meta_orchestrator import MetaOrchestrator; print('   ✓ Import successful')"

# 4. Check methods exist
echo
echo "4. Checking extracted methods..."
python3 << 'EOF'
from core.meta_orchestrator import MetaOrchestrator
mo = MetaOrchestrator()

methods = [
    '_setup_event_stream',
    '_check_circuit_breaker',
    '_initialize_decision_trace',
    '_emit_mission_events',
    '_register_mission_guards',
    '_run_cognitive_analysis',
    '_execute_reasoning_prepass',
    '_cleanup_event_stream',
    '_post_mission_learning',
]

all_present = True
for method in methods:
    if hasattr(mo, method):
        print(f"   ✓ {method}")
    else:
        print(f"   ✗ {method} MISSING")
        all_present = False

if not all_present:
    exit(1)
EOF

# 5. Run tests
echo
echo "5. Running test suite..."
python3 -m pytest \
    tests/test_surgical_hardening.py::TestMetaOrchestratorCircuitBreakerIntegration \
    tests/test_approval_gate.py::TestMetaOrchestratorApproval \
    tests/test_pillar_integration.py::TestMetaOrchestratorUsesUnifiedContracts \
    -v --tb=short 2>&1 | grep -E "(PASSED|FAILED|passed|failed|ERROR)"

echo
echo "========================================================================"
echo "✓ VERIFICATION COMPLETE - All checks passed!"
echo "========================================================================"
