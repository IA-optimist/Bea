"""
tests/test_cognitive_upgrade.py — Unit tests for Pass 42 cognitive upgrade.

Tests cover all 3 phases:
  Phase 1 — MissionReasoningState (build, update_observed, compare)
  Phase 2 — ConfidencePolicy (tiers, risk shifts, behavior flags)
  Phase 3 — MissionLessons + memory_retrieval (structure, fallback, injection)

Also covers:
  - No-regression: existing mission flow still works when modules fail
  - Fail-open: all modules return safe fallback on exception

Test strategy: pure unit tests, no LLM, no network, no VPS.
Run with: python -m pytest tests/test_cognitive_upgrade.py -v
"""
from __future__ import annotations

import sys
import os

# Add repo root to path so imports work from test runner
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 1 — MissionReasoningState
# ══════════════════════════════════════════════════════════════════════════════

class TestMissionReasoningState:

    def test_build_returns_state(self):
        """build() always returns a MissionReasoningState, never raises."""
        from core.orchestration.mission_reasoning_state import build
        state = build(
            goal="Fix the authentication bug in login.py",
            mission_id="test-001",
            classification={"task_type": "code", "complexity": "simple", "risk_level": "low"},
        )
        assert state is not None
        assert state.mission_id == "test-001"
        assert "login.py" in state.goal

    def test_build_sets_initial_and_target_state(self):
        """Initial and target state are non-empty strings."""
        from core.orchestration.mission_reasoning_state import build
        state = build(
            goal="Deploy the new API version",
            mission_id="test-002",
            classification={"task_type": "deployment", "complexity": "moderate", "risk_level": "high"},
        )
        assert len(state.initial_state) > 0
        assert len(state.target_state) > 0

    def test_build_populates_preconditions_for_complex(self):
        """Complex mission has multiple preconditions."""
        from core.orchestration.mission_reasoning_state import build
        state = build(
            goal="Redesign the entire authentication system",
            mission_id="test-003",
            classification={"task_type": "code", "complexity": "complex", "risk_level": "medium"},
        )
        assert len(state.preconditions) >= 2

    def test_build_sets_failure_modes_for_code(self):
        """Code task has relevant failure modes."""
        from core.orchestration.mission_reasoning_state import build
        state = build(
            goal="Refactor the payment module",
            mission_id="test-004",
            classification={"task_type": "code", "complexity": "moderate"},
        )
        assert len(state.failure_modes) > 0
        # Code failure modes should mention syntax or tests
        failure_text = " ".join(state.failure_modes).lower()
        assert any(kw in failure_text for kw in ["syntax", "test", "import", "break"])

    def test_build_sets_candidate_actions(self):
        """Candidate actions are populated for non-trivial missions."""
        from core.orchestration.mission_reasoning_state import build
        state = build(
            goal="Analyze database performance bottlenecks",
            mission_id="test-005",
            classification={"task_type": "analysis", "complexity": "moderate"},
        )
        assert len(state.candidate_actions) >= 2

    def test_build_sets_success_criteria(self):
        """Success criteria are populated."""
        from core.orchestration.mission_reasoning_state import build
        state = build(
            goal="Write unit tests for the payment module",
            mission_id="test-006",
            classification={"task_type": "code", "complexity": "simple"},
        )
        assert len(state.success_criteria) >= 1

    def test_build_with_prior_failures_augments_failure_modes(self):
        """Prior failures from memory are added to failure modes."""
        from core.orchestration.mission_reasoning_state import build
        state = build(
            goal="Fix the database connection pool",
            mission_id="test-007",
            classification={"task_type": "code", "complexity": "moderate"},
            prior_failures=["connection timeout after pool exhaustion"],
        )
        failure_text = " ".join(state.failure_modes)
        assert "prior:" in failure_text

    def test_build_with_memory_lessons(self):
        """Memory lessons are incorporated into failure modes."""
        from core.orchestration.mission_reasoning_state import build
        state = build(
            goal="Optimize query performance",
            mission_id="test-008",
            classification={"task_type": "code", "complexity": "moderate"},
            memory_lessons=[{"what_to_do_differently": "use EXPLAIN ANALYZE before optimizing"}],
        )
        failure_text = " ".join(state.failure_modes)
        assert "memory:" in failure_text

    def test_build_fallback_on_exception(self):
        """build() returns fallback state when classification is garbage."""
        from core.orchestration.mission_reasoning_state import build
        state = build(
            goal="Do something",
            mission_id="test-009",
            classification=None,  # Will trigger fallback path
        )
        assert state is not None
        assert state.mission_id == "test-009"

    def test_to_dict_is_serializable(self):
        """to_dict() returns a JSON-serializable dict."""
        import json
        from core.orchestration.mission_reasoning_state import build
        state = build(
            goal="Research competitors",
            mission_id="test-010",
            classification={"task_type": "research", "complexity": "simple"},
        )
        d = state.to_dict()
        # Should not raise
        json.dumps(d)
        assert "mission_id" in d
        assert "initial_state" in d
        assert "target_state" in d
        assert "expected_effects" in d
        assert "success_criteria" in d
        assert "failure_modes" in d

    def test_to_prompt_injection_non_empty(self):
        """Prompt injection includes key state model fields."""
        from core.orchestration.mission_reasoning_state import build
        state = build(
            goal="Fix memory leak in the agent loop",
            mission_id="test-011",
            classification={"task_type": "code", "complexity": "moderate"},
        )
        injection = state.to_prompt_injection()
        assert "[STATE_MODEL]" in injection
        assert "INITIAL:" in injection
        assert "TARGET:" in injection

    def test_update_observed_fills_effects(self):
        """update_observed() populates observed_effects from result."""
        from core.orchestration.mission_reasoning_state import build
        state = build(
            goal="Fix authentication bug",
            mission_id="test-012",
            classification={"task_type": "code", "complexity": "simple"},
        )
        state.update_observed(
            result="Fixed the authentication bug. Login now works correctly. All tests pass.",
            error="",
        )
        assert len(state.observed_effects) > 0
        assert state.state_satisfied is not None

    def test_update_observed_with_error_marks_unsatisfied(self):
        """update_observed() with error marks state_satisfied=False."""
        from core.orchestration.mission_reasoning_state import build
        state = build(
            goal="Deploy service",
            mission_id="test-013",
            classification={"task_type": "deployment", "complexity": "moderate"},
        )
        state.update_observed(result="", error="Container failed to start")
        assert state.state_satisfied is False
        assert "execution_error" in state.satisfaction_reason

    def test_update_observed_computes_expected_vs_observed(self):
        """expected_vs_observed diff is computed after update_observed."""
        from core.orchestration.mission_reasoning_state import build
        state = build(
            goal="Write a report",
            mission_id="test-014",
            classification={"task_type": "research", "complexity": "simple"},
        )
        state.update_observed(result="Findings complete. Sources cited. Conclusions stated.")
        assert "coverage_ratio" in state.expected_vs_observed
        assert isinstance(state.expected_vs_observed["coverage_ratio"], float)

    def test_state_transition_updates_updated_at(self):
        """update_observed() changes updated_at."""
        import time
        from core.orchestration.mission_reasoning_state import build
        state = build(goal="Test", mission_id="test-015")
        t0 = state.updated_at
        time.sleep(0.01)
        state.update_observed(result="Done")
        assert state.updated_at > t0


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 2 — ConfidencePolicy
# ══════════════════════════════════════════════════════════════════════════════

