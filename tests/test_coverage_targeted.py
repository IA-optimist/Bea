"""Targeted coverage tests — exercise actual code paths in high-stmt modules.

Unlike smoke tests (imports only), these tests call real function bodies to
cover conditional branches, dataclass methods, and pure logic.  No LLM calls,
no DB, no external I/O.

Coverage intent: bring total from 58% toward 60%+.  Kernel pure modules added
in round 2 (PR #81) : KernelLearner, KernelPlanner, KernelGoal, KernelPlan,
KernelLesson, KernelPlanStep — all pure Python, no external deps.
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


# ── KernelLesson (kernel/learning/lesson.py) — pure dataclass ────────────────

class TestKernelLesson:

    def _make_lesson(self):
        from kernel.learning.lesson import KernelLesson
        return KernelLesson(
            mission_id="m123",
            goal_summary="Write a hello world",
            what_happened="Low confidence result (confidence=0.70)",
            what_to_do_differently="Consider more specific goal formulation",
            confidence=0.7,
            verdict="low_confidence",
            weaknesses=["shallow analysis"],
            improvement_suggestion="break into steps",
        )

    def test_to_dict_has_mission_id(self):
        d = self._make_lesson().to_dict()
        assert d["mission_id"] == "m123"

    def test_to_dict_has_verdict(self):
        d = self._make_lesson().to_dict()
        assert d["verdict"] == "low_confidence"

    def test_to_dict_has_weaknesses(self):
        d = self._make_lesson().to_dict()
        assert d["weaknesses"] == ["shallow analysis"]

    def test_to_core_lesson_dict(self):
        d = self._make_lesson().to_core_lesson_dict()
        assert "mission_id" in d
        assert "what_to_do_differently" in d
        assert "confidence" in d

    def test_lesson_id_generated(self):
        from kernel.learning.lesson import KernelLesson
        l1 = KernelLesson(
            mission_id="x", goal_summary="g", what_happened="h",
            what_to_do_differently="w", confidence=0.5,
        )
        l2 = KernelLesson(
            mission_id="x", goal_summary="g", what_happened="h",
            what_to_do_differently="w", confidence=0.5,
        )
        assert l1.lesson_id != l2.lesson_id


# ── KernelGoal / KernelPlan / KernelPlanStep (kernel/planning/goal.py) ───────

class TestKernelGoalPlan:

    def test_kernel_goal_from_text(self):
        from kernel.planning.goal import KernelGoal
        g = KernelGoal.from_text("Build a REST API")
        assert g.description == "Build a REST API"
        assert g.goal_type == "general"

    def test_kernel_goal_from_text_strips(self):
        from kernel.planning.goal import KernelGoal
        g = KernelGoal.from_text("  trim me  ")
        assert g.description == "trim me"

    def test_kernel_goal_to_dict(self):
        from kernel.planning.goal import KernelGoal
        g = KernelGoal(description="test goal", goal_type="code", priority=3)
        d = g.to_dict()
        assert d["description"] == "test goal"
        assert d["goal_type"] == "code"
        assert d["priority"] == 3

    def test_kernel_goal_id_generated(self):
        from kernel.planning.goal import KernelGoal
        g1 = KernelGoal(description="a")
        g2 = KernelGoal(description="a")
        assert g1.goal_id != g2.goal_id

    def test_plan_step_to_dict(self):
        from kernel.planning.goal import KernelPlanStep, PlanComplexity, StepStatus
        s = KernelPlanStep(step_id=0, action="Analyze the problem", complexity=PlanComplexity.LOW)
        d = s.to_dict()
        assert d["step_id"] == 0
        assert d["action"] == "Analyze the problem"
        assert d["complexity"] == "low"
        assert d["status"] == "pending"

    def test_plan_step_retryable_default(self):
        from kernel.planning.goal import KernelPlanStep
        s = KernelPlanStep(step_id=1, action="Do thing")
        assert s.retryable is True

    def test_kernel_plan_is_empty_true(self):
        from kernel.planning.goal import KernelGoal, KernelPlan
        g = KernelGoal(description="goal")
        p = KernelPlan(plan_id="p1", goal=g)
        assert p.is_empty is True
        assert p.step_count == 0
        assert p.success_rate == 0.0

    def test_kernel_plan_step_count(self):
        from kernel.planning.goal import KernelGoal, KernelPlan, KernelPlanStep
        g = KernelGoal(description="goal")
        steps = [KernelPlanStep(step_id=i, action=f"step {i}") for i in range(3)]
        p = KernelPlan(plan_id="p1", goal=g, steps=steps)
        assert p.step_count == 3
        assert p.is_empty is False

    def test_kernel_plan_pending_and_done(self):
        from kernel.planning.goal import KernelGoal, KernelPlan, KernelPlanStep, StepStatus
        g = KernelGoal(description="goal")
        s0 = KernelPlanStep(step_id=0, action="a", status=StepStatus.DONE)
        s1 = KernelPlanStep(step_id=1, action="b", status=StepStatus.PENDING)
        s2 = KernelPlanStep(step_id=2, action="c", status=StepStatus.DONE)
        p = KernelPlan(plan_id="p1", goal=g, steps=[s0, s1, s2])
        assert len(p.done_steps) == 2
        assert len(p.pending_steps) == 1
        assert abs(p.success_rate - 2/3) < 1e-9

    def test_kernel_plan_to_dict(self):
        from kernel.planning.goal import KernelGoal, KernelPlan, KernelPlanStep
        g = KernelGoal(description="test")
        p = KernelPlan(plan_id="p99", goal=g, steps=[KernelPlanStep(step_id=0, action="do")])
        d = p.to_dict()
        assert d["plan_id"] == "p99"
        assert len(d["steps"]) == 1
        assert d["step_count"] == 1


# ── KernelPlanner (kernel/planning/planner.py) — heuristic planning ──────────

class TestKernelPlanner:

    def _planner(self):
        from kernel.planning.planner import KernelPlanner
        return KernelPlanner()

    def _goal(self, text: str):
        from kernel.planning.goal import KernelGoal
        return KernelGoal(description=text)

    def test_complexity_low(self):
        from kernel.planning.goal import PlanComplexity
        p = self._planner()
        g = self._goal("Fix bug")
        assert p._complexity(g) == PlanComplexity.LOW

    def test_complexity_medium(self):
        from kernel.planning.goal import PlanComplexity
        p = self._planner()
        g = self._goal("Implement a user authentication system with JWT tokens and refresh logic")
        assert p._complexity(g) == PlanComplexity.MEDIUM

    def test_complexity_high(self):
        from kernel.planning.goal import PlanComplexity
        p = self._planner()
        # 31+ words
        words = " ".join(["word"] * 35)
        g = self._goal(words)
        assert p._complexity(g) == PlanComplexity.HIGH

    def test_heuristic_plan_creates_3_steps(self):
        p = self._planner()
        g = self._goal("Build a microservice for data processing and analysis")
        plan = p._heuristic_plan("kplan-test", g)
        assert len(plan.steps) == 3
        assert plan.source == "kernel_heuristic"

    def test_heuristic_plan_step_depends_on(self):
        p = self._planner()
        g = self._goal("simple goal")
        plan = p._heuristic_plan("kplan-test", g)
        assert plan.steps[1].depends_on == [0]
        assert plan.steps[2].depends_on == [1]

    def test_build_no_core_planner(self):
        import kernel.planning.planner as planner_mod
        original = planner_mod._core_planner_fn
        planner_mod._core_planner_fn = None
        try:
            p = self._planner()
            g = self._goal("Analyze the dataset")
            plan = p.build(g)
            assert plan.source == "kernel_heuristic"
            assert plan.step_count == 3
        finally:
            planner_mod._core_planner_fn = original

    def test_build_with_core_planner_dict_steps(self):
        import kernel.planning.planner as planner_mod
        original = planner_mod._core_planner_fn
        fake_plan = {"steps": [
            {"action": "Step 1: gather data", "agent_hint": "researcher"},
            {"action": "Step 2: analyze", "agent_hint": "analyst"},
        ]}
        planner_mod._core_planner_fn = lambda desc: fake_plan
        try:
            p = self._planner()
            g = self._goal("Analyze the dataset")
            plan = p.build(g)
            assert plan.source == "core_planner"
            assert plan.step_count == 2
            assert plan.steps[0].action == "Step 1: gather data"
        finally:
            planner_mod._core_planner_fn = original

    def test_build_core_planner_exception_falls_back(self):
        import kernel.planning.planner as planner_mod
        original = planner_mod._core_planner_fn
        def _boom(desc):
            raise RuntimeError("boom")
        planner_mod._core_planner_fn = _boom
        try:
            p = self._planner()
            g = self._goal("Analyze")
            plan = p.build(g)
            assert plan.source == "kernel_heuristic"
        finally:
            planner_mod._core_planner_fn = original

    def test_build_core_planner_empty_steps_falls_back(self):
        import kernel.planning.planner as planner_mod
        original = planner_mod._core_planner_fn
        planner_mod._core_planner_fn = lambda desc: {"steps": []}
        try:
            p = self._planner()
            g = self._goal("Do something")
            plan = p.build(g)
            assert plan.source == "kernel_heuristic"
        finally:
            planner_mod._core_planner_fn = original

    def test_register_core_planner(self):
        from kernel.planning.planner import register_core_planner
        import kernel.planning.planner as planner_mod
        original = planner_mod._core_planner_fn
        def _fake_planner(desc):
            return {"steps": []}
        try:
            register_core_planner(_fake_planner)
            assert planner_mod._core_planner_fn is _fake_planner
        finally:
            planner_mod._core_planner_fn = original

    def test_get_planner_singleton(self):
        from kernel.planning.planner import get_planner
        p1 = get_planner()
        p2 = get_planner()
        assert p1 is p2


# ── KernelLearner (kernel/learning/learner.py) — learning decisions ──────────

class TestKernelLearner:

    def _learner(self):
        from kernel.learning.learner import KernelLearner
        return KernelLearner()

    def test_should_learn_clean_accept_high_conf(self):
        l = self._learner()
        assert l.should_learn("accept", 0.9) is False

    def test_should_learn_accept_exactly_threshold(self):
        l = self._learner()
        assert l.should_learn("accept", 0.8) is False

    def test_should_learn_accept_below_threshold(self):
        l = self._learner()
        assert l.should_learn("accept", 0.79) is True

    def test_should_learn_non_accept_verdict(self):
        l = self._learner()
        assert l.should_learn("retry_suggested", 0.99) is True
        assert l.should_learn("low_confidence", 0.95) is True
        assert l.should_learn("empty", 0.5) is True

    def test_extract_clean_accept_returns_none(self):
        l = self._learner()
        result = l.extract(
            goal="Build API", result="Done", mission_id="m1",
            verdict="accept", confidence=0.9,
        )
        assert result is None

    def test_extract_empty_verdict(self):
        l = self._learner()
        lesson = l.extract(
            goal="Generate report", result="", mission_id="m2",
            verdict="empty", confidence=0.1,
        )
        assert lesson is not None
        assert "no output" in lesson.what_happened.lower()
        assert lesson.verdict == "empty"

    def test_extract_retry_suggested(self):
        l = self._learner()
        lesson = l.extract(
            goal="Analyze data", result="partial", mission_id="m3",
            verdict="retry_suggested", confidence=0.5,
        )
        assert lesson is not None
        assert "weak" in lesson.what_happened.lower() or "confidence" in lesson.what_happened.lower()

    def test_extract_with_error_class_timeout(self):
        l = self._learner()
        lesson = l.extract(
            goal="Long task", result="", mission_id="m4",
            verdict="low_confidence", confidence=0.3,
            error_class="timeout",
        )
        assert lesson is not None
        assert "timeout" in lesson.what_happened.lower() or "timeout" in lesson.what_to_do_differently.lower()

    def test_extract_with_tool_not_available(self):
        l = self._learner()
        lesson = l.extract(
            goal="Use tool X", result="", mission_id="m5",
            verdict="low_confidence", confidence=0.2,
            error_class="tool_not_available",
        )
        assert lesson is not None
        assert "tool" in lesson.what_to_do_differently.lower()

    def test_extract_with_retries(self):
        l = self._learner()
        lesson = l.extract(
            goal="Flaky task", result="ok", mission_id="m6",
            verdict="low_confidence", confidence=0.6,
            retries=3,
        )
        assert lesson is not None
        assert "retries" in lesson.what_happened.lower() or "3" in lesson.what_happened

    def test_extract_with_weaknesses_appended(self):
        l = self._learner()
        lesson = l.extract(
            goal="Complex task", result="partial", mission_id="m7",
            verdict="low_confidence", confidence=0.4,
            weaknesses=["shallow analysis", "missing context"],
        )
        assert lesson is not None
        assert "shallow analysis" in lesson.what_happened

    def test_extract_with_improvement_suggestion(self):
        l = self._learner()
        lesson = l.extract(
            goal="Task", result="result", mission_id="m8",
            verdict="low_confidence", confidence=0.5,
            improvement_suggestion="Break into smaller subtasks",
        )
        assert lesson is not None
        assert lesson.what_to_do_differently == "Break into smaller subtasks"

    def test_extract_truncates_long_goal(self):
        l = self._learner()
        long_goal = "a" * 200
        lesson = l.extract(
            goal=long_goal, result="r", mission_id="m9",
            verdict="low_confidence", confidence=0.5,
        )
        assert lesson is not None
        assert len(lesson.goal_summary) <= 103  # 100 chars + "..."

    def test_store_no_fn_returns_false(self):
        import kernel.learning.learner as learner_mod
        from kernel.learning.lesson import KernelLesson
        original = learner_mod._lesson_store_fn
        learner_mod._lesson_store_fn = None
        try:
            lesson = KernelLesson(
                mission_id="x", goal_summary="g", what_happened="h",
                what_to_do_differently="w", confidence=0.5,
            )
            result = self._learner().store(lesson)
            assert result is False
        finally:
            learner_mod._lesson_store_fn = original

    def test_store_with_fn_called(self):
        import kernel.learning.learner as learner_mod
        from kernel.learning.lesson import KernelLesson
        original = learner_mod._lesson_store_fn
        calls = []
        learner_mod._lesson_store_fn = lambda l: calls.append(l) or True
        try:
            lesson = KernelLesson(
                mission_id="x", goal_summary="g", what_happened="h",
                what_to_do_differently="w", confidence=0.5,
            )
            result = self._learner().store(lesson)
            assert result is True
            assert len(calls) == 1
        finally:
            learner_mod._lesson_store_fn = original

    def test_store_fn_exception_falls_back(self):
        import kernel.learning.learner as learner_mod
        from kernel.learning.lesson import KernelLesson
        original = learner_mod._lesson_store_fn
        def _crash(l):
            raise RuntimeError("db down")
        learner_mod._lesson_store_fn = _crash
        try:
            lesson = KernelLesson(
                mission_id="x", goal_summary="g", what_happened="h",
                what_to_do_differently="w", confidence=0.5,
            )
            result = self._learner().store(lesson)
            assert result is False
        finally:
            learner_mod._lesson_store_fn = original

    def test_learn_clean_returns_none(self):
        l = self._learner()
        result = l.learn(
            goal="Task", result="Done", mission_id="m_clean",
            verdict="accept", confidence=0.95,
        )
        assert result is None

    def test_learn_creates_and_stores_lesson(self):
        import kernel.learning.learner as learner_mod
        original = learner_mod._lesson_store_fn
        stored = []
        learner_mod._lesson_store_fn = lambda les: stored.append(les) or True
        try:
            l = self._learner()
            lesson = l.learn(
                goal="Do analysis", result="partial", mission_id="m_learn",
                verdict="low_confidence", confidence=0.4,
            )
            assert lesson is not None
            assert lesson.mission_id == "m_learn"
            assert len(stored) == 1
        finally:
            learner_mod._lesson_store_fn = original

    def test_learn_never_raises(self):
        # store() catches its own exception and logs; learn() still returns the lesson
        import kernel.learning.learner as learner_mod
        original = learner_mod._lesson_store_fn
        def _crash(l):
            raise RuntimeError("crash")
        learner_mod._lesson_store_fn = _crash
        try:
            l = self._learner()
            # Does not raise — learn() is fail-open
            result = l.learn(
                goal="g", result="r", mission_id="m_crash",
                verdict="empty", confidence=0.1,
            )
            # lesson is returned even if store failed (store catches internally)
            assert result is not None
            assert result.mission_id == "m_crash"
        finally:
            learner_mod._lesson_store_fn = original

    def test_register_lesson_store(self):
        from kernel.learning.learner import register_lesson_store
        import kernel.learning.learner as learner_mod
        original = learner_mod._lesson_store_fn
        def _fake_store(l):
            return True
        try:
            register_lesson_store(_fake_store)
            assert learner_mod._lesson_store_fn is _fake_store
        finally:
            learner_mod._lesson_store_fn = original

    def test_get_learner_singleton(self):
        from kernel.learning.learner import get_learner
        l1 = get_learner()
        l2 = get_learner()
        assert l1 is l2
