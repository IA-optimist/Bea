"""
Regression tests for core/hierarchical_planner.py

Tests guard:
  - should_decompose() threshold contract
  - decompose() returns None on short/low-complexity goals (fail-safe)
  - decompose() returns a valid HierarchicalPlan on long/high-complexity goals
  - MacroGoals count is within [MIN_MACRO_GOALS, MAX_MACRO_GOALS]
  - Each macro goal has a tactical plan
  - Domain keyword matching routes to correct macro descriptions
  - Fail-open: exceptions inside decompose() return None, never raise
  - Singleton get_mission_decomposer() is idempotent
"""

from unittest.mock import patch, MagicMock


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_plan_stub():
    """Return a real MissionPlan (2 steps) so isinstance checks in HierarchicalPlan pass."""
    from core.mission_planner import MissionPlan, PlanStep
    return MissionPlan(
        plan_id="stub-000",
        original_goal="stub goal",
        mission_type="general",
        complexity="medium",
        steps=[
            PlanStep(step_id=0, description="stub step 0", mission_type="general",
                     required_tools=[], required_agents=[], estimated_complexity="low", depends_on=[]),
            PlanStep(step_id=1, description="stub step 1", mission_type="general",
                     required_tools=[], required_agents=[], estimated_complexity="low", depends_on=[]),
        ],
    )


# ── should_decompose() ────────────────────────────────────────────────────────

class TestShouldDecompose:
    def setup_method(self):
        from core.hierarchical_planner import MissionDecomposer
        self.d = MissionDecomposer()

    def test_high_complexity_long_goal_returns_true(self):
        goal = "Build a full SaaS platform with authentication, billing, and multi-tenant support"
        assert self.d.should_decompose(goal, complexity="high") is True

    def test_medium_complexity_returns_false(self):
        goal = "Build a full SaaS platform with authentication and billing"
        assert self.d.should_decompose(goal, complexity="medium") is False

    def test_low_complexity_returns_false(self):
        goal = "Fix a bug in authentication module that causes login to fail"
        assert self.d.should_decompose(goal, complexity="low") is False

    def test_short_goal_high_complexity_returns_false(self):
        # Under 60 chars should not decompose even at high complexity
        short = "Fix auth bug"
        assert self.d.should_decompose(short, complexity="high") is False

    def test_exactly_60_chars_returns_true(self):
        goal = "A" * 60
        assert self.d.should_decompose(goal, complexity="high") is True

    def test_59_chars_returns_false(self):
        goal = "A" * 59
        assert self.d.should_decompose(goal, complexity="high") is False

    def test_empty_goal_returns_false(self):
        assert self.d.should_decompose("", complexity="high") is False

    def test_whitespace_only_returns_false(self):
        assert self.d.should_decompose("   ", complexity="high") is False


# ── decompose() returns None for excluded cases ───────────────────────────────

class TestDecomposeReturnsNone:
    def setup_method(self):
        from core.hierarchical_planner import MissionDecomposer
        self.d = MissionDecomposer()

    def test_short_goal_returns_none(self):
        result = self.d.decompose("Short goal", "general", "high")
        assert result is None

    def test_low_complexity_returns_none(self):
        long_goal = "Build a full SaaS platform with authentication and billing system"
        result = self.d.decompose(long_goal, "general", "low")
        assert result is None

    def test_medium_complexity_returns_none(self):
        long_goal = "Build a full SaaS platform with authentication and billing system"
        result = self.d.decompose(long_goal, "general", "medium")
        assert result is None


# ── decompose() returns valid plan ────────────────────────────────────────────