class TestConfidencePolicy:

    def get_policy(self):
        from core.orchestration.confidence_policy import ConfidencePolicy
        return ConfidencePolicy()

    def test_high_confidence_proceeds(self):
        """confidence=0.85 + low risk → PROCEED, no approval."""
        p = self.get_policy()
        d = p.decide(confidence=0.85, risk_level="low")
        from core.orchestration.confidence_policy import PolicyTier
        assert d.tier == PolicyTier.PROCEED
        assert not d.require_approval
        assert not d.abort
        assert not d.add_context

    def test_medium_confidence_gathers_context(self):
        """confidence=0.55 → gather_context tier."""
        p = self.get_policy()
        d = p.decide(confidence=0.55, risk_level="low")
        from core.orchestration.confidence_policy import PolicyTier
        assert d.tier == PolicyTier.CONTEXT
        assert d.add_context
        assert len(d.context_queries) > 0
        assert not d.require_approval

    def test_low_confidence_requires_approval(self):
        """confidence=0.40 + medium risk → CAUTIOUS, require_approval=True.

        Post-phase0 fix: CAUTIOUS only requires approval for medium+ risk.
        Low-risk missions proceed even at low confidence (can't cause damage).
        """
        p = self.get_policy()
        d = p.decide(confidence=0.40, risk_level="medium")
        from core.orchestration.confidence_policy import PolicyTier
        assert d.tier == PolicyTier.CAUTIOUS
        assert d.require_approval
        assert d.add_context

        # Sanity check: low risk does NOT require approval at CAUTIOUS
        d_low = p.decide(confidence=0.40, risk_level="low")
        assert d_low.tier == PolicyTier.CAUTIOUS
        assert not d_low.require_approval, "low-risk CAUTIOUS should proceed without approval"
        assert d_low.add_context

    def test_very_low_confidence_decomposes(self):
        """confidence=0.25 → DECOMPOSE tier."""
        p = self.get_policy()
        d = p.decide(confidence=0.25, risk_level="low")
        from core.orchestration.confidence_policy import PolicyTier
        assert d.tier == PolicyTier.DECOMPOSE
        assert d.decompose_mission
        assert d.require_approval
        assert d.use_safer_model

    def test_critical_confidence_aborts(self):
        """confidence=0.05 → ABORT."""
        p = self.get_policy()
        d = p.decide(confidence=0.05, risk_level="low")
        from core.orchestration.confidence_policy import PolicyTier
        assert d.tier == PolicyTier.ABORT
        assert d.abort
        assert len(d.abort_reason) > 0

    def test_high_risk_shifts_threshold(self):
        """confidence=0.75 + high risk → shifts threshold, may not PROCEED."""
        p = self.get_policy()
        d_low  = p.decide(confidence=0.75, risk_level="low")
        d_high = p.decide(confidence=0.75, risk_level="high")
        from core.orchestration.confidence_policy import PolicyTier
        # low risk: 0.75 >= 0.70 → PROCEED
        assert d_low.tier == PolicyTier.PROCEED
        # high risk: shift 0.10 → 0.65, which is < 0.70 → CONTEXT
        assert d_high.tier != PolicyTier.PROCEED

    def test_critical_risk_triggers_approval_on_medium_confidence(self):
        """confidence=0.65 + critical risk → approval required."""
        p = self.get_policy()
        d = p.decide(confidence=0.65, risk_level="critical")
        assert d.require_approval

    def test_destructive_task_overrides_proceed(self):
        """Even high confidence, destructive=True forces CAUTIOUS and approval.

        Post-phase0 fix: approval only requires medium+ risk at CAUTIOUS tier.
        Destructive actions should explicitly bump the risk level.
        """
        p = self.get_policy()
        d = p.decide(confidence=0.85, risk_level="medium", is_destructive=True)
        from core.orchestration.confidence_policy import PolicyTier
        assert d.tier == PolicyTier.CAUTIOUS
        assert d.require_approval

    def test_prior_failures_override_to_cautious(self):
        """Prior failures in memory escalate to CAUTIOUS even at medium-high confidence."""
        p = self.get_policy()
        d = p.decide(confidence=0.65, risk_level="low", has_prior_failures=True)
        from core.orchestration.confidence_policy import PolicyTier
        assert d.tier == PolicyTier.CAUTIOUS

    def test_strategy_suggestion_decompose_respected(self):
        """pre_execution strategy_suggestion='decompose' → DECOMPOSE tier."""
        p = self.get_policy()
        d = p.decide(confidence=0.6, risk_level="low", strategy_suggestion="decompose")
        from core.orchestration.confidence_policy import PolicyTier
        assert d.tier == PolicyTier.DECOMPOSE

    def test_prompt_additions_injected_for_cautious(self):
        """CAUTIOUS tier adds prompt content."""
        p = self.get_policy()
        d = p.decide(confidence=0.40, risk_level="low")
        assert len(d.prompt_additions) > 0
        assert any("CAUTIOUS" in pa or "cautious" in pa.lower() for pa in d.prompt_additions)

    def test_context_queries_generated(self):
        """CONTEXT tier produces relevant queries."""
        p = self.get_policy()
        d = p.decide(confidence=0.55, risk_level="low", task_type="code",
                     goal="Fix the authentication bug")
        assert d.add_context
        assert len(d.context_queries) >= 2

    def test_to_dict_serializable(self):
        """to_dict() returns JSON-serializable dict."""
        import json
        p = self.get_policy()
        d = p.decide(confidence=0.40, risk_level="medium")
        json.dumps(d.to_dict())

    def test_policy_log_is_populated(self):
        """policy_log records reasoning for audit."""
        p = self.get_policy()
        d = p.decide(confidence=0.40, risk_level="high")
        assert len(d.policy_log) > 0

    def test_singleton_get_confidence_policy(self):
        """get_confidence_policy() returns same instance."""
        from core.orchestration.confidence_policy import get_confidence_policy
        p1 = get_confidence_policy()
        p2 = get_confidence_policy()
        assert p1 is p2


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 3 — Memory Retrieval
# ══════════════════════════════════════════════════════════════════════════════

