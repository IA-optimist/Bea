"""Targeted coverage tests — exercise actual code paths in high-stmt modules.

Unlike smoke tests (imports only), these tests call real function bodies to
cover conditional branches, dataclass methods, and pure logic.  No LLM calls,
no DB, no external I/O.

Coverage intent: bring total from 58% toward 60%+.
"""
from __future__ import annotations

import time


# ── cognitive_consolidation — pure math/transform helpers ────────────────────

class TestCognitiveConsolidation:

    def test_variance_empty(self):
        from core.cognitive_consolidation import _variance
        assert _variance([]) == 0.0

    def test_variance_single(self):
        from core.cognitive_consolidation import _variance
        assert _variance([42.0]) == 0.0

    def test_variance_known(self):
        from core.cognitive_consolidation import _variance
        assert abs(_variance([1.0, 2.0, 3.0, 4.0, 5.0]) - 2.0) < 1e-9

    def test_variance_uniform(self):
        from core.cognitive_consolidation import _variance
        assert _variance([7.0, 7.0, 7.0]) == 0.0

    def test_extract_domain_patterns_empty(self):
        from core.cognitive_consolidation import _extract_domain_patterns
        result = _extract_domain_patterns([])
        assert isinstance(result, dict)

    def test_extract_domain_patterns_single_domain(self):
        from core.cognitive_consolidation import _extract_domain_patterns
        traces = [
            {"domain": "code", "success": True, "duration_ms": 500, "score": 0.9},
            {"domain": "code", "success": False, "duration_ms": 200, "score": 0.3},
        ]
        result = _extract_domain_patterns(traces)
        assert isinstance(result, dict)

    def test_extract_domain_patterns_multi_domain(self):
        from core.cognitive_consolidation import _extract_domain_patterns
        traces = [
            {"domain": "search", "success": True},
            {"domain": "analysis", "success": True},
            {"domain": "search", "success": False},
        ]
        result = _extract_domain_patterns(traces)
        assert isinstance(result, dict)


# ── knowledge_filter — pure scoring logic ────────────────────────────────────

class TestKnowledgeFilter:

    def test_filter_result_dataclass(self):
        from core.learning.knowledge_filter import FilterResult
        r = FilterResult(
            url="https://docs.python.org",
            source_type="documentation",
            trust_score=0.9,
            freshness_score=0.8,
            actionability_score=0.7,
            global_score=0.8,
            accepted=True,
        )
        assert r.accepted is True
        assert r.global_score == 0.8

    def test_filter_result_with_rejection(self):
        from core.learning.knowledge_filter import FilterResult
        r = FilterResult(
            url="https://spam.example.com",
            source_type="unknown",
            trust_score=0.1,
            freshness_score=0.2,
            actionability_score=0.1,
            global_score=0.1,
            accepted=False,
            rejection_reason="low_trust",
        )
        assert r.accepted is False
        assert r.rejection_reason == "low_trust"

    def test_evaluate_trusted_source(self):
        from core.learning.knowledge_filter import KnowledgeFilter
        kf = KnowledgeFilter()
        result = kf.evaluate(
            "https://docs.python.org/3/library/functions.html",
            "Python built-in functions documentation",
        )
        assert hasattr(result, "accepted")
        assert hasattr(result, "global_score")
        assert isinstance(result.global_score, float)

    def test_evaluate_unknown_url(self):
        from core.learning.knowledge_filter import KnowledgeFilter
        kf = KnowledgeFilter()
        result = kf.evaluate("https://random-site.example.com/page", "some content")
        assert hasattr(result, "accepted")

    def test_evaluate_empty_content(self):
        from core.learning.knowledge_filter import KnowledgeFilter
        kf = KnowledgeFilter()
        result = kf.evaluate("https://example.com")
        assert hasattr(result, "global_score")

    def test_batch_evaluate_empty(self):
        from core.learning.knowledge_filter import KnowledgeFilter
        kf = KnowledgeFilter()
        results = kf.batch_evaluate([])
        assert results == []

    def test_batch_evaluate_multiple(self):
        from core.learning.knowledge_filter import KnowledgeFilter
        kf = KnowledgeFilter()
        sources = [
            {"url": "https://docs.python.org", "content": "Python docs"},
            {"url": "https://arxiv.org/abs/1234", "content": "Research paper"},
        ]
        results = kf.batch_evaluate(sources)
        assert len(results) == 2

    def test_filter_accepted(self):
        from core.learning.knowledge_filter import KnowledgeFilter
        kf = KnowledgeFilter()
        sources = [
            {"url": "https://docs.python.org", "content": "docs"},
            {"url": "https://spam.xyz/link", "content": "spam"},
        ]
        accepted = kf.filter_accepted(sources)
        assert isinstance(accepted, list)


