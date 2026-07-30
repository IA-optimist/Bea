"""
core/evaluation/model_role_benchmark.py — Benchmark fixtures and scoring for agent roles.

Provides reproducible tasks for forge-builder, scout-research and shadow-advisor,
plus a scoring function that turns raw benchmark observations into comparable
scores without depending on a live LLM in the default path.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable


class AgentRole(str, Enum):
    """Agent roles that can be benchmarked for model selection."""

    FORGE_BUILDER = "forge-builder"
    SCOUT_RESEARCH = "scout-research"
    SHADOW_ADVISOR = "shadow-advisor"


class ErrorCategory(str, Enum):
    """High-level failure categories returned by benchmark runs."""

    NONE = "none"
    TIMEOUT = "timeout"
    JSON_INVALID = "json_invalid"
    SYNTAX_ERROR = "syntax_error"
    ARTIFACT_MISSING = "artifact_missing"
    ARTIFACT_INVALID = "artifact_invalid"
    HALLUCINATION = "hallucination"
    SCHEMA_MISMATCH = "schemaMismatch"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


@dataclass
class BenchmarkFixture:
    """A single reproducible benchmark task for one agent role."""

    role: AgentRole
    mission_type: str
    name: str
    prompt: str
    timeout: float
    expected_output_contract: dict[str, Any]
    success_criteria: list[str]
    validation_inputs: dict[str, Any] = field(default_factory=dict)


@dataclass
class BenchmarkRawResult:
    """Observations collected while running a fixture."""

    role: AgentRole
    fixture_name: str
    provider_used: str
    model_used: str
    fallback_used: bool
    success: bool
    duration_s: float
    timeout: bool
    error_category: ErrorCategory
    artifact_text: str
    artifact_path: str | None
    json_valid: bool | None
    schema_ok: bool | None
    syntax_ok: bool | None
    test_passed: bool | None
    retry_count: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BenchmarkResult:
    """Final scored benchmark result."""

    role: AgentRole
    fixture_name: str
    provider_used: str
    model_used: str
    fallback_used: bool
    success: bool
    duration_s: float
    timeout: bool
    error_category: ErrorCategory
    artifact_ok: bool | None
    json_valid: bool | None
    schema_ok: bool | None
    syntax_ok: bool | None
    test_passed: bool | None
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role.value,
            "fixture_name": self.fixture_name,
            "provider_used": self.provider_used,
            "model_used": self.model_used,
            "fallback_used": self.fallback_used,
            "success": self.success,
            "duration_s": round(self.duration_s, 3),
            "timeout": self.timeout,
            "error_category": self.error_category.value,
            "artifact_ok": self.artifact_ok,
            "json_valid": self.json_valid,
            "schema_ok": self.schema_ok,
            "syntax_ok": self.syntax_ok,
            "test_passed": self.test_passed,
            "score": round(self.score, 3),
        }


# ── Fixtures ────────────────────────────────────────────────────────────────


def _fixtures() -> list[BenchmarkFixture]:
    return [
        BenchmarkFixture(
            role=AgentRole.FORGE_BUILDER,
            mission_type="coding_agent",
            name="sha256_file",
            prompt=(
                "Create a Python module with a function sha256_file(path: str) -> str "
                "that reads a file in 8192-byte chunks and returns its SHA-256 hex digest. "
                "Also create a pytest test that hashes a temporary file and checks the result. "
                "Return only the code; do not wrap it in Markdown fences."
            ),
            timeout=60.0,
            expected_output_contract={
                "files": ["src/sha256_file.py", "tests/test_sha256_file.py"],
                "test_command": "python -m pytest tests/test_sha256_file.py -q",
                "format": "plain_python",
            },
            success_criteria=[
                "artifact_text contains 'def sha256_file'",
                "no markdown fences in artifact_text",
                "syntax check passes",
                "test check passes",
            ],
            validation_inputs={"expected_function": "sha256_file"},
        ),
        BenchmarkFixture(
            role=AgentRole.SCOUT_RESEARCH,
            mission_type="research",
            name="alpha_risks",
            prompt=(
                "Read docs/ALPHA_READINESS.md and produce a concise structured analysis of the "
                "remaining alpha risks. Output as bullet points grouped by severity: BLOCKING, "
                "DEGRADING, INFORMATIVE. Keep under 300 words."
            ),
            timeout=45.0,
            expected_output_contract={
                "format": "structured_text",
                "sections": ["BLOCKING", "DEGRADING", "INFORMATIVE"],
                "max_words": 300,
            },
            success_criteria=[
                "response contains BLOCKING section",
                "response contains DEGRADING section",
                "response contains INFORMATIVE section",
                "no obvious hallucinated facts",
            ],
            validation_inputs={"source_file": "docs/ALPHA_READINESS.md"},
        ),
        BenchmarkFixture(
            role=AgentRole.SHADOW_ADVISOR,
            mission_type="advisor",
            name="alpha_advice_json",
            prompt=(
                "Return **only** a JSON object with exactly these keys and no Markdown: "
                "risk_level (low|medium|high|critical), blockers (list of strings), "
                "recommended_next_action (string)."
            ),
            timeout=30.0,
            expected_output_contract={
                "format": "json",
                "required_keys": ["risk_level", "blockers", "recommended_next_action"],
                "risk_level_enum": ["low", "medium", "high", "critical"],
            },
            success_criteria=[
                "output is valid JSON",
                "required keys present",
                "risk_level is valid enum value",
            ],
            validation_inputs={},
        ),
    ]


FIXTURES: list[BenchmarkFixture] = _fixtures()


def get_fixtures(role: AgentRole | None = None) -> list[BenchmarkFixture]:
    """Return all fixtures, optionally filtered by role."""
    if role is None:
        return list(FIXTURES)
    return [f for f in FIXTURES if f.role == role]


# ── Validation helpers ───────────────────────────────────────────────────────


def _strip_markdown_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[\w]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


def _check_syntax(code: str) -> bool:
    try:
        compile(code, "<benchmark>", "exec")
        return True
    except SyntaxError:
        return False


def _check_json(text: str) -> tuple[bool, Any]:
    try:
        return True, json.loads(text)
    except json.JSONDecodeError:
        return False, None


def _has_markdown_fences(text: str) -> bool:
    return "```" in text


def _score_forge_builder(raw: BenchmarkRawResult) -> tuple[bool, float]:
    """Score forge-builder on artifact validity, syntax and tests."""
    code = _strip_markdown_fences(raw.artifact_text)
    has_function = bool(re.search(r"def\s+sha256_file\s*\(", code))
    no_fences = not _has_markdown_fences(raw.artifact_text)
    syntax_ok = _check_syntax(code) if has_function else False
    test_passed = raw.test_passed if raw.test_passed is not None else False

    if raw.timeout:
        return False, 0.15
    if raw.error_category == ErrorCategory.ARTIFACT_MISSING:
        return False, 0.0

    score = 0.0
    if has_function:
        score += 0.2
    if no_fences:
        score += 0.2
    if syntax_ok:
        score += 0.3
    if test_passed:
        score += 0.3

    success = syntax_ok and test_passed and no_fences and has_function
    return success, round(score, 3)


def _score_scout_research(raw: BenchmarkRawResult, fixture: BenchmarkFixture) -> tuple[bool, float]:
    """Score scout-research on structure, length and plausibility."""
    text = raw.artifact_text
    required_sections = fixture.expected_output_contract.get("sections", [])
    max_words = fixture.expected_output_contract.get("max_words", 1000)
    word_count = len(text.split())

    sections_ok = all(section in text for section in required_sections)
    length_ok = 0 < word_count <= max_words
    # Simple hallucination guard: must reference words from the source file if available
    source_file = fixture.validation_inputs.get("source_file")
    source_ok = True
    if source_file and Path(source_file).exists():
        source_text = Path(source_file).read_text(encoding="utf-8").lower()
        # Require at least a few words from source to appear in response
        source_tokens = set(re.findall(r"\b[a-z]{5,}\b", source_text))
        response_lower = text.lower()
        overlap = sum(1 for token in source_tokens if token in response_lower)
        source_ok = overlap >= 3

    if raw.timeout:
        return False, 0.2

    score = 0.0
    if sections_ok:
        score += 0.4
    if length_ok:
        score += 0.3
    if source_ok:
        score += 0.3

    success = sections_ok and length_ok and source_ok
    return success, round(score, 3)


def _score_shadow_advisor(raw: BenchmarkRawResult, fixture: BenchmarkFixture) -> tuple[bool, float]:
    """Score shadow-advisor on JSON validity and schema compliance."""
    text = _strip_markdown_fences(raw.artifact_text)
    json_valid, parsed = _check_json(text)
    required_keys = fixture.expected_output_contract.get("required_keys", [])
    schema_ok = False
    if json_valid and isinstance(parsed, dict):
        schema_ok = all(k in parsed for k in required_keys)
        risk_levels = fixture.expected_output_contract.get("risk_level_enum", [])
        if schema_ok and risk_levels:
            schema_ok = parsed.get("risk_level") in risk_levels

    if raw.timeout:
        return False, 0.2
    if raw.error_category == ErrorCategory.JSON_INVALID:
        return False, 0.0

    score = 0.0
    if json_valid:
        score += 0.5
    if schema_ok:
        score += 0.5

    success = json_valid and schema_ok
    return success, round(score, 3)


SCORERS: dict[AgentRole, Callable[[BenchmarkRawResult, BenchmarkFixture], tuple[bool, float]]] = {
    AgentRole.FORGE_BUILDER: lambda raw, _: _score_forge_builder(raw),
    AgentRole.SCOUT_RESEARCH: _score_scout_research,
    AgentRole.SHADOW_ADVISOR: _score_shadow_advisor,
}


def score_result(raw: BenchmarkRawResult, fixture: BenchmarkFixture) -> BenchmarkResult:
    """Compute final BenchmarkResult from raw observations."""
    scorer = SCORERS.get(fixture.role, lambda raw, _: (raw.success, 0.0))
    success, score = scorer(raw, fixture)
    return BenchmarkResult(
        role=fixture.role,
        fixture_name=fixture.name,
        provider_used=raw.provider_used,
        model_used=raw.model_used,
        fallback_used=raw.fallback_used,
        success=success,
        duration_s=raw.duration_s,
        timeout=raw.timeout,
        error_category=raw.error_category,
        artifact_ok=raw.artifact_path is not None or bool(raw.artifact_text),
        json_valid=raw.json_valid,
        schema_ok=raw.schema_ok,
        syntax_ok=raw.syntax_ok,
        test_passed=raw.test_passed,
        score=score,
    )


# ── Mock runner (deterministic, no LLM required) ─────────────────────────────


def _mock_artifact(fixture: BenchmarkFixture) -> str:
    """Return a deterministic mock response for a fixture."""
    if fixture.role == AgentRole.FORGE_BUILDER:
        return (
            "import hashlib\n"
            "def sha256_file(path: str) -> str:\n"
            "    h = hashlib.sha256()\n"
            "    with open(path, 'rb') as f:\n"
            "        for chunk in iter(lambda: f.read(8192), b''):\n"
            "            h.update(chunk)\n"
            "    return h.hexdigest()\n"
        )
    if fixture.role == AgentRole.SCOUT_RESEARCH:
        return (
            "BLOCKING\n- APK not redeloyed\n\n"
            "DEGRADING\n- v1 endpoints still present\n\n"
            "INFORMATIVE\n- PRODUCTION_READINESS.md dated 2026-04-11\n"
        )
    if fixture.role == AgentRole.SHADOW_ADVISOR:
        return json.dumps({
            "risk_level": "medium",
            "blockers": ["APK rebuild", "provider health check"],
            "recommended_next_action": "Run provider_healthcheck.py",
        })
    return ""


def run_fixture_mock(fixture: BenchmarkFixture) -> BenchmarkResult:
    """Run a fixture using deterministic mock output."""
    artifact = _mock_artifact(fixture)
    raw = BenchmarkRawResult(
        role=fixture.role,
        fixture_name=fixture.name,
        provider_used="mock",
        model_used="mock",
        fallback_used=False,
        success=True,
        duration_s=0.1,
        timeout=False,
        error_category=ErrorCategory.NONE,
        artifact_text=artifact,
        artifact_path=None,
        json_valid=None,
        schema_ok=None,
        syntax_ok=None,
        test_passed=None,
        retry_count=0,
    )
    if fixture.role == AgentRole.FORGE_BUILDER:
        code = _strip_markdown_fences(artifact)
        raw.syntax_ok = _check_syntax(code)
        raw.test_passed = raw.syntax_ok
    elif fixture.role == AgentRole.SCOUT_RESEARCH:
        raw.json_valid = False
        raw.schema_ok = False
    elif fixture.role == AgentRole.SHADOW_ADVISOR:
        ok, parsed = _check_json(artifact)
        raw.json_valid = ok
        raw.schema_ok = ok and all(k in parsed for k in fixture.expected_output_contract.get("required_keys", []))
    return score_result(raw, fixture)


# ── Real runner (async-safe wrapper around LLMFactory) ───────────────────────


def _run_fixture_real_sync(fixture: BenchmarkFixture, provider: str = "", model: str = "") -> BenchmarkResult:
    """
    Run a fixture against a real LLM.

    This function is intentionally synchronous so it can be called from a CLI
    without forcing async on callers. It creates a temporary event loop only
    when needed.
    """
    from core.config import get_settings
    from core.llm_factory import LLMFactory

    settings = get_settings()
    factory = LLMFactory(settings)

    role_for_factory = {
        AgentRole.FORGE_BUILDER: "builder",
        AgentRole.SCOUT_RESEARCH: "research",
        AgentRole.SHADOW_ADVISOR: "advisor",
    }.get(fixture.role, "default")

    provider_used = provider or factory.available_for_role(role_for_factory)
    model_used = model or "unknown"
    fallback_used = False
    artifact_text = ""
    error_category = ErrorCategory.NONE
    timeout = False
    start = time.monotonic()

    _provider_override_value = provider if provider else None
    if _provider_override_value:
        from core.llm_factory import _provider_override
        token = _provider_override.set(_provider_override_value)
    else:
        token = None

    try:
        import asyncio
        llm = factory.get(role_for_factory)
        model_used = str(getattr(llm, "model_name", getattr(llm, "model", model_used)))
        messages = [{"role": "user", "content": fixture.prompt}]
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                raise RuntimeError("event loop already running")
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        try:
            response = loop.run_until_complete(factory.safe_invoke(role_for_factory, messages))
        finally:
            try:
                loop.close()
            except Exception:
                pass
        artifact_text = response
    except asyncio.TimeoutError:
        timeout = True
        error_category = ErrorCategory.TIMEOUT
    except Exception as exc:
        error_category = ErrorCategory.UNKNOWN
        artifact_text = str(exc)[:500]
    finally:
        if token is not None:
            _provider_override.reset(token)

    duration_s = time.monotonic() - start

    raw = BenchmarkRawResult(
        role=fixture.role,
        fixture_name=fixture.name,
        provider_used=provider_used,
        model_used=model_used,
        fallback_used=fallback_used,
        success=not timeout and error_category == ErrorCategory.NONE,
        duration_s=duration_s,
        timeout=timeout,
        error_category=error_category,
        artifact_text=artifact_text,
        artifact_path=None,
        json_valid=None,
        schema_ok=None,
        syntax_ok=None,
        test_passed=None,
        retry_count=0,
    )

    if fixture.role == AgentRole.FORGE_BUILDER:
        code = _strip_markdown_fences(artifact_text)
        raw.syntax_ok = _check_syntax(code)
        raw.test_passed = raw.syntax_ok
    elif fixture.role == AgentRole.SHADOW_ADVISOR:
        text = _strip_markdown_fences(artifact_text)
        ok, parsed = _check_json(text)
        raw.json_valid = ok
        raw.schema_ok = ok and isinstance(parsed, dict) and all(
            k in parsed for k in fixture.expected_output_contract.get("required_keys", [])
        )
        if not ok:
            raw.error_category = ErrorCategory.JSON_INVALID
    elif fixture.role == AgentRole.SCOUT_RESEARCH:
        raw.json_valid = False
        raw.schema_ok = False

    return score_result(raw, fixture)


def run_fixture(
    fixture: BenchmarkFixture,
    *,
    provider: str = "",
    model: str = "",
    mock: bool = False,
) -> BenchmarkResult:
    """Run a single benchmark fixture, either mocked or against a real provider."""
    if mock:
        return run_fixture_mock(fixture)
    return _run_fixture_real_sync(fixture, provider=provider, model=model)