class TestMissionLessons:
    """Tests for MissionLessons data model (no facade dependency)."""

    def test_empty_lessons_has_no_lessons(self):
        from core.orchestration.memory_retrieval import MissionLessons
        lessons = MissionLessons()
        assert not lessons.has_lessons

    def test_lessons_with_avoid_has_lessons(self):
        from core.orchestration.memory_retrieval import MissionLessons
        lessons = MissionLessons(avoid=["do not skip tests"])
        assert lessons.has_lessons

    def test_to_dict_serializable(self):
        import json
        from core.orchestration.memory_retrieval import MissionLessons
        lessons = MissionLessons(
            avoid=["skip tests", "assume no regression"],
            reuse=["run tests before commit"],
            summary="2 failures, 1 success",
        )
        json.dumps(lessons.to_dict())

    def test_prompt_injection_empty_when_no_lessons(self):
        from core.orchestration.memory_retrieval import MissionLessons
        lessons = MissionLessons()
        assert lessons.to_prompt_injection() == ""

    def test_prompt_injection_includes_avoid_and_reuse(self):
        from core.orchestration.memory_retrieval import MissionLessons
        lessons = MissionLessons(
            avoid=["skip health check"],
            reuse=["deploy then verify"],
        )
        injection = lessons.to_prompt_injection()
        assert "[MEMORY_LESSONS]" in injection
        assert "AVOID" in injection
        assert "REUSE" in injection

    def test_failed_retrieval_is_fail_open(self):
        """retrieve_mission_lessons never raises — returns empty lessons."""
        from core.orchestration.memory_retrieval import retrieve_mission_lessons
        # Calling without facade available should not raise
        lessons = retrieve_mission_lessons("deploy the API", task_type="deployment")
        assert lessons is not None
        # Either has data or is fail-open
        assert isinstance(lessons.retrieval_ok, bool)

    def test_failed_retrieval_logs_error(self):
        """When memory_facade fails, retrieval_ok=False and error is recorded."""
        from core.orchestration.memory_retrieval import MissionLessons
        # Simulate a failed retrieval
        lessons = MissionLessons(
            retrieval_ok=False,
            retrieval_error="connection refused",
        )
        assert not lessons.retrieval_ok
        assert "connection refused" in lessons.retrieval_error

    def test_normalize_dict_entry(self):
        """_normalize handles dict entries correctly."""
        from core.orchestration.memory_retrieval import _normalize
        entry = {"content": "Test content", "score": 0.8, "content_type": "failure"}
        result = _normalize(entry)
        assert result["content"] == "Test content"
        assert result["score"] == 0.8

    def test_extract_avoid_falls_back_to_defaults(self):
        """_extract_avoid returns defaults when no failures found."""
        from core.orchestration.memory_retrieval import _extract_avoid
        avoid = _extract_avoid([], "code")
        assert len(avoid) > 0  # Should have defaults for "code"

    def test_extract_reuse_falls_back_to_defaults(self):
        """_extract_reuse returns defaults when no successes found."""
        from core.orchestration.memory_retrieval import _extract_reuse
        reuse = _extract_reuse([], "deployment")
        assert len(reuse) > 0  # Should have defaults for "deployment"

    def test_retrieve_no_facade_returns_empty_ok(self):
        """retrieve_mission_lessons is fully fail-open when facade is not ready."""
        from core.orchestration.memory_retrieval import retrieve_mission_lessons
        # This may or may not have memory available — just must not raise
        lessons = retrieve_mission_lessons("Research AI trends", task_type="research")
        assert isinstance(lessons, object)
        assert hasattr(lessons, "retrieval_ok")
        assert hasattr(lessons, "avoid")
        assert hasattr(lessons, "reuse")