class TestDecomposeReturnsValidPlan:
    def setup_method(self):
        from core.hierarchical_planner import MissionDecomposer, MIN_MACRO_GOALS, MAX_MACRO_GOALS
        self.d = MissionDecomposer()
        self.min = MIN_MACRO_GOALS
        self.max = MAX_MACRO_GOALS

    @patch("core.mission_planner.MissionPlanner")
    def test_saas_goal_returns_plan(self, mock_planner_cls):
        mock_planner = MagicMock()
        mock_planner.build_plan.return_value = _make_plan_stub()
        mock_planner_cls.return_value = mock_planner

        goal = "Build a full SaaS product with multi-tenant architecture and billing"
        result = self.d.decompose(goal, "coding_task", "high", mission_id="test-001")

        assert result is not None
        assert self.min <= len(result.macro_goals) <= self.max
        assert result.mission_id == "test-001"
        assert result.original_goal == goal

    @patch("core.mission_planner.MissionPlanner")
    def test_macro_goals_have_tactical_plan(self, mock_planner_cls):
        mock_planner = MagicMock()
        mock_planner.build_plan.return_value = _make_plan_stub()
        mock_planner_cls.return_value = mock_planner

        goal = "Migrate legacy monolith to microservices architecture with zero downtime"
        result = self.d.decompose(goal, "coding_task", "high")

        assert result is not None
        for mg in result.macro_goals:
            assert mg.tactical_plan is not None
            assert mg.macro_id >= 0
            assert len(mg.description) > 10
            assert mg.status == "pending"

    @patch("core.mission_planner.MissionPlanner")
    def test_total_tactical_steps_counts_correctly(self, mock_planner_cls):
        stub = _make_plan_stub()  # 2 steps per macro goal
        mock_planner = MagicMock()
        mock_planner.build_plan.return_value = stub
        mock_planner_cls.return_value = mock_planner

        goal = "Build a DevOps CI/CD pipeline with Docker and Kubernetes automation"
        result = self.d.decompose(goal, "coding_task", "high")

        assert result is not None
        assert result.total_tactical_steps == len(result.macro_goals) * 2

    @patch("core.mission_planner.MissionPlanner")
    def test_to_dict_is_serializable(self, mock_planner_cls):
        mock_planner = MagicMock()
        mock_planner.build_plan.return_value = _make_plan_stub()
        mock_planner_cls.return_value = mock_planner

        goal = "Design a multi-system integration architecture for enterprise platform"
        result = self.d.decompose(goal, "architecture_task", "high")

        assert result is not None
        d = result.to_dict()
        assert isinstance(d, dict)
        assert "plan_id" in d
        assert "macro_goals" in d
        assert isinstance(d["macro_goals"], list)


# ── Domain keyword routing ────────────────────────────────────────────────────

class TestDomainKeywordRouting:
    @patch("core.mission_planner.MissionPlanner")
    def test_security_goal_gets_security_macros(self, mock_planner_cls):
        mock_planner = MagicMock()
        mock_planner.build_plan.return_value = _make_plan_stub()
        mock_planner_cls.return_value = mock_planner

        from core.hierarchical_planner import MissionDecomposer
        d = MissionDecomposer()
        goal = "Conduct a full security audit and vulnerability assessment of the backend infrastructure"
        result = d.decompose(goal, "research_task", "high")

        assert result is not None
        descriptions = [mg.description.lower() for mg in result.macro_goals]
        # Security domain: should mention attack surface / vulnerability / remediation
        combined = " ".join(descriptions)
        assert any(kw in combined for kw in ["vuln", "risque", "attaque", "remédiation", "rapport"])

    @patch("core.mission_planner.MissionPlanner")
    def test_generic_goal_still_produces_plan(self, mock_planner_cls):
        mock_planner = MagicMock()
        mock_planner.build_plan.return_value = _make_plan_stub()
        mock_planner_cls.return_value = mock_planner

        from core.hierarchical_planner import MissionDecomposer
        d = MissionDecomposer()
        # This goal has no specific domain keywords → generic decomposition
        goal = "Execute a comprehensive and thorough investigation into the reported anomaly"
        result = d.decompose(goal, "research_task", "high")

        assert result is not None
        assert len(result.macro_goals) >= 2


# ── Fail-open behavior ────────────────────────────────────────────────────────

class TestFailOpen:
    def test_planner_exception_returns_none_not_raises(self):
        from core.hierarchical_planner import MissionDecomposer
        d = MissionDecomposer()

        with patch("core.mission_planner.MissionPlanner") as mock_cls:
            mock_cls.side_effect = RuntimeError("unexpected failure")
            goal = "Build a SaaS product with full authentication and multi-tenant billing"
            result = d.decompose(goal, "coding_task", "high")
            assert result is None  # fail-open: returns None, never raises

    def test_build_plan_exception_returns_none(self):
        from core.hierarchical_planner import MissionDecomposer
        d = MissionDecomposer()

        with patch("core.mission_planner.MissionPlanner") as mock_cls:
            mock_planner = MagicMock()
            mock_planner.build_plan.side_effect = ValueError("plan failure")
            mock_cls.return_value = mock_planner

            goal = "Build a full DevOps pipeline with Docker Kubernetes and CI/CD automation"
            result = d.decompose(goal, "coding_task", "high")
            assert result is None


# ── Singleton ─────────────────────────────────────────────────────────────────

class TestSingleton:
    def test_get_mission_decomposer_returns_same_instance(self):
        from core.hierarchical_planner import get_mission_decomposer
        a = get_mission_decomposer()
        b = get_mission_decomposer()
        assert a is b

    def test_singleton_is_mission_decomposer(self):
        from core.hierarchical_planner import get_mission_decomposer, MissionDecomposer
        inst = get_mission_decomposer()
        assert isinstance(inst, MissionDecomposer)
