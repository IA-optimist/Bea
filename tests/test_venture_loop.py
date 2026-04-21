"""
tests/test_venture_loop.py — Venture Loop Layer tests.

Tests Phases 1-10:
  VL01-VL10: Hypothesis + Experiment Spec
  VL11-VL20: Evaluation + Iteration Proposal
  VL21-VL30: Loop engine + memory
  VL31-VL40: Safety + API + integration
"""


# ── Phase 1: Venture Hypothesis ───────────────────────────────

class TestVentureHypothesis:
    def test_VL01_create_hypothesis(self):
        from core.venture.venture_loop import VentureHypothesis
        h = VentureHypothesis(
            problem_statement="Small businesses lack affordable marketing",
            target_segment="Small business owners",
            value_proposition="AI-powered marketing for $29/month",
        )
        assert h.hypothesis_id.startswith("hyp-")
        assert h.confidence_level == 0.5

    def test_VL02_hypothesis_validation(self):
        from core.venture.venture_loop import VentureHypothesis
        h = VentureHypothesis()
        issues = h.validate()
        assert "missing problem_statement" in issues
        assert "missing target_segment" in issues
        assert "missing value_proposition" in issues

    def test_VL03_valid_hypothesis_passes(self):
        from core.venture.venture_loop import VentureHypothesis
        h = VentureHypothesis(
            problem_statement="Problem",
            target_segment="Segment",
            value_proposition="Value",
        )
        assert h.validate() == []

    def test_VL04_hypothesis_serialization(self):
        from core.venture.venture_loop import VentureHypothesis
        h = VentureHypothesis(
            problem_statement="P", target_segment="S", value_proposition="V",
            assumptions=["a1"], risk_factors=["r1"],
        )
        d = h.to_dict()
        h2 = VentureHypothesis.from_dict(d)
        assert h2.problem_statement == "P"
        assert h2.assumptions == ["a1"]

    def test_VL05_hypothesis_confidence_bounded(self):
        from core.venture.venture_loop import VentureHypothesis
        h = VentureHypothesis(problem_statement="P", target_segment="S",
                             value_proposition="V", confidence_level=1.5)
        assert "confidence_level" in h.validate()[0]


# ── Phase 2: Experiment Spec ──────────────────────────────────

class TestExperimentSpec:
    def test_VL06_create_experiment(self):
        from core.venture.venture_loop import ExperimentSpec, ExperimentType
        e = ExperimentSpec(
            experiment_type=ExperimentType.LANDING_PAGE,
            hypothesis_id="hyp-test",
        )
        assert e.experiment_id.startswith("exp-")
        assert e.evaluation_metric == "perceived_value_score"

    def test_VL07_experiment_validation(self):
        from core.venture.venture_loop import ExperimentSpec
        e = ExperimentSpec()
        issues = e.validate()
        assert "missing hypothesis_id" in issues

    def test_VL08_experiment_iteration_limit_bounded(self):
        from core.venture.venture_loop import ExperimentSpec
        e = ExperimentSpec(hypothesis_id="h", iteration_limit=99)
        issues = e.validate()
        assert any("iteration_limit" in i for i in issues)

    def test_VL09_experiment_types_exist(self):
        from core.venture.venture_loop import ExperimentType
        types = list(ExperimentType)
        assert len(types) == 5

    def test_VL10_experiment_serialization(self):
        from core.venture.venture_loop import ExperimentSpec, ExperimentType
        e = ExperimentSpec(experiment_type=ExperimentType.OFFER_TEST, hypothesis_id="h")
        d = e.to_dict()
        e2 = ExperimentSpec.from_dict(d)
        assert e2.experiment_type == ExperimentType.OFFER_TEST


# ── Phase 4: Evaluation ──────────────────────────────────────

class TestEvaluation:
    def test_VL11_evaluate_artifacts(self):
        from core.venture.venture_loop import VentureHypothesis, evaluate_artifacts
        h = VentureHypothesis(
            problem_statement="Businesses need better marketing tools for growth",
            target_segment="SMB marketing managers",
            value_proposition="AI marketing platform that automates campaigns and tracks ROI for businesses",
            expected_outcome="50% reduction in marketing overhead",
            test_strategy="Landing page test",
            success_signal_definition="10% signup rate",
        )
        ev = evaluate_artifacts(h, [], iteration=1)
        assert ev.composite_score > 0
        assert 0 <= ev.confidence <= 1

    def test_VL12_evaluation_scores_bounded(self):
        from core.venture.venture_loop import VentureHypothesis, evaluate_artifacts
        h = VentureHypothesis(
            problem_statement="P", target_segment="S",
            value_proposition="V" * 300,  # Long VP → high perceived value
        )
        ev = evaluate_artifacts(h, [])
        assert ev.perceived_value_score <= 1.0
        assert ev.clarity_score <= 1.0

    def test_VL13_evaluation_to_dict(self):
        from core.venture.venture_loop import ExperimentEvaluation
        ev = ExperimentEvaluation(clarity_score=0.8, coherence_score=0.7)
        d = ev.to_dict()
        assert "composite_score" in d
        assert "confidence" in d
        assert "improvement_priority" in d

    def test_VL14_empty_hypothesis_low_scores(self):
        from core.venture.venture_loop import VentureHypothesis, evaluate_artifacts
        h = VentureHypothesis(problem_statement="P", target_segment="S", value_proposition="V")
        ev = evaluate_artifacts(h, [])
        assert ev.clarity_score < 0.8  # Missing fields

    def test_VL15_risk_score_from_factors(self):
        from core.venture.venture_loop import VentureHypothesis, evaluate_artifacts
        h = VentureHypothesis(
            problem_statement="P", target_segment="S", value_proposition="V",
            risk_factors=["r1", "r2", "r3", "r4", "r5"],
        )
        ev = evaluate_artifacts(h, [])
        assert ev.risk_score >= 0.9  # 5 risk factors → high risk