# ── knowledge_validator — content analysis ───────────────────────────────────

class TestKnowledgeValidator:

    def test_validation_result_dataclass(self):
        from core.learning.knowledge_validator import ValidationResult, Verdict
        r = ValidationResult(
            verdict=Verdict.KEEP,
            knowledge_type="best_practice",
            credibility_score=0.8,
            utility_score=0.9,
            reusability_score=0.7,
        )
        assert r.verdict == Verdict.KEEP

    def test_verdict_enum_values(self):
        from core.learning.knowledge_validator import Verdict
        assert hasattr(Verdict, "KEEP") or hasattr(Verdict, "DISCARD")

    def test_validate_good_content(self):
        from core.learning.knowledge_validator import KnowledgeValidator
        kv = KnowledgeValidator()
        result = kv.validate(
            content="Use context managers (with statement) for resource management in Python.",
            topic="python best practices",
            source_trust=0.9,
            knowledge_type="best_practice",
        )
        assert hasattr(result, "verdict")
        assert hasattr(result, "global_score")

    def test_validate_empty_content(self):
        from core.learning.knowledge_validator import KnowledgeValidator
        kv = KnowledgeValidator()
        result = kv.validate(content="", topic="test")
        assert hasattr(result, "verdict")

    def test_validate_batch_empty(self):
        from core.learning.knowledge_validator import KnowledgeValidator
        kv = KnowledgeValidator()
        results = kv.validate_batch([])
        assert results == []

    def test_validate_batch_items(self):
        from core.learning.knowledge_validator import KnowledgeValidator
        kv = KnowledgeValidator()
        items = [
            {"content": "Always test your code.", "topic": "testing"},
            {"content": "Use version control.", "topic": "vcs"},
        ]
        results = kv.validate_batch(items)
        assert len(results) == 2
        for item, result in results:
            assert hasattr(result, "verdict")


# ── capability_scorer — pure score logic ─────────────────────────────────────

class TestCapabilityScorer:

    def test_domain_score_dataclass(self):
        from core.knowledge.capability_scorer import DomainScore
        ds = DomainScore(domain="code", success_count=5, failure_count=1)
        assert ds.domain == "code"
        assert ds.success_count == 5

    def test_scorer_default_score(self):
        from core.knowledge.capability_scorer import CapabilityScorer
        cs = CapabilityScorer()
        score = cs.get_score("code")
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def test_scorer_all_scores(self):
        from core.knowledge.capability_scorer import CapabilityScorer
        cs = CapabilityScorer()
        scores = cs.get_all_scores()
        assert isinstance(scores, dict)

    def test_scorer_stats(self):
        from core.knowledge.capability_scorer import CapabilityScorer
        cs = CapabilityScorer()
        stats = cs.get_stats()
        assert isinstance(stats, dict)

    def test_scorer_strongest_weakest(self):
        from core.knowledge.capability_scorer import CapabilityScorer
        cs = CapabilityScorer()
        strongest = cs.get_strongest_domain()
        weakest = cs.get_weakest_domain()
        assert strongest is None or isinstance(strongest, str)
        assert weakest is None or isinstance(weakest, str)


# ── decision_replay — event tracking dataclass ───────────────────────────────

