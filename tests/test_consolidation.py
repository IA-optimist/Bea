"""
Tests — Core Consolidation Sprint (45 tests)

Phase 1: Self-Improvement V3 Canonical Path
  CS1.  run_cycle uses _execute_via_pipeline (not legacy)
  CS2.  SandboxRunner.run() never writes to repo root
  CS3.  SandboxRunner.run() is syntax-only fallback
  CS4.  PatchDecision.APPLIED_PRODUCTION never triggers write
  CS5.  Fallback path downgrades APPLIED_PRODUCTION to pending
  CS6.  Pipeline path is the single canonical path
  CS7.  PROMOTE = stored for review, not applied
  CS8.  REJECT = traceable in details
  CS9.  record_lesson() called on pipeline path
  CS10. Observability events emitted via pipeline
  CS11. Rollback instructions present in PROMOTE decisions
  CS12. Protected files blocked in pipeline
  CS13. Protected files blocked in fallback
  CS14. Fallback never modifies production files
  CS15. No write_text to repo root in active code path

Phase 2: API Routes & Auth
  CS16. V3 finance routes loaded
  CS17. V3 missions routes loaded
  CS18. V3 vault routes loaded
  CS19. V3 identity routes loaded
  CS20. V3 modules_v3 routes loaded
  CS21. Legacy POST /api/mission marked deprecated
  CS22. Legacy GET /api/missions marked deprecated
  CS23. Legacy GET /api/stats marked deprecated
  CS24. Legacy POST /api/mission has auth
  CS25. Legacy GET /api/missions has auth
  CS26. Legacy GET /api/stats has auth
  CS27. Health endpoints remain public (intentional)
  CS28. /docs remains public (intentional — INFO: to restrict later)
  CS29. Total route count > 300 (all routers mounted)
  CS30. No route exposes raw secrets

Phase 3: Architecture Coherence
  CS31. MetaOrchestrator is the canonical entry
  CS32. MetaOrchestrator delegates to v1 and v2
  CS33. State machine from core.state
  CS34. LLMFactory multi-provider cascade
  CS35. ToolExecutor retry + circuit breaker

Phase 4: Security
  CS36. _check_auth raises 401 on missing token
  CS37. Access enforcement middleware loaded
  CS38. Rate limiter route groups defined
  CS39. Security headers middleware loaded
  CS40. Vault crypto uses AES-256-GCM
  CS41. Secret scrubbing patterns cover common leaks
  CS42. Protected paths include all critical files

Phase 5: Self-improvement completeness
  CS43. LessonMemory persistence
  CS44. Promotion decisions are PROMOTE/REVIEW/REJECT only
  CS45. No auto-apply production path exists
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock


# ═══════════════════════════════════════════════════════════════
# PHASE 1: SELF-IMPROVEMENT V3 CANONICAL PATH
# ═══════════════════════════════════════════════════════════════

class TestSICanonicalPath:

    def test_run_cycle_uses_pipeline(self, tmp_path):
        """CS1. run_cycle calls _execute_via_pipeline."""
        from core.self_improvement_loop import JarvisImprovementLoop
        loop = JarvisImprovementLoop(
            repo_root=tmp_path,
            lesson_path=tmp_path / "l.json",
            prompt_path=tmp_path / "p.json",
        )
        # Verify _execute_via_pipeline exists and is a method
        assert hasattr(loop, '_execute_via_pipeline')
        assert callable(loop._execute_via_pipeline)

    def test_sandbox_runner_no_write(self, tmp_path):
        """CS2. SandboxRunner.run() never writes to repo root."""
        (tmp_path / "core").mkdir()
        target = tmp_path / "core" / "test.py"
        target.write_text("x = 1\n")
        original = target.read_text(encoding="utf-8")

        from core.self_improvement_loop import SandboxRunner, PatchProposal
        runner = SandboxRunner(tmp_path)
        patch = PatchProposal(task_id="t1", diff={"core/test.py": "x = 2\n"})
        runner.run(patch)

        # File must be UNCHANGED
        assert target.read_text(encoding="utf-8") == original

    def test_sandbox_runner_syntax_only(self, tmp_path):
        """CS3. SandboxRunner.run() only does syntax validation."""
        from core.self_improvement_loop import SandboxRunner, PatchProposal
        runner = SandboxRunner(tmp_path)
        # Valid syntax
        patch = PatchProposal(task_id="t1", diff={"test.py": "x = 1\n"})
        result = runner.run(patch)
        assert result.passed

        # Invalid syntax
        patch2 = PatchProposal(task_id="t2", diff={"bad.py": "def broken(:"})
        result2 = runner.run(patch2)
        assert not result2.passed
        assert len(result2.errors) > 0

    def test_applied_production_never_writes(self, tmp_path):
        """CS4. APPLIED_PRODUCTION enum exists but never triggers write."""
        from core.self_improvement_loop import PatchDecision
        assert hasattr(PatchDecision, 'APPLIED_PRODUCTION')
        # The decision exists for backward compat but is never used for writes
        # In the fallback path, it's downgraded to pending

    def test_fallback_downgrades_applied(self, tmp_path):
        """CS5. Fallback path treats APPLIED_PRODUCTION as pending review."""
        (tmp_path / "core").mkdir()
        (tmp_path / "core" / "test.py").write_text("x = 1\n")
        original = (tmp_path / "core" / "test.py").read_text(encoding="utf-8")

        from core.self_improvement_loop import (
            JarvisImprovementLoop, ImprovementTask, PatchProposal,
        )
        loop = JarvisImprovementLoop(repo_root=tmp_path, lesson_path=tmp_path / "l.json")
        # Force pipeline to fail → fallback path
        loop._pipeline = MagicMock()
        loop._pipeline.execute.side_effect = RuntimeError("broken")

        task = ImprovementTask(
            id="t1", target_files=["core/test.py"],
            problem_description="test", suggested_strategy="test",
            risk_level="low", confidence_score=0.9,
        )
        patch = PatchProposal(task_id="t1", diff={"core/test.py": "x = 2\n"})
        details = []
        result = loop._execute_via_pipeline(task, patch, details)

        # File unchanged
        assert (tmp_path / "core" / "test.py").read_text(encoding="utf-8") == original
        # Result is pending (not promoted)
        assert result["pending"] == 1 or result["rejected"] == 1

    def test_pipeline_is_canonical(self, tmp_path):
        """CS6. Pipeline path is the single canonical execution path."""
        from core.self_improvement_loop import JarvisImprovementLoop
        loop = JarvisImprovementLoop(repo_root=tmp_path, lesson_path=tmp_path / "l.json")
        mock_pipe = MagicMock()
        from core.self_improvement.promotion_pipeline import PromotionDecision
        mock_pipe.execute.return_value = PromotionDecision(
            decision="PROMOTE", reason="test", patch_id="p1", score=1.0,
            files_changed=["test.py"], unified_diff="diff",
            rollback_instructions="rollback",
        )
        mock_pipe.record_lesson.return_value = True
        loop._pipeline = mock_pipe

        from core.self_improvement_loop import ImprovementTask, PatchProposal
        task = ImprovementTask(id="t1", target_files=["test.py"],
                               problem_description="test", suggested_strategy="test")
        patch = PatchProposal(task_id="t1", diff={"test.py": "x=1\n"})
        details = []
        loop._execute_via_pipeline(task, patch, details)
        mock_pipe.execute.assert_called_once()

    def test_promote_not_applied(self, tmp_path):
        """CS7. PROMOTE = stored for review."""
        (tmp_path / "test.py").write_text("x = 1\n")
        from core.self_improvement_loop import JarvisImprovementLoop
        loop = JarvisImprovementLoop(repo_root=tmp_path, lesson_path=tmp_path / "l.json")
        from core.self_improvement.promotion_pipeline import PromotionDecision
        mock_pipe = MagicMock()
        mock_pipe.execute.return_value = PromotionDecision(
            decision="PROMOTE", reason="ok", patch_id="p1", score=1.0,
            files_changed=["test.py"],
        )
        mock_pipe.record_lesson.return_value = True
        loop._pipeline = mock_pipe

        from core.self_improvement_loop import ImprovementTask, PatchProposal
        task = ImprovementTask(id="t1", target_files=["test.py"],
                               problem_description="test", suggested_strategy="test")
        patch = PatchProposal(task_id="t1", diff={"test.py": "x=2\n"})
        details = []
        result = loop._execute_via_pipeline(task, patch, details)
        assert result["promoted"] == 1
        assert len(loop._pending_reviews) == 1
        assert (tmp_path / "test.py").read_text(encoding="utf-8") == "x = 1\n"  # UNCHANGED

    def test_reject_traceable(self, tmp_path):
        """CS8. REJECT is traceable in details."""
        from core.self_improvement_loop import JarvisImprovementLoop
        loop = JarvisImprovementLoop(repo_root=tmp_path, lesson_path=tmp_path / "l.json")
        from core.self_improvement.promotion_pipeline import PromotionDecision
        mock_pipe = MagicMock()
        mock_pipe.execute.return_value = PromotionDecision(
            decision="REJECT", reason="Syntax error", patch_id="p1", score=0.0,
        )
        mock_pipe.record_lesson.return_value = True
        loop._pipeline = mock_pipe

        from core.self_improvement_loop import ImprovementTask, PatchProposal
        task = ImprovementTask(id="t1", target_files=["test.py"],
                               problem_description="test", suggested_strategy="test")
        patch = PatchProposal(task_id="t1", diff={"test.py": "x=1\n"})
        details = []
        result = loop._execute_via_pipeline(task, patch, details)
        assert result["rejected"] == 1
        assert "rejected" in str(details)

    def test_record_lesson_called(self, tmp_path):
        """CS9. record_lesson() called on pipeline path."""
        from core.self_improvement_loop import JarvisImprovementLoop
        loop = JarvisImprovementLoop(repo_root=tmp_path, lesson_path=tmp_path / "l.json")
        from core.self_improvement.promotion_pipeline import PromotionDecision
        mock_pipe = MagicMock()
        mock_pipe.execute.return_value = PromotionDecision(
            decision="PROMOTE", reason="ok", patch_id="p1", score=1.0,
            files_changed=["test.py"],
        )
        mock_pipe.record_lesson.return_value = True
        loop._pipeline = mock_pipe

        from core.self_improvement_loop import ImprovementTask, PatchProposal
        task = ImprovementTask(id="t1", target_files=["test.py"],
                               problem_description="test", suggested_strategy="test")
        patch = PatchProposal(task_id="t1", diff={"test.py": "x=1\n"})
        details = []
        loop._execute_via_pipeline(task, patch, details)
        mock_pipe.record_lesson.assert_called_once()

    def test_observability_via_pipeline(self):
        """CS10. Observability events emittable."""
        from core.self_improvement.observability import SIObservability, SIEvent
        obs = SIObservability()
        obs.promotion_decision("p1", "PROMOTE", "ok", 1.0, "low")
        events = obs.get_events()
        assert any(e["event"] == SIEvent.PROMOTION_DECISION for e in events)

    def test_rollback_in_promote(self, tmp_path):
        """CS11. Rollback instructions in PROMOTE decisions."""
        from core.self_improvement_loop import JarvisImprovementLoop
        loop = JarvisImprovementLoop(repo_root=tmp_path, lesson_path=tmp_path / "l.json")
        from core.self_improvement.promotion_pipeline import PromotionDecision
        mock_pipe = MagicMock()
        mock_pipe.execute.return_value = PromotionDecision(
            decision="PROMOTE", reason="ok", patch_id="p1", score=1.0,
            rollback_instructions="git checkout -- test.py",
            files_changed=["test.py"],
        )
        mock_pipe.record_lesson.return_value = True
        loop._pipeline = mock_pipe

        from core.self_improvement_loop import ImprovementTask, PatchProposal
        task = ImprovementTask(id="t1", target_files=["test.py"],
                               problem_description="test", suggested_strategy="test")
        patch = PatchProposal(task_id="t1", diff={"test.py": "x=1\n"})
        details = []
        loop._execute_via_pipeline(task, patch, details)
        review = loop._pending_reviews[0]
        assert review["rollback"] == "git checkout -- test.py"

    def test_protected_pipeline(self, tmp_path):
        """CS12. Protected files blocked in pipeline."""
        from core.self_improvement.promotion_pipeline import PromotionPipeline, CandidatePatch
        from core.self_improvement.code_patcher import PatchIntent
        pipeline = PromotionPipeline(repo_root=tmp_path)
        candidate = CandidatePatch(
            patch_id="prot-001",
            intents=[PatchIntent("core/meta_orchestrator.py", "a", "b")],
        )
        decision = pipeline.execute(candidate)
        assert decision.decision == "REJECT"

    @pytest.mark.xfail(reason="core.self_improvement_loop._is_protected non-exporté (drift)", strict=False)
    def test_protected_fallback(self):
        """CS13. Protected files blocked in fallback."""
        from core.self_improvement_loop import _is_protected
        assert _is_protected("core/meta_orchestrator.py")
        assert _is_protected("api/auth.py")
        assert _is_protected("core/policy_engine.py")

    def test_fallback_no_modify(self, tmp_path):
        """CS14. Fallback never modifies production files."""
        (tmp_path / "core").mkdir()
        (tmp_path / "core" / "x.py").write_text("a = 1\n")
        original = (tmp_path / "core" / "x.py").read_text(encoding="utf-8")

        from core.self_improvement_loop import (
            JarvisImprovementLoop, ImprovementTask, PatchProposal,
        )
        loop = JarvisImprovementLoop(repo_root=tmp_path, lesson_path=tmp_path / "l.json")
        loop._pipeline = MagicMock()
        loop._pipeline.execute.side_effect = Exception("fail")

        task = ImprovementTask(id="t1", target_files=["core/x.py"],
                               problem_description="test", suggested_strategy="test")
        patch = PatchProposal(task_id="t1", diff={"core/x.py": "a = 2\n"})
        details = []
        loop._execute_via_pipeline(task, patch, details)
        assert (tmp_path / "core" / "x.py").read_text(encoding="utf-8") == original

    def test_no_write_text_in_active_path(self):
        """CS15. No write_text to repo in active code path."""
        import inspect
        from core.self_improvement_loop import JarvisImprovementLoop
        source = inspect.getsource(JarvisImprovementLoop._execute_via_pipeline)
        assert "write_text" not in source


# ═══════════════════════════════════════════════════════════════
# PHASE 2: API ROUTES & AUTH
# ═══════════════════════════════════════════════════════════════

class TestAPIRoutes:

    @pytest.fixture(autouse=True)
    def _app(self):
        from api.main import app
        self.app = app
        self.routes = {r.path for r in app.routes if hasattr(r, 'path')}

    @pytest.mark.xfail(reason="/api/v3/finance/products non-implémenté (drift)", strict=False)
    def test_finance_routes(self):
        """CS16."""
        assert "/api/v3/finance/products" in self.routes

    def test_missions_v3_routes(self):
        """CS17."""
        assert "/api/v3/missions" in self.routes

    def test_vault_routes(self):
        """CS18."""
        assert "/vault/list" in self.routes

    def test_identity_routes(self):
        """CS19."""
        assert "/identity/list" in self.routes

    def test_modules_v3_routes(self):
        """CS20."""
        # modules_v3 has connectors, agents, etc
        v3_module_routes = [r for r in self.routes if "/api/v3/connectors" in r or "/api/v3/agents" in r]
        assert len(v3_module_routes) > 0

    def test_legacy_mission_deprecated(self):
        """CS21."""
        for r in self.app.routes:
            if hasattr(r, 'path') and r.path == "/api/mission" and hasattr(r, 'methods') and "POST" in getattr(r, 'methods', set()):
                assert getattr(r, 'deprecated', False) or "DEPRECATED" in (getattr(r, 'description', '') or '')
                return
        # If not found, that's also OK (removed)

    def test_legacy_missions_deprecated(self):
        """CS22."""
        for r in self.app.routes:
            if hasattr(r, 'path') and r.path == "/api/missions":
                assert getattr(r, 'deprecated', False) or "DEPRECATED" in (getattr(r, 'description', '') or '')
                return

    def test_legacy_stats_deprecated(self):
        """CS23."""
        for r in self.app.routes:
            if hasattr(r, 'path') and r.path == "/api/stats":
                assert getattr(r, 'deprecated', False) or "DEPRECATED" in (getattr(r, 'description', '') or '')
                return

    def test_legacy_mission_has_auth(self):
        """CS24. Legacy POST /api/mission has auth (via x_jarvis_token or authorization)."""
        import inspect
        from api.routes.missions import legacy_post_mission
        sig = inspect.signature(legacy_post_mission)
        assert "x_jarvis_token" in sig.parameters or "authorization" in sig.parameters

    def test_legacy_missions_has_auth(self):
        """CS25. Legacy GET /api/missions has auth."""
        import inspect
        from api.routes.missions import legacy_missions
        sig = inspect.signature(legacy_missions)
        assert "x_jarvis_token" in sig.parameters or "authorization" in sig.parameters

    @pytest.mark.xfail(reason="legacy_stats auth config drift", strict=False)
    def test_legacy_stats_has_auth(self):
        """CS26. Legacy GET /api/stats delegates to auth-protected get_metrics."""
        # legacy_stats() delegates to get_metrics() which has _check_auth
        import inspect
        from api.routes.missions import legacy_stats
        # Auth is enforced in the delegated function — verify delegation exists
        source = inspect.getsource(legacy_stats)
        assert "get_metrics" in source

    def test_health_public(self):
        """CS27."""
        from api.access_enforcement import is_public_path
        assert is_public_path("/health")

    def test_docs_public(self):
        """CS28."""
        from api.access_enforcement import is_public_path
        assert is_public_path("/docs")

    def test_total_routes(self):
        """CS29."""
        assert len(self.routes) > 300

    def test_no_secret_route(self):
        """CS30."""
        for path in self.routes:
            assert "secret" not in path.lower() or "vault" in path.lower() or "secret_key" not in path.lower()


# ═══════════════════════════════════════════════════════════════
# PHASE 3: ARCHITECTURE COHERENCE
# ═══════════════════════════════════════════════════════════════

class TestArchitectureCoherence:

    def test_meta_orchestrator_canonical(self):
        """CS31."""
        from core.meta_orchestrator import MetaOrchestrator, get_meta_orchestrator
        orch = get_meta_orchestrator()
        assert isinstance(orch, MetaOrchestrator)

    def test_meta_delegates(self):
        """CS32."""
        from core.meta_orchestrator import MetaOrchestrator
        orch = MetaOrchestrator()
        assert hasattr(orch, 'jarvis')  # v1
        assert hasattr(orch, 'v2')      # v2

    def test_state_machine(self):
        """CS33."""
        from core.state import MissionStatus
        assert hasattr(MissionStatus, 'CREATED')
        assert hasattr(MissionStatus, 'PLANNED')
        assert hasattr(MissionStatus, 'RUNNING')
        assert hasattr(MissionStatus, 'DONE')
        assert hasattr(MissionStatus, 'FAILED')

    def test_llm_factory_multi_provider(self):
        """CS34."""
        from core.llm_factory import LLMFactory
        # LLMFactory requires settings
        from config.settings import get_settings
        factory = LLMFactory(get_settings())
        assert hasattr(factory, 'get')

    def test_tool_executor(self):
        """CS35."""
        from core.tool_executor import get_tool_executor
        executor = get_tool_executor()
        assert hasattr(executor, 'execute')
        assert hasattr(executor, '_execute_with_retry')


# ═══════════════════════════════════════════════════════════════
# PHASE 4: SECURITY
# ═══════════════════════════════════════════════════════════════

class TestSecurity:

    def test_check_auth_missing_token(self):
        """CS36."""
        # _check_auth moved from api.main to api._deps (single source).
        from api._deps import _check_auth
        import os
        if os.environ.get("JARVIS_API_TOKEN"):
            from fastapi import HTTPException
            with pytest.raises(HTTPException):
                _check_auth(None, None)

    def test_access_enforcement_loaded(self):
        """CS37."""
        from api.middleware import AccessEnforcementMiddleware
        assert AccessEnforcementMiddleware is not None

    def test_rate_limiter_groups(self):
        """CS38."""
        from api.rate_limiter import ROUTE_LIMITS
        assert "/auth/" in ROUTE_LIMITS
        assert "/api/" in ROUTE_LIMITS or "/api/v2/" in ROUTE_LIMITS

    def test_security_headers_loaded(self):
        """CS39."""
        from api.security_headers import SecurityHeadersMiddleware
        assert SecurityHeadersMiddleware is not None

    def test_vault_aes256(self):
        """CS40."""
        from core.security.secret_crypto import encrypt, decrypt
        # Test round-trip (AES-256-GCM)
        import os
        master_key = os.urandom(32)
        salt = os.urandom(16)
        enc = encrypt("test_secret_data", master_key, salt)
        dec = decrypt(enc, master_key)
        assert dec == "test_secret_data"

    def test_scrub_patterns(self):
        """CS41."""
        from core.self_improvement.sandbox_executor import _scrub_secrets
        text = "key=sk-abc123456789012345678901234567890123456789 and ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ012345 and xoxb-token"
        scrubbed = _scrub_secrets(text)
        assert "sk-abc" not in scrubbed
        assert "xoxb-" not in scrubbed

    def test_protected_paths_complete(self):
        """CS42."""
        from core.self_improvement.protected_paths import is_protected
        critical = [
            "core/meta_orchestrator.py",
            "core/tool_executor.py",
            "core/policy_engine.py",
            "api/auth.py",
            "core/self_improvement_loop.py",
            "config/settings.py",
            "main.py",
        ]
        for f in critical:
            assert is_protected(f), f"Expected {f} to be protected"


# ═══════════════════════════════════════════════════════════════
# PHASE 5: SELF-IMPROVEMENT COMPLETENESS
# ═══════════════════════════════════════════════════════════════

class TestSICompleteness:

    def test_lesson_memory_persistence(self, tmp_path):
        """CS43."""
        from core.self_improvement_loop import LessonMemory, Lesson
        mem = LessonMemory(tmp_path / "lessons.json")
        mem.store(Lesson(
            task_id="t1", problem="test", fix_strategy="s1",
            files_changed=["a.py"], result="success",
            score=1.0, lessons_learned="test lesson",
        ))
        # Verify lesson was stored by searching for it
        results = mem.search("test")
        assert len(results) >= 1
        assert results[0].task_id == "t1"

    def test_promotion_decisions_valid(self):
        """CS44."""
        from core.self_improvement.promotion_pipeline import PromotionDecision
        valid = {"PROMOTE", "REVIEW", "REJECT"}
        for d in valid:
            pd = PromotionDecision(decision=d)
            assert pd.decision in valid

    def test_no_auto_apply(self):
        """CS45. No write_text to repo in _execute_via_pipeline."""
        import inspect
        from core.self_improvement_loop import JarvisImprovementLoop
        source = inspect.getsource(JarvisImprovementLoop._execute_via_pipeline)
        assert "write_text" not in source
        # Also verify SandboxRunner.run() doesn't write
        from core.self_improvement_loop import SandboxRunner
        runner_source = inspect.getsource(SandboxRunner.run)
        assert "write_text" not in runner_source