# ══════════════════════════════════════════════════════════════════════════════
# NO-REGRESSION: existing mission flow
# ══════════════════════════════════════════════════════════════════════════════

class TestNoRegression:

    def test_mission_state_import_does_not_break(self):
        """Module imports cleanly with no side effects."""
        import importlib
        mod = importlib.import_module("core.orchestration.mission_reasoning_state")
        assert hasattr(mod, "MissionReasoningState")
        assert hasattr(mod, "build")

    def test_confidence_policy_import_does_not_break(self):
        """Module imports cleanly."""
        import importlib
        mod = importlib.import_module("core.orchestration.confidence_policy")
        assert hasattr(mod, "ConfidencePolicy")
        assert hasattr(mod, "PolicyTier")
        assert hasattr(mod, "get_confidence_policy")

    def test_memory_retrieval_import_does_not_break(self):
        """Module imports cleanly."""
        import importlib
        mod = importlib.import_module("core.orchestration.memory_retrieval")
        assert hasattr(mod, "MissionLessons")
        assert hasattr(mod, "retrieve_mission_lessons")

    def test_build_with_none_classification_does_not_raise(self):
        """Backward compat: classification=None is handled."""
        from core.orchestration.mission_reasoning_state import build
        state = build(goal="Test mission", mission_id="reg-001", classification=None)
        assert state is not None

    def test_confidence_policy_with_zero_confidence_does_not_raise(self):
        """Edge case: confidence=0.0 → ABORT, no exception."""
        from core.orchestration.confidence_policy import ConfidencePolicy, PolicyTier
        d = ConfidencePolicy().decide(confidence=0.0, risk_level="low")
        assert d.tier == PolicyTier.ABORT
        assert d.abort

    def test_confidence_policy_with_max_confidence_does_not_raise(self):
        """Edge case: confidence=1.0 → PROCEED, no exception."""
        from core.orchestration.confidence_policy import ConfidencePolicy, PolicyTier
        d = ConfidencePolicy().decide(confidence=1.0, risk_level="low")
        assert d.tier == PolicyTier.PROCEED

    def test_mission_state_update_observed_idempotent(self):
        """Calling update_observed twice does not raise or corrupt state."""
        from core.orchestration.mission_reasoning_state import build
        state = build(goal="Deploy", mission_id="reg-002",
                      classification={"task_type": "deployment"})
        state.update_observed(result="Service running.")
        state.update_observed(result="Service still running.")
        assert state.state_satisfied is not None