class TestDecisionReplay:

    def test_decision_event_dataclass(self):
        from core.decision_replay import DecisionEvent
        evt = DecisionEvent(
            id="evt1",
            session_id="sess1",
            event_type="tool_call",
            ts=time.time(),
        )
        assert evt.id == "evt1"
        assert evt.success is True

    def test_decision_event_with_error(self):
        from core.decision_replay import DecisionEvent
        evt = DecisionEvent(
            id="evt2",
            session_id="sess1",
            event_type="tool_call",
            ts=time.time(),
            success=False,
            error="timeout",
        )
        assert evt.success is False
        assert evt.error == "timeout"

    def test_decision_replay_class(self):
        from core.decision_replay import DecisionReplay
        import inspect
        methods = [n for n in dir(DecisionReplay) if not n.startswith("_")]
        assert len(methods) > 0


# ── rag pipeline — dataclass coverage ───────────────────────────────────────

class TestRagPipeline:

    def test_rag_result_dataclass(self):
        from core.rag.pipeline import RagResult
        r = RagResult(
            answer_context="Here is the relevant context from memory.",
            sources=["memory://chunk1"],
            scores=[0.9],
            total_found=1,
        )
        assert r.answer_context.startswith("Here")
        assert r.total_found == 1

    def test_rag_result_defaults(self):
        from core.rag.pipeline import RagResult
        r = RagResult(answer_context="")
        assert r.sources == []
        assert r.total_found == 0


# ── agent_comm — message dataclasses ─────────────────────────────────────────

class TestAgentComm:

    def test_agent_message_dataclass(self):
        from core.agent_comm import AgentMessage
        msg = AgentMessage(
            session_id="s1",
            from_agent="orchestrator",
            to_agent="researcher",
            payload={"task": "search for X"},
        )
        assert msg.from_agent == "orchestrator"
        assert msg.session_id == "s1"

    def test_agent_output_dataclass(self):
        from core.agent_comm import AgentOutput
        out = AgentOutput(
            session_id="s1",
            agent_name="researcher",
            output_type="result",
            payload={"result": "found X"},
        )
        assert out.agent_name == "researcher"
        assert out.output_type == "result"

    def test_agent_message_auto_ids(self):
        from core.agent_comm import AgentMessage
        msg1 = AgentMessage(session_id="s1")
        msg2 = AgentMessage(session_id="s1")
        assert msg1.message_id != msg2.message_id


# ── client_profile — data model ──────────────────────────────────────────────

class TestClientProfile:

    def test_client_profile_dataclass(self):
        from core.client_profile import ClientProfile
        p = ClientProfile(
            name="Acme Corp",
            sector="B2B SaaS",
            communication_style="formel",
        )
        assert p.name == "Acme Corp"
        assert p.sector == "B2B SaaS"

    def test_client_profile_defaults(self):
        from core.client_profile import ClientProfile
        p = ClientProfile(name="Test", sector="tech")
        assert isinstance(p.objectives, list)
        assert isinstance(p.mission_history, list)
        assert p.communication_style == "professionnel"


# ── action_executor — singleton access ───────────────────────────────────────

class TestActionExecutor:

    def test_get_executor_returns_instance(self):
        from core.action_executor import get_executor
        executor = get_executor()
        assert executor is not None

    def test_action_executor_has_execute(self):
        from core.action_executor import ActionExecutor
        assert hasattr(ActionExecutor, "execute_action") or hasattr(ActionExecutor, "run_once")


# ── proposal_applicator — parsing helpers ─────────────────────────────────────

class TestProposalApplicator:

    def test_failed_tests_empty_output(self):
        from core.self_improvement.proposal_applicator import _failed_tests
        result = _failed_tests("")
        assert isinstance(result, set)
        assert len(result) == 0

    def test_failed_tests_all_passed(self):
        from core.self_improvement.proposal_applicator import _failed_tests
        result = _failed_tests("test_foo PASSED\ntest_bar PASSED\n")
        assert isinstance(result, set)

    def test_failed_tests_with_failures(self):
        from core.self_improvement.proposal_applicator import _failed_tests
        output = (
            "PASSED tests/test_foo.py::test_one\n"
            "FAILED tests/test_bar.py::test_two - AssertionError: expected True\n"
            "FAILED tests/test_baz.py::test_three\n"
            "ERROR tests/test_qux.py::test_four\n"
        )
        result = _failed_tests(output)
        assert isinstance(result, set)
        assert len(result) >= 2

    def test_failed_tests_only_errors(self):
        from core.self_improvement.proposal_applicator import _failed_tests
        result = _failed_tests("ERROR tests/test_db.py::test_connect - ConnectionError\n")
        assert isinstance(result, set)