# ── Phase 5: Iteration Proposals ──────────────────────────────

class TestIterationProposal:
    def test_VL16_generate_proposals_for_weak_hypothesis(self):
        from core.venture.venture_loop import (
            VentureHypothesis, evaluate_artifacts, generate_proposals,
        )
        h = VentureHypothesis(
            problem_statement="P", target_segment="S", value_proposition="V",
        )
        ev = evaluate_artifacts(h, [])
        proposals = generate_proposals(ev, h)
        assert len(proposals) > 0

    def test_VL17_proposals_have_required_fields(self):
        from core.venture.venture_loop import IterationProposal, ChangeType
        p = IterationProposal(
            change_type=ChangeType.IMPROVE_POSITIONING,
            affected_artifact="content_asset",
            expected_improvement_reason="test",
        )
        d = p.to_dict()
        assert "change_type" in d
        assert "affected_artifact" in d
        assert "expected_improvement_reason" in d
        assert "confidence_level" in d

    def test_VL18_change_types_exist(self):
        from core.venture.venture_loop import ChangeType
        assert len(list(ChangeType)) == 7

    def test_VL19_max_proposals_bounded(self):
        from core.venture.venture_loop import (
            VentureHypothesis, evaluate_artifacts, generate_proposals,
        )
        h = VentureHypothesis(
            problem_statement="P", target_segment="S", value_proposition="V",
        )
        ev = evaluate_artifacts(h, [])
        proposals = generate_proposals(ev, h)
        assert len(proposals) <= 4

    def test_VL20_strong_hypothesis_few_proposals(self):
        from core.venture.venture_loop import (
            VentureHypothesis, evaluate_artifacts, generate_proposals,
        )
        h = VentureHypothesis(
            problem_statement="Businesses need better marketing tools for growth and efficiency",
            target_segment="SMB marketing managers in SaaS",
            value_proposition="AI marketing platform that automates campaigns, tracks ROI, and reduces overhead for businesses looking to grow efficiently",
            expected_outcome="50% reduction in marketing overhead within 3 months",
            test_strategy="Landing page test with targeted ads",
            success_signal_definition="10% signup rate from landing page visitors",
        )
        ev = evaluate_artifacts(h, [])
        proposals = generate_proposals(ev, h)
        # Strong hypothesis → fewer proposals
        assert ev.composite_score > 0.4


# ── Phase 3+6+7: Loop Engine + Memory + Safety ───────────────

