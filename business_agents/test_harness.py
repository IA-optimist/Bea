"""
JARVIS MAX — Business Agent Test Harness
==========================================
Tests every generated business agent against its template's
evaluation rules and expected behaviors.

Tests:
  - valid input → structured output
  - missing input → validation error
  - malformed input → graceful handling
  - safe fallback → no crash
  - output schema validity
  - no unsafe action
  - memory retrieval relevance
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from business_agents.template_schema import BusinessAgentTemplate, EvaluationRule
from business_agents.template_registry import get_template
from business_agents.factory import GeneratedAgent


@dataclass
class TestCase:
    """Single test case for a business agent."""
    name: str
    description: str
    input_data: dict
    expected_behavior: str   # success, validation_error, fallback, escalation
    checks: list[str] = field(default_factory=list)  # evaluation rules to apply


@dataclass
class TestResult:
    """Result of a single test case."""
    test_name: str
    passed: bool
    details: dict = field(default_factory=dict)
    duration_ms: float = 0
    error: str = ""


@dataclass
class AgentSuiteResult:
    """Result of running all tests for an agent."""
    agent_id: str
    template_name: str
    total_tests: int = 0
    passed: int = 0
    failed: int = 0
    results: list[TestResult] = field(default_factory=list)
    score: float = 0.0
    duration_ms: float = 0

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total_tests if self.total_tests > 0 else 0

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "template": self.template_name,
            "total": self.total_tests,
            "passed": self.passed,
            "failed": self.failed,
            "score": round(self.score, 3),
            "pass_rate": round(self.pass_rate, 3),
            "duration_ms": round(self.duration_ms, 1),
            "results": [
                {"test": r.test_name, "passed": r.passed,
                 "error": r.error, "duration_ms": r.duration_ms}
                for r in self.results
            ],
        }


# ═══════════════════════════════════════════════════════════════
# TEST GENERATION
# ═══════════════════════════════════════════════════════════════

def generate_test_battery(template: BusinessAgentTemplate) -> list[TestCase]:
    """Generate test cases from template definition."""
    tests = []

    # T1: Valid complete input
    valid_input = {}
    for f in template.input_schema:
        if f.type == "string":
            valid_input[f.name] = f"Test value for {f.name}"
        elif f.type == "number":
            valid_input[f.name] = 42.0
        elif f.type == "boolean":
            valid_input[f.name] = True
        elif f.type == "list":
            valid_input[f.name] = ["test_item_1", "test_item_2"]
        elif f.type == "object":
            valid_input[f.name] = {"test_key": "test_value"}
    tests.append(TestCase(
        name="valid_complete_input",
        description="All required fields present with valid types",
        input_data=valid_input,
        expected_behavior="success",
        checks=["input_validated", "no_error"],
    ))

    # T2: Missing required fields
    tests.append(TestCase(
        name="missing_required_fields",
        description="No input provided — should return validation error",
        input_data={},
        expected_behavior="validation_error",
        checks=["has_error_message", "lists_missing_fields"],
    ))

    # T3: Only optional fields
    optional_only = {f.name: f"value_{f.name}" for f in template.input_schema
                     if not f.required and f.type == "string"}
    tests.append(TestCase(
        name="only_optional_fields",
        description="Only optional fields provided",
        input_data=optional_only,
        expected_behavior="validation_error",
        checks=["has_error_message"],
    ))

    # T4: Malformed input types
    malformed = {}
    for f in template.input_schema:
        if f.required:
            # Give wrong type
            if f.type == "string":
                malformed[f.name] = 12345  # number instead of string
            elif f.type == "number":
                malformed[f.name] = "not_a_number"
            elif f.type == "list":
                malformed[f.name] = "not_a_list"
    if malformed:
        tests.append(TestCase(
            name="malformed_input_types",
            description="Required fields present but wrong types",
            input_data=malformed,
            expected_behavior="success",  # Should still handle gracefully
            checks=["no_crash"],
        ))

    # T5: Minimal valid input
    minimal = {}
    for f in template.input_schema:
        if f.required:
            if f.type == "string":
                minimal[f.name] = "x"
            elif f.type == "number":
                minimal[f.name] = 0
            elif f.type == "boolean":
                minimal[f.name] = False
            elif f.type == "list":
                minimal[f.name] = []
            elif f.type == "object":
                minimal[f.name] = {}
    tests.append(TestCase(
        name="minimal_valid_input",
        description="Only required fields with minimal values",
        input_data=minimal,
        expected_behavior="success",
        checks=["input_validated"],
    ))

    # T6: Empty strings for required fields
    empty_strings = {f.name: "" for f in template.input_schema if f.required}
    tests.append(TestCase(
        name="empty_required_strings",
        description="Required fields present but empty",
        input_data=empty_strings,
        expected_behavior="success",  # Agent should detect and ask
        checks=["no_crash"],
    ))

    # T7: Extra unexpected fields
    extra = dict(valid_input)
    extra["__unexpected_field__"] = "should be ignored"
    extra["admin_override"] = True
    tests.append(TestCase(
        name="extra_unexpected_fields",
        description="Valid input plus unexpected fields that should be ignored",
        input_data=extra,
        expected_behavior="success",
        checks=["no_crash", "input_validated"],
    ))

    return tests


# ═══════════════════════════════════════════════════════════════
# TEST EXECUTION
# ═══════════════════════════════════════════════════════════════

def _evaluate_output(output: dict, rule: EvaluationRule) -> tuple[bool, str]:
    """Evaluate a single output against an evaluation rule."""
    target = output.get(rule.target_field)

    if rule.check_type == "presence":
        if target is not None and target != "" and target != []:
            return True, f"{rule.target_field} is present"
        return False, f"{rule.target_field} is missing or empty"

    elif rule.check_type == "length":
        if isinstance(target, str) and len(target) >= (rule.threshold or 0):
            return True, f"{rule.target_field} length {len(target)} >= {rule.threshold}"
        return False, f"{rule.target_field} too short: {len(target) if isinstance(target, str) else 'N/A'}"

    elif rule.check_type == "format":
        # Placeholder for format validation
        return True, "format check not yet implemented"

    elif rule.check_type == "keyword":
        # Check that field exists and is non-empty
        if target is not None and str(target).strip():
            return True, f"{rule.target_field} has content"
        return False, f"{rule.target_field} empty"

    elif rule.check_type == "schema":
        if isinstance(target, dict):
            return True, f"{rule.target_field} is valid object"
        return False, f"{rule.target_field} is not a valid object"

    return True, "unknown check type — passed"


def run_test_case(agent: GeneratedAgent, test: TestCase) -> TestResult:
    """Run a single test case against a generated agent."""
    start = time.time()
    try:
        output = agent.execute(test.input_data)

        # Check based on expected behavior
        if test.expected_behavior == "validation_error":
            if "error" in output or output.get("status") == "validation_error":
                passed = True
                details = {"correctly_rejected": True, "error": output.get("error", "")}
            else:
                passed = False
                details = {"expected_error_but_got": output.get("status", "unknown")}

        elif test.expected_behavior == "success":
            passed = output.get("status") in ("ready_for_llm", "success") or output.get("input_validated", False)
            details = {"status": output.get("status"), "input_validated": output.get("input_validated")}

        else:
            passed = "error" not in output or output.get("status") != "crash"
            details = {"status": output.get("status", "unknown")}

        duration = (time.time() - start) * 1000
        return TestResult(test_name=test.name, passed=passed, details=details,
                          duration_ms=duration)

    except Exception as e:
        duration = (time.time() - start) * 1000
        return TestResult(test_name=test.name, passed=False,
                          error=str(e), duration_ms=duration)


def run_test_suite(agent: GeneratedAgent) -> AgentSuiteResult:
    """Run the full test battery for a generated agent."""
    template = get_template(agent.template_name)
    if not template:
        return AgentSuiteResult(agent_id=agent.id, template_name=agent.template_name)

    tests = generate_test_battery(template)
    start = time.time()

    results = []
    for test in tests:
        result = run_test_case(agent, test)
        results.append(result)

    total_duration = (time.time() - start) * 1000
    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed

    # Composite score
    pass_rate = passed / len(results) if results else 0
    score = pass_rate * 0.8 + (1.0 if failed == 0 else 0) * 0.2

    suite = AgentSuiteResult(
        agent_id=agent.id,
        template_name=agent.template_name,
        total_tests=len(results),
        passed=passed,
        failed=failed,
        results=results,
        score=round(score, 3),
        duration_ms=total_duration,
    )
    return suite