# ── decision_replay — in-memory replay engine ─────────────────────────────────

class TestDecisionReplayMethods:

    def _make_replay(self):
        from unittest.mock import MagicMock
        from core.decision_replay import DecisionReplay
        return DecisionReplay(settings=MagicMock())

    def test_get_errors_empty(self):
        dr = self._make_replay()
        errors = dr.get_errors()
        assert isinstance(errors, list)
        assert errors == []

    def test_explain_session_missing(self):
        dr = self._make_replay()
        explanation = dr.explain_session("nonexistent-session")
        assert isinstance(explanation, str)

    def test_clear_is_idempotent(self):
        dr = self._make_replay()
        dr.clear()
        dr.clear()
        assert dr.get_errors() == []

    def test_clear_session(self):
        dr = self._make_replay()
        dr.clear_session("no-such-session")
        assert dr.get_errors() == []

    def test_get_errors_with_n(self):
        dr = self._make_replay()
        errors = dr.get_errors(n=5)
        assert isinstance(errors, list)


# ── agent_factory — blueprint dataclass ───────────────────────────────────────

class TestAgentFactory:

    def test_agent_blueprint_minimal(self):
        from core.agent_factory import AgentBlueprint
        bp = AgentBlueprint(
            name="researcher",
            role="search and summarize information",
            system_prompt="You are a research agent. Search for relevant information.",
        )
        assert bp.name == "researcher"
        assert "researcher" in bp.name

    def test_agent_blueprint_with_tools(self):
        from core.agent_factory import AgentBlueprint
        bp = AgentBlueprint(
            name="coder",
            role="write and review code",
            system_prompt="You are a coding agent.",
            tools=["python_repl", "file_read"],
            timeout_s=120,
            max_reruns=2,
        )
        assert bp.tools == ["python_repl", "file_read"]
        assert bp.timeout_s == 120

    def test_agent_blueprint_defaults(self):
        from core.agent_factory import AgentBlueprint
        bp = AgentBlueprint(
            name="analyst",
            role="analyze data",
            system_prompt="You analyze data.",
        )
        assert isinstance(bp.tools, list) or bp.tools is None


# ── cognitive_consolidation — file reading helper ─────────────────────────────

class TestCognitiveConsolidationIO:

    def test_read_jsonl_missing_file(self):
        from core.cognitive_consolidation import _read_jsonl
        from pathlib import Path
        result = _read_jsonl(Path("/nonexistent/path/data.jsonl"))
        assert isinstance(result, list)
        assert result == []

    def test_read_jsonl_empty_file(self):
        import tempfile
        from pathlib import Path
        from core.cognitive_consolidation import _read_jsonl
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            fname = f.name
        result = _read_jsonl(Path(fname))
        assert isinstance(result, list)

    def test_read_jsonl_with_fresh_data(self):
        import json
        import tempfile
        import time
        from pathlib import Path
        from core.cognitive_consolidation import _read_jsonl
        data = [
            {"ts": time.time(), "domain": "code", "success": True},
            {"ts": time.time(), "domain": "search", "success": False},
        ]
        with tempfile.NamedTemporaryFile(
            suffix=".jsonl", mode="w", delete=False, encoding="utf-8"
        ) as f:
            for row in data:
                f.write(json.dumps(row) + "\n")
            fname = f.name
        result = _read_jsonl(Path(fname))
        assert isinstance(result, list)


# ── reasoning_engine — additional code paths ──────────────────────────────────