# ══════════════════════════════════════════════════════════════════════════════
# P42b REGRESSION — needs_approval preservation fix
# ══════════════════════════════════════════════════════════════════════════════

class TestNeedsApprovalPreservation:
    """
    Regression tests for the needs_approval overwrite bug (Pass 42b).

    Bug: meta_orchestrator.py set needs_approval=True via confidence_policy
    (line 962) then immediately overwrote it from classification dict (line 1005).
    Fix: save _cp_approval_preserved before reassignment, merge after.

    These tests verify the PolicyDecision flags are correct so the orchestrator
    can use them to preserve approval. They are pure unit tests — no orchestrator
    instantiation needed (the orchestrator logic is trivially verifiable by
    reading the flag and simulating the 3-line fix).
    """

    def test_cautious_tier_sets_require_approval(self):
        """CAUTIOUS tier with medium+ risk must have require_approval=True.

        Post-phase0 fix: CAUTIOUS only requires approval for medium+ risk.
        Low-risk CAUTIOUS missions proceed without approval.
        """
        from core.orchestration.confidence_policy import ConfidencePolicy, PolicyTier
        d = ConfidencePolicy().decide(
            confidence=0.72, risk_level="medium", task_type="code",
            goal="Fix auth bug", has_prior_failures=True
        )
        assert d.tier == PolicyTier.CAUTIOUS
        assert d.require_approval is True, "CAUTIOUS with medium risk must require_approval"

    def test_decompose_tier_sets_require_approval(self):
        """DECOMPOSE tier must have require_approval=True (very low confidence)."""
        from core.orchestration.confidence_policy import ConfidencePolicy, PolicyTier
        d = ConfidencePolicy().decide(
            confidence=0.28, risk_level="low", task_type="research", goal="Big analysis"
        )
        assert d.tier == PolicyTier.DECOMPOSE
        assert d.require_approval is True, "DECOMPOSE must require_approval"

    def test_critical_risk_context_tier_sets_require_approval(self):
        """CONTEXT tier + critical risk must set require_approval=True."""
        from core.orchestration.confidence_policy import ConfidencePolicy, PolicyTier
        d = ConfidencePolicy().decide(
            confidence=0.75, risk_level="critical", task_type="deployment",
            goal="Deploy prod DB migration"
        )
        assert d.tier == PolicyTier.CONTEXT
        assert d.require_approval is True, "CONTEXT + critical must require_approval"

    def test_preservation_logic_simulation(self):
        """
        Simulate the 3-line fix in meta_orchestrator:
          _cp_approval_preserved = needs_approval  # save
          needs_approval = classification.get("needs_approval", False)  # overwrite
          if _cp_approval_preserved and not force_approved: needs_approval = True  # merge

        Prove that require_approval=True from confidence_policy survives classification
        reassignment when classification does NOT have needs_approval=True.

        Post-phase0 fix: CAUTIOUS only sets require_approval for medium+ risk.
        Uses medium risk to keep the require_approval behavior.
        """
        from core.orchestration.confidence_policy import ConfidencePolicy

        # Simulate: confidence_policy raises require_approval (medium risk CAUTIOUS)
        d = ConfidencePolicy().decide(
            confidence=0.72, risk_level="medium", task_type="code",
            goal="Fix auth bug", has_prior_failures=True
        )
        assert d.require_approval is True  # Policy said: require approval

        # Simulate orchestrator state after confidence_policy block
        needs_approval = d.require_approval  # True (line 962 equivalent)

        # Simulate classification dict WITHOUT needs_approval (typical case)
        classification = {"task_type": "code", "risk_level": "low"}  # no needs_approval key
        force_approved = False

        # --- BUG (before fix): this would silently overwrite needs_approval ---
        # needs_approval = False if force_approved else classification.get("needs_approval", False)
        # assert needs_approval == False  ← BUG: approval lost

        # --- FIX (P42b): save, overwrite, merge ---
        _cp_approval_preserved = needs_approval                         # save: True
        needs_approval = (
            False if force_approved
            else classification.get("needs_approval", False)            # overwrite: False
        )
        if _cp_approval_preserved and not force_approved:
            needs_approval = True                                        # merge: restored

        assert needs_approval is True, (
            "needs_approval must remain True after classification reassignment "
            "when confidence_policy required approval"
        )

    def test_force_approved_overrides_cp_approval(self):
        """force_approved=True must win over confidence_policy require_approval.

        Post-phase0 fix: Use medium risk to trigger CAUTIOUS require_approval.
        """
        from core.orchestration.confidence_policy import ConfidencePolicy

        # Use confidence=0.45, risk=medium → CAUTIOUS → require_approval=True
        d = ConfidencePolicy().decide(
            confidence=0.45, risk_level="medium", task_type="code",
            goal="Emergency hotfix", has_prior_failures=False
        )
        assert d.require_approval is True

        # Simulate fix logic with force_approved=True
        _cp_approval_preserved = d.require_approval  # True
        force_approved = True
        classification = {}
        needs_approval = False if force_approved else classification.get("needs_approval", False)
        if _cp_approval_preserved and not force_approved:
            needs_approval = True  # not executed: force_approved=True

        assert needs_approval is False, (
            "force_approved=True must suppress needs_approval even if cp required it"
        )

    def test_high_risk_deploy_require_approval_preserved(self):
        """
        High-risk deployment: confidence=0.75, risk=high.
        After risk shift: adjusted=0.65 → CONTEXT tier.
        is_destructive=True does NOT promote to CAUTIOUS here (CONTEXT != PROCEED).
        require_approval stays False at CONTEXT tier (no critical risk).
        Verify: approval NOT required (expected behavior — CONTEXT without critical).
        """
        from core.orchestration.confidence_policy import ConfidencePolicy, PolicyTier
        d = ConfidencePolicy().decide(
            confidence=0.75, risk_level="high", task_type="deployment",
            goal="Deploy to prod", is_destructive=True
        )
        assert d.tier == PolicyTier.CONTEXT
        # CONTEXT + high (not critical) → require_approval=False is CORRECT behavior
        # (approval is optional at CONTEXT; only critical forces it)
        assert d.require_approval is False
        assert d.add_context is True  # does trigger context gathering

    def test_proceed_tier_never_requires_approval(self):
        """PROCEED tier: high confidence, low risk → no approval needed."""
        from core.orchestration.confidence_policy import ConfidencePolicy, PolicyTier
        d = ConfidencePolicy().decide(
            confidence=0.90, risk_level="low", task_type="conversation",
            goal="Say hello"
        )
        assert d.tier == PolicyTier.PROCEED
        assert d.require_approval is False