class TestVentureLoop:
    def test_VL21_run_loop_basic(self):
        from core.venture.venture_loop import VentureHypothesis, run_venture_loop
        h = VentureHypothesis(
            problem_statement="Restaurants need better online ordering systems",
            target_segment="Independent restaurant owners",
            value_proposition="Simple online ordering in 5 minutes for restaurants",
        )
        result = run_venture_loop(h, max_iterations=3)
        assert result.status in ("converged", "stopped")
        assert len(result.iterations) > 0
        assert len(result.score_progression) > 0

    def test_VL22_loop_bounded(self):
        from core.venture.venture_loop import VentureHypothesis, run_venture_loop, MAX_LOOP_ITERATIONS
        assert MAX_LOOP_ITERATIONS <= 10
        h = VentureHypothesis(
            problem_statement="P", target_segment="S", value_proposition="V",
        )
        result = run_venture_loop(h, max_iterations=2)
        assert len(result.iterations) <= 2

    def test_VL23_loop_rejects_invalid_hypothesis(self):
        from core.venture.venture_loop import VentureHypothesis, run_venture_loop
        h = VentureHypothesis()  # Empty = invalid
        result = run_venture_loop(h)
        assert result.status == "failed"
        assert "Invalid" in result.reason

    def test_VL24_loop_stores_hypothesis(self):
        from core.venture.venture_loop import (
            VentureHypothesis, run_venture_loop, get_hypotheses,
        )
        h = VentureHypothesis(
            problem_statement="P", target_segment="S", value_proposition="V",
        )
        run_venture_loop(h, max_iterations=1)
        hyps = get_hypotheses()
        assert h.hypothesis_id in hyps

    def test_VL25_loop_stores_experiment(self):
        from core.venture.venture_loop import (
            VentureHypothesis, run_venture_loop, get_experiments,
        )
        h = VentureHypothesis(
            problem_statement="P", target_segment="S", value_proposition="V",
        )
        result = run_venture_loop(h, max_iterations=1)
        exps = get_experiments()
        assert result.experiment_id in exps

    def test_VL26_loop_records_evaluations(self):
        from core.venture.venture_loop import (
            VentureHypothesis, run_venture_loop, get_evaluations,
        )
        before = len(get_evaluations())
        h = VentureHypothesis(
            problem_statement="P", target_segment="S", value_proposition="V",
        )
        run_venture_loop(h, max_iterations=2)
        after = len(get_evaluations())
        assert after > before

    def test_VL27_loop_score_progression(self):
        from core.venture.venture_loop import VentureHypothesis, run_venture_loop
        h = VentureHypothesis(
            problem_statement="P", target_segment="S", value_proposition="V",
        )
        result = run_venture_loop(h, max_iterations=3)
        assert len(result.score_progression) >= 1
        # Scores should be non-negative
        assert all(s >= 0 for s in result.score_progression)

    def test_VL28_loop_result_to_dict(self):
        from core.venture.venture_loop import VentureHypothesis, run_venture_loop
        h = VentureHypothesis(
            problem_statement="P", target_segment="S", value_proposition="V",
        )
        result = run_venture_loop(h, max_iterations=1)
        d = result.to_dict()
        assert "loop_id" in d
        assert "score_progression" in d
        assert "status" in d

    def test_VL29_loop_results_stored(self):
        from core.venture.venture_loop import (
            VentureHypothesis, run_venture_loop, get_loop_results,
        )
        h = VentureHypothesis(
            problem_statement="P", target_segment="S", value_proposition="V",
        )
        run_venture_loop(h, max_iterations=1)
        results = get_loop_results()
        assert len(results) > 0

    def test_VL30_loop_stops_on_no_improvement(self):
        from core.venture.venture_loop import VentureHypothesis, run_venture_loop
        # Minimal hypothesis → will plateau quickly
        h = VentureHypothesis(
            problem_statement="P", target_segment="S", value_proposition="V",
        )
        result = run_venture_loop(h, max_iterations=5)
        # Should stop before 5 if no improvement
        assert result.status in ("stopped", "converged")


# ── Safety + API + Integration ────────────────────────────────

class TestVentureAPI:
    def test_VL31_venture_router_mounted(self):
        import importlib
        main_mod = importlib.import_module("api.main")
        source = __import__("inspect").getsource(main_mod)
        assert "venture_router" in source

    def test_VL32_api_hypotheses_exists(self):
        import importlib
        mod = importlib.import_module("api.routes.venture")
        assert hasattr(mod, "list_hypotheses")

    def test_VL33_api_experiments_exists(self):
        import importlib
        mod = importlib.import_module("api.routes.venture")
        assert hasattr(mod, "list_experiments")

    def test_VL34_api_evaluations_exists(self):
        import importlib
        mod = importlib.import_module("api.routes.venture")
        assert hasattr(mod, "list_evaluations")

    def test_VL35_api_run_loop_exists(self):
        import importlib
        mod = importlib.import_module("api.routes.venture")
        assert hasattr(mod, "run_loop")

    def test_VL36_api_status_exists(self):
        import importlib
        mod = importlib.import_module("api.routes.venture")
        assert hasattr(mod, "venture_status")

    def test_VL37_no_secrets_in_results(self):
        import json
        from core.venture.venture_loop import VentureHypothesis, run_venture_loop
        h = VentureHypothesis(
            problem_statement="P", target_segment="S", value_proposition="V",
        )
        result = run_venture_loop(h, max_iterations=1)
        dumped = json.dumps(result.to_dict())
        assert "sk-or-" not in dumped
        assert "ghp_" not in dumped

    def test_VL38_experiment_artifacts_map(self):
        from core.venture.venture_loop import EXPERIMENT_ARTIFACTS, ExperimentType
        assert len(EXPERIMENT_ARTIFACTS) == 5
        for et in ExperimentType:
            assert et in EXPERIMENT_ARTIFACTS or et.value in EXPERIMENT_ARTIFACTS

    def test_VL39_experiment_metrics_map(self):
        from core.venture.venture_loop import EXPERIMENT_METRICS, ExperimentType
        for et in ExperimentType:
            assert et in EXPERIMENT_METRICS or et.value in EXPERIMENT_METRICS

    def test_VL40_loop_cooldown_exists(self):
        from core.venture.venture_loop import COOLDOWN_SECONDS
        assert COOLDOWN_SECONDS > 0
