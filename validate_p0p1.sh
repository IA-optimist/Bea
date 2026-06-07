#!/bin/bash
echo "=========================================="
echo "P0/P1 Bug Fixes Validation"
echo "=========================================="
echo ""

# Test 1: Python compilation
echo "1. Testing Python compilation..."
python3 -m py_compile \
  core/orchestration/bea_team_dispatcher.py \
  core/meta_orchestrator.py \
  core/cognition/orchestrator.py \
  api/routes/vault.py 2>&1
if [ $? -eq 0 ]; then
  echo "   ✓ All files compile successfully"
else
  echo "   ✗ Compilation errors found"
  exit 1
fi
echo ""

# Test 2: Run validation suite
echo "2. Running validation test suite..."
python3 tests/test_p0p1_fixes.py
if [ $? -eq 0 ]; then
  echo "   ✓ All tests passed"
else
  echo "   ✗ Some tests failed"
  exit 1
fi
echo ""

# Test 3: Check git commits
echo "3. Checking git commits..."
git log --oneline -2 | grep -q "P0/P1"
if [ $? -eq 0 ]; then
  echo "   ✓ P0/P1 commits present"
  git log --oneline -2 | grep "P0/P1"
else
  echo "   ✗ P0/P1 commits not found"
  exit 1
fi
echo ""

echo "=========================================="
echo "✅ ALL VALIDATIONS PASSED"
echo "=========================================="
echo ""
echo "Summary:"
echo "  • Python files compile: ✓"
echo "  • Test suite passes: ✓"
echo "  • Git commits present: ✓"
echo "  • Ready for deployment: ✓"