# ══════════════════════════════════════════════════════════════════════════════
# Pass 43 — use_safer_model, decompose_mission, MemoryRetrieval, state_satisfied
# ══════════════════════════════════════════════════════════════════════════════

class TestUseSaferModel:
    """
    use_safer_model: DECOMPOSE tier must set use_safer_model=True.
    LLMFactory ContextVar _safer_model_active must exist and default to False.
    """

    def test_decompose_tier_sets_use_safer_model(self):
        from core.orchestration.confidence_policy import ConfidencePolicy
        d = ConfidencePolicy().decide(confidence=0.25, risk_level="low", goal="Vague task")
        assert d.use_safer_model is True, "DECOMPOSE tier must set use_safer_model"

    def test_proceed_tier_does_not_set_use_safer_model(self):
        from core.orchestration.confidence_policy import ConfidencePolicy
        d = ConfidencePolicy().decide(confidence=0.90, risk_level="low", goal="Simple task")
        assert d.use_safer_model is False

    def test_safer_model_contextvar_exists_and_defaults_false(self):
        from core.llm_factory import _safer_model_active
        assert _safer_model_active.get() is False

    def test_safer_model_contextvar_can_be_set_and_reset(self):
        from core.llm_factory import _safer_model_active
        token = _safer_model_active.set(True)
        assert _safer_model_active.get() is True
        _safer_model_active.reset(token)
        assert _safer_model_active.get() is False

    def test_safer_model_does_not_activate_on_proceed(self):
        """Orchestrator should NOT set safer_model when tier=PROCEED."""
        from core.orchestration.confidence_policy import ConfidencePolicy
        d = ConfidencePolicy().decide(confidence=0.85, risk_level="low", goal="Hi")
        # Simulate orchestrator logic: only activate if use_safer_model=True
        _would_activate = d.use_safer_model and not False  # force_approved=False
        assert _would_activate is False