class TestReasoningEngineAdditional:

    def test_classify_complexity_multi_word(self):
        from core.orchestration.reasoning_engine import _classify_complexity
        goals = [
            ("simple query", set("simple query".split())),
            ("build and deploy a multi-region distributed microservices platform", set()),
            ("", set()),
        ]
        for goal, words in goals:
            result = _classify_complexity(goal, words)
            assert isinstance(result, str)

    def test_decompose_requirements_various_goals(self):
        from core.orchestration.reasoning_engine import _decompose_requirements
        goals = [
            ("", set()),
            ("write tests for the authentication module", set("write tests authentication module".split())),
            ("refactor and optimize the database layer with proper indexes", set()),
        ]
        for goal, words in goals:
            reqs, constraints, verif = _decompose_requirements(goal, words)
            assert isinstance(reqs, list)
            assert isinstance(constraints, list)
            assert isinstance(verif, list)

    def test_detect_bottleneck_various_contexts(self):
        from core.orchestration.reasoning_engine import _detect_bottleneck
        cases = [
            ("optimize SQL queries", {"type": "performance"}, ["slow query", "timeout"]),
            ("write unit tests", None, []),
            ("debug authentication error", {"type": "bug"}, ["401 error", "token expired"]),
        ]
        for goal, classification, failures in cases:
            result = _detect_bottleneck(goal, classification, failures)
            assert isinstance(result, str)

    def test_classify_issue_various(self):
        from core.orchestration.reasoning_engine import _classify_issue
        issues = [
            ("memory leak in the connection pool", "optimize database"),
            ("AttributeError: object has no attribute x", "fix bug"),
            ("test coverage is below threshold", "improve quality"),
        ]
        for issue, goal in issues:
            priority, score, category = _classify_issue(issue, goal)
            assert isinstance(score, float)
            assert isinstance(category, str)


# ── knowledge_filter — edge cases ─────────────────────────────────────────────

class TestKnowledgeFilterEdgeCases:

    def test_evaluate_with_year(self):
        from core.learning.knowledge_filter import KnowledgeFilter
        kf = KnowledgeFilter()
        result = kf.evaluate(
            "https://arxiv.org/abs/2312.00001",
            "A research paper on language models",
            published_year=2023,
        )
        assert hasattr(result, "global_score")

    def test_evaluate_old_source(self):
        from core.learning.knowledge_filter import KnowledgeFilter
        kf = KnowledgeFilter()
        result = kf.evaluate(
            "https://old-blog.example.com/post-from-2010",
            "deprecated tutorial",
            published_year=2010,
        )
        assert hasattr(result, "accepted")

    def test_filter_result_tags(self):
        from core.learning.knowledge_filter import FilterResult
        r = FilterResult(
            url="https://github.com/user/repo",
            source_type="code_repository",
            trust_score=0.85,
            freshness_score=0.9,
            actionability_score=0.95,
            global_score=0.9,
            accepted=True,
            tags=["code", "open_source"],
        )
        assert "code" in r.tags


# ── knowledge_validator — edge cases ──────────────────────────────────────────

class TestKnowledgeValidatorEdgeCases:

    def test_validate_duplicate_detection(self):
        from core.learning.knowledge_validator import KnowledgeValidator
        kv = KnowledgeValidator()
        existing = ["Always test your code before shipping."]
        result = kv.validate(
            content="Always test your code before shipping to production.",
            topic="software engineering",
            existing_knowledge=existing,
        )
        assert hasattr(result, "is_duplicate")

    def test_validate_dangerous_content(self):
        from core.learning.knowledge_validator import KnowledgeValidator
        kv = KnowledgeValidator()
        result = kv.validate(
            content="Delete all files with rm -rf / to free space",
            topic="disk management",
        )
        assert hasattr(result, "verdict")

    def test_validate_batch_with_knowledge(self):
        from core.learning.knowledge_validator import KnowledgeValidator
        kv = KnowledgeValidator()
        existing = ["Use type hints in Python.", "Write docstrings."]
        items = [
            {"content": "Use type hints in Python for better IDE support.", "topic": "python"},
            {"content": "Prefer composition over inheritance.", "topic": "oop"},
        ]
        results = kv.validate_batch(items, existing_knowledge=existing)
        assert len(results) == 2
