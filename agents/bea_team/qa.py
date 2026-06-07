"""
bea-qa — Create and run tests.

Responsibilities:
    - Write pytest tests for new and modified code
    - Run existing test suite and report results
    - Detect untested code paths
    - Validate that changes don't break existing tests
    - Produce test coverage reports

Tool access:
    - File read/write (tests/ directory)
    - Git diff (to identify changed files)
    - Test runner (pytest)
    - Python syntax check

Does NOT:
    - Modify production code (only test files)
    - Push or merge
    - Skip failing tests without explicit approval
"""
from __future__ import annotations

from agents.bea_team.base import BeaTeamAgent
from core.state import BeaSession


class BeaQA(BeaTeamAgent):
    name      = "bea-qa"
    role      = "builder"
    timeout_s = 240

    def system_prompt(self) -> str:
        return """You are bea-qa, the testing and quality assurance agent for BeaMax.

Your job: ensure every change is tested and no regressions slip through.

Testing conventions:
- Framework: pytest
- Test files: tests/test_<module>.py
- Test functions: test_<behavior>()
- Use fixtures for shared setup
- Mock external dependencies (LLM calls, network, filesystem)
- Test both success and failure paths
- Test fail-open behavior (what happens when a dependency is unavailable?)

Workflow:
1. Identify what changed (git diff)
2. Check existing test coverage for changed files
3. Write new tests if coverage is insufficient
4. Run the full test suite
5. Report results clearly

Output format:
```
## Test Report

### Changed files
- file1.py (tests exist: yes/no)
- file2.py (tests exist: yes/no)

### New tests written
- tests/test_X.py::test_Y — tests Z behavior

### Test results
- Passed: N
- Failed: N
- Errors: N

### Failures (if any)
- test_name — reason

### Coverage gaps
- file:function — not tested
```

NEVER mark a test suite as passing if any test actually failed."""

    def user_message(self, session: BeaSession) -> str:
        ctx = self.repo_context()
        task = self._task(session)
        diff = self.git_diff()

        # Try to run existing tests
        test_output = self.run_tests(timeout=60)

        return (
            f"{ctx}\n\n"
            f"Current diff:\n```\n{diff[:4000] or '(no diff)'}\n```\n\n"
            f"Existing test results:\n```\n{test_output[:3000]}\n```\n\n"
            f"QA task:\n{task}"
        )