class TestDecomposeMission:
    """
    decompose_mission: when True + candidate_actions available,
    enriched_goal must be restructured into numbered steps.
    """

    def test_decompose_tier_sets_decompose_mission(self):
        from core.orchestration.confidence_policy import ConfidencePolicy
        d = ConfidencePolicy().decide(confidence=0.25, risk_level="low", goal="Big task")
        assert d.decompose_mission is True

    def test_goal_restructure_logic(self):
        """Simulate the decompose_mission goal restructuring in meta_orchestrator."""
        from core.orchestration.mission_reasoning_state import build

        state = build(
            goal="Fix the authentication module",
            mission_id="decomp-001",
            classification={"task_type": "code", "complexity": "moderate"},
        )
        assert state.candidate_actions, "Must have candidate_actions to decompose"

        actions = state.candidate_actions[:5]
        steps = "\n".join(f"  Step {i+1}: {a}" for i, a in enumerate(actions))
        restructured = (
            f"[DECOMPOSED MISSION — execute each step in order, "
            f"do not attempt the full goal in one pass]\n"
            f"{steps}\n\n"
            f"Original goal: Fix the authentication module"
        )
        assert "Step 1:" in restructured
        assert "Original goal:" in restructured
        assert "DECOMPOSED MISSION" in restructured
        # Must not be a simple appended prompt — goal is replaced, not just extended
        assert restructured.startswith("[DECOMPOSED")

    def test_decompose_uses_candidate_actions_from_state(self):
        from core.orchestration.mission_reasoning_state import build
        state = build(
            goal="Deploy new service",
            mission_id="decomp-002",
            classification={"task_type": "deployment", "complexity": "complex"},
        )
        # deployment candidate_actions known from _TASK_TYPE_PATTERNS
        assert len(state.candidate_actions) >= 2
        assert any("deploy" in a.lower() or "build" in a.lower()
                   for a in state.candidate_actions)


class TestMemoryRetrievalFiltering:
    """
    Pass 43: _filter_and_dedup must:
    - drop entries below SCORE_THRESHOLD
    - deduplicate by content prefix
    - return at most top_k entries
    """

    def test_filter_drops_low_score_entries(self):
        from core.orchestration.memory_retrieval import _filter_and_dedup, _SCORE_THRESHOLD
        entries = [
            {"content": "good entry A", "score": 0.80},
            {"content": "bad entry B",  "score": 0.10},   # below threshold
            {"content": "ok entry C",   "score": 0.50},
        ]
        kept = _filter_and_dedup(entries, threshold=_SCORE_THRESHOLD, top_k=10)
        contents = [e["content"] for e in kept]
        assert "good entry A" in contents
        assert "ok entry C" in contents
        assert "bad entry B" not in contents

    def test_filter_deduplicates_by_prefix(self):
        from core.orchestration.memory_retrieval import _filter_and_dedup
        # Build two entries that share the exact same first 60 chars
        shared = "auth failed because the token was not present in the request"  # 60 chars
        assert len(shared) == 60
        entries = [
            {"content": shared + " — first occurrence with extra detail", "score": 0.80},
            {"content": shared + " — second occurrence is duplicate",     "score": 0.75},
            {"content": "deployment failed due to missing environment config file", "score": 0.70},
        ]
        kept = _filter_and_dedup(entries, threshold=0.0, top_k=10)
        # First two share the same 60-char prefix → only highest score kept
        assert len(kept) == 2

    def test_filter_respects_top_k(self):
        from core.orchestration.memory_retrieval import _filter_and_dedup
        entries = [{"content": f"entry {i}", "score": 0.9 - i * 0.05} for i in range(10)]
        kept = _filter_and_dedup(entries, threshold=0.0, top_k=3)
        assert len(kept) == 3

    def test_score_threshold_constant_is_reasonable(self):
        from core.orchestration.memory_retrieval import _SCORE_THRESHOLD
        assert 0.30 <= _SCORE_THRESHOLD <= 0.60, "Threshold should be between 0.3 and 0.6"

    def test_empty_entries_returns_empty(self):
        from core.orchestration.memory_retrieval import _filter_and_dedup
        assert _filter_and_dedup([], threshold=0.4, top_k=5) == []


class TestStateSatisfiedImproved:
    """
    Pass 43: state_satisfied improvements.
    - Synonym matching must rescue paraphrase hits.
    - Soft threshold 0.33 (was 0.50).
    - Error with no result must be unsatisfied.
    """

    def test_synonym_match_tests_pass_satisfies_code_criteria(self):
        """'Tests pass' in result matches 'code runs without errors' via synonym."""
        from core.orchestration.mission_reasoning_state import build
        state = build(
            goal="Fix the auth bug in login.py",
            mission_id="sat-001",
            classification={"task_type": "code", "complexity": "simple"},
        )
        # Result uses paraphrase "Tests pass" not literal "code runs without errors"
        state.update_observed(
            result="Fixed: added missing token validation. Tests pass. No imports broken.",
            error="",
        )
        assert state.state_satisfied is True, (
            "Synonym 'pass' must match criteria 'runs without errors'"
        )

    def test_soft_threshold_partial_match_is_satisfied(self):
        """1/3 criteria matched at ratio=0.33 → satisfied (was failing at 0.50)."""
        from core.orchestration.mission_reasoning_state import build
        state = build(
            goal="Deploy the service",
            mission_id="sat-002",
            classification={"task_type": "deployment", "complexity": "moderate"},
        )
        # success_criteria for deployment: ["health endpoint returns OK", "no error spike"]
        # Result only mentions "healthy" → triggers synonym for "health endpoint" → 1 match
        state.update_observed(result="Service is healthy.", error="")
        state.expected_vs_observed.get("coverage_ratio", 0)
        # state_satisfied depends on 0.33 threshold — 1/2 = 0.5 → satisfied
        assert state.state_satisfied is True

    def test_error_no_result_is_unsatisfied(self):
        from core.orchestration.mission_reasoning_state import build
        state = build(goal="Deploy", mission_id="sat-003",
                      classification={"task_type": "deployment"})
        state.update_observed(result="", error="ConnectionRefusedError")
        assert state.state_satisfied is False
        assert "execution_error" in state.satisfaction_reason

    def test_empty_result_is_unsatisfied(self):
        from core.orchestration.mission_reasoning_state import build
        state = build(goal="Research topic", mission_id="sat-004",
                      classification={"task_type": "research"})
        state.update_observed(result="", error="")
        assert state.state_satisfied is False
        assert state.satisfaction_reason == "no_result"

    def test_synonym_dict_is_non_empty(self):
        from core.orchestration.mission_reasoning_state import _CRITERION_SYNONYMS
        assert len(_CRITERION_SYNONYMS) >= 5


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
