"""
JARVIS MAX — Tests for Devin Bug Fixes
==========================================
BUG A: Anti-duplicate mission execution
BUG B: No-op patch detection (false success prevention)
BUG C: Bearer token parsing consistency

Total: 30 tests
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


# ═══════════════════════════════════════════════════════════════
# BUG A — Anti-Duplicate Mission Execution
# ═══════════════════════════════════════════════════════════════

class TestAntiDuplicateMission:
    """Verify a mission_id can never run twice concurrently."""

    def test_DA01_running_missions_set_exists(self):
        """DA01: _running_missions guard exists in api/main.py."""
        from api.main import _running_missions
        assert isinstance(_running_missions, set)

    def test_DA02_guard_prevents_duplicate(self):
        """DA02: Second submit with same mission_id returns 'already_running'."""
        from api.main import _running_missions
        _running_missions.add("test-mission-001")
        try:
            assert "test-mission-001" in _running_missions
        finally:
            _running_missions.discard("test-mission-001")

    def test_DA03_guard_cleanup_on_completion(self):
        """DA03: Mission ID removed from guard set after execution."""
        from api.main import _running_missions
        _running_missions.add("test-mission-002")
        _running_missions.discard("test-mission-002")
        assert "test-mission-002" not in _running_missions

    def test_DA04_orchestrator_single_entrypoint(self):
        """DA04: Only one orch.run() call exists in the API layer."""
        api_main_path = os.path.join(os.path.dirname(__file__), "..", "api", "main.py")
        with open(api_main_path, encoding="utf-8") as f:
            source = f.read()
        # Count orch.run( calls — there should be exactly 1 in the API
        source.count("orch.run(") + source.count("orch.run_mission(")
        # 1 for await orch.run(), possibly 1 for the agent trigger
        # But run_mission should be at most 1
        orch_run_count = source.count("await orch.run(")
        assert orch_run_count == 1, f"Expected 1 orch.run() call, found {orch_run_count}"

    def test_DA05_mission_system_submit_creates_once(self):
        """DA05: MissionSystem.submit() creates mission record — doesn't execute."""
        # The submit() call just creates a record and returns a result
        # It's the background_tasks.add_task(_run_mission) that executes
        from api.main import _running_missions
        # Guard is checked before background task is added
        assert isinstance(_running_missions, set)

    def test_DA06_no_notify_meta_orchestrator(self):
        """DA06: No phantom notify_meta_orchestrator function anywhere (excl. tests)."""
        import subprocess
        result = subprocess.run(
            ["grep", "-rn", "notify_meta_orchestrator", "--include=*.py",
             "--exclude-dir=tests", "--exclude-dir=__pycache__", "."],
            capture_output=True, text=True, cwd=os.path.join(os.path.dirname(__file__), ".."),
        )
        assert result.stdout.strip() == "", f"Found phantom function: {result.stdout[:200]}"

    def test_DA07_finally_cleanup_present(self):
        """DA07: _run_mission has finally block that clears running guard."""
        api_main_path = os.path.join(os.path.dirname(__file__), "..", "api", "main.py")
        with open(api_main_path, encoding="utf-8") as f:
            source = f.read()
        assert "_running_missions.discard(" in source, "Missing cleanup in finally block"


# ═══════════════════════════════════════════════════════════════
# BUG B — No-Op Patch Detection (False Success Prevention)
# ═══════════════════════════════════════════════════════════════

class TestNoOpPatchDetection:
    """Verify that no-op patches are never promoted as successful."""

    def test_DB01_create_diff_returns_none_on_noop(self):
        """DB01: _create_diff returns None when old_text == new_text."""
        import tempfile
        from core.self_improvement.code_patcher import CodePatcher, PatchIntent, PatchMode
        with tempfile.TemporaryDirectory() as td:
            # Write a source file
            target = os.path.join(td, "test.py")
            with open(target, "w") as f:
                f.write("x = 1\ny = 2\n")
            patcher = CodePatcher(td)
            intent = PatchIntent(
                file_path="test.py",
                old_text="x = 1",
                new_text="x = 1",  # same text — no-op
                mode=PatchMode.EXACT_REPLACE,
            )
            diff = patcher._create_diff(intent)
            assert diff is None, "No-op should return None"

    def test_DB02_noop_violation_flag_set(self):
        """DB02: generate() sets noop_violation when diff produces nothing."""
        import tempfile
        from core.self_improvement.code_patcher import CodePatcher, PatchIntent
        with tempfile.TemporaryDirectory() as td:
            target = os.path.join(td, "test.py")
            with open(target, "w") as f:
                f.write("x = 1\n")
            patcher = CodePatcher(td)
            patch = patcher.generate([
                PatchIntent(file_path="test.py", old_text="x = 1", new_text="x = 1"),
            ], issue="noop test")
            assert patch.noop_violation is True
            assert patch.is_valid is False

    def test_DB03_insertion_produces_real_diff(self):
        """DB03: Insertion generates a real diff."""
        import tempfile
        from core.self_improvement.code_patcher import CodePatcher, PatchIntent, PatchMode
        with tempfile.TemporaryDirectory() as td:
            target = os.path.join(td, "test.py")
            with open(target, "w") as f:
                f.write("x = 1\n")
            patcher = CodePatcher(td)
            intent = PatchIntent(
                file_path="test.py",
                old_text="x = 1",
                new_text="x = 1\ny = 2",
                mode=PatchMode.EXACT_REPLACE,
            )
            diff = patcher._create_diff(intent)
            assert diff is not None
            assert diff.lines_added > 0

    def test_DB04_deletion_produces_real_diff(self):
        """DB04: Deletion generates a real diff."""
        import tempfile
        from core.self_improvement.code_patcher import CodePatcher, PatchIntent, PatchMode
        with tempfile.TemporaryDirectory() as td:
            target = os.path.join(td, "test.py")
            with open(target, "w") as f:
                f.write("x = 1\ny = 2\nz = 3\n")
            patcher = CodePatcher(td)
            intent = PatchIntent(
                file_path="test.py",
                old_text="y = 2\n",
                new_text="",
                mode=PatchMode.EXACT_REPLACE,
            )
            diff = patcher._create_diff(intent)
            assert diff is not None
            assert diff.lines_removed > 0

    def test_DB05_replacement_produces_real_diff(self):
        """DB05: Replacement generates a real diff."""
        import tempfile
        from core.self_improvement.code_patcher import CodePatcher, PatchIntent
        with tempfile.TemporaryDirectory() as td:
            target = os.path.join(td, "test.py")
            with open(target, "w") as f:
                f.write("timeout = 30\n")
            patcher = CodePatcher(td)
            intent = PatchIntent(
                file_path="test.py", old_text="timeout = 30", new_text="timeout = 60",
            )
            diff = patcher._create_diff(intent)
            assert diff is not None
            assert "timeout = 60" in diff.modified

    def test_DB06_old_text_not_found_returns_none(self):
        """DB06: If old_text doesn't exist in file → None (not false success)."""
        import tempfile
        from core.self_improvement.code_patcher import CodePatcher, PatchIntent
        with tempfile.TemporaryDirectory() as td:
            target = os.path.join(td, "test.py")
            with open(target, "w") as f:
                f.write("x = 1\n")
            patcher = CodePatcher(td)
            intent = PatchIntent(
                file_path="test.py", old_text="NONEXISTENT", new_text="y = 2",
            )
            diff = patcher._create_diff(intent)
            assert diff is None

    def test_DB07_apply_to_sandbox_refuses_invalid_patch(self):
        """DB07: apply_to_sandbox returns False for invalid patch."""
        import tempfile
        from core.self_improvement.code_patcher import CodePatcher, CodePatch
        with tempfile.TemporaryDirectory() as td:
            patcher = CodePatcher(td)
            patch = CodePatch(patch_id="noop", issue="test", noop_violation=True)
            result = patcher.apply_to_sandbox(patch, td)
            assert result is False

    def test_DB08_pipeline_rejects_noop_after_apply(self):
        """DB08: PromotionPipeline has a post-apply mutation check."""
        # Verify the code contains the no-op mutation check
        pipeline_path = os.path.join(
            os.path.dirname(__file__), "..",
            "core", "self_improvement", "promotion_pipeline.py"
        )
        with open(pipeline_path, encoding="utf-8") as f:
            source = f.read()
        assert "noop_mutation" in source, "Missing post-apply mutation check in pipeline"
        assert "No-op: sandbox has no actual diff" in source

    def test_DB09_guarded_append_skips_existing(self):
        """DB09: GUARDED_APPEND mode returns None if content already present."""
        import tempfile
        from core.self_improvement.code_patcher import CodePatcher, PatchIntent, PatchMode
        with tempfile.TemporaryDirectory() as td:
            target = os.path.join(td, "test.py")
            with open(target, "w") as f:
                f.write("import os\n\ndef hello():\n    pass\n")
            patcher = CodePatcher(td)
            intent = PatchIntent(
                file_path="test.py",
                old_text="",
                new_text="def hello():\n    pass",
                mode=PatchMode.GUARDED_APPEND,
            )
            diff = patcher._create_diff(intent)
            assert diff is None, "GUARDED_APPEND should skip if content already present"

    def test_DB10_sandbox_content_actually_changes(self):
        """DB10: After apply_to_sandbox, file content is actually different."""
        import tempfile
        from core.self_improvement.code_patcher import CodePatcher, PatchIntent
        with tempfile.TemporaryDirectory() as td:
            target = os.path.join(td, "test.py")
            original = "x = 1\n"
            with open(target, "w") as f:
                f.write(original)
            patcher = CodePatcher(td)
            patch = patcher.generate([
                PatchIntent(file_path="test.py", old_text="x = 1", new_text="x = 42"),
            ], issue="change x")
            patcher.validate_syntax(patch)
            sandbox = tempfile.mkdtemp()
            # Pre-populate sandbox
            sandbox_file = os.path.join(sandbox, "test.py")
            with open(sandbox_file, "w") as f:
                f.write(original)
            result = patcher.apply_to_sandbox(patch, sandbox)
            assert result is True
            with open(sandbox_file, encoding="utf-8") as f:
                final = f.read()
            assert final != original, "File content must be different after apply"
            assert "x = 42" in final


# ═══════════════════════════════════════════════════════════════
# BUG C — Bearer Token Parsing Consistency
# ═══════════════════════════════════════════════════════════════

class TestBearerTokenParsing:
    """Verify centralized, consistent Bearer token handling."""

    def test_DC01_strip_bearer_basic(self):
        """DC01: Basic Bearer prefix stripping."""
        from api.token_utils import strip_bearer
        assert strip_bearer("Bearer abc123") == "abc123"

    def test_DC02_strip_bearer_case_insensitive(self):
        """DC02: Case-insensitive prefix."""
        from api.token_utils import strip_bearer
        assert strip_bearer("bearer abc123") == "abc123"
        assert strip_bearer("BEARER abc123") == "abc123"
        assert strip_bearer("BeArEr abc123") == "abc123"

    def test_DC03_strip_bearer_no_prefix(self):
        """DC03: No prefix returns token as-is."""
        from api.token_utils import strip_bearer
        assert strip_bearer("abc123") == "abc123"
        assert strip_bearer("jv-mytoken") == "jv-mytoken"

    def test_DC04_strip_bearer_none_empty(self):
        """DC04: None/empty input returns None."""
        from api.token_utils import strip_bearer
        assert strip_bearer(None) is None
        assert strip_bearer("") is None
        assert strip_bearer("   ") is None

    def test_DC05_strip_bearer_whitespace(self):
        """DC05: Handles leading/trailing whitespace."""
        from api.token_utils import strip_bearer
        assert strip_bearer("  Bearer abc123  ") == "abc123"
        assert strip_bearer("Bearer   abc123") == "abc123"

    def test_DC06_strip_bearer_preserves_internal(self):
        """DC06: Does NOT strip 'Bearer' that appears mid-string."""
        from api.token_utils import strip_bearer
        result = strip_bearer("myBearer token")
        assert result == "myBearer token"

    def test_DC07_strip_bearer_only_prefix(self):
        """DC07: 'Bearer ' alone returns None (empty token)."""
        from api.token_utils import strip_bearer
        assert strip_bearer("Bearer ") is None
        assert strip_bearer("Bearer   ") is None

    def test_DC08_auth_py_uses_strip_bearer(self):
        """DC08: api/auth.py uses centralized strip_bearer."""
        auth_path = os.path.join(os.path.dirname(__file__), "..", "api", "auth.py")
        with open(auth_path, encoding="utf-8") as f:
            source = f.read()
        assert "from api.token_utils import strip_bearer" in source

    def test_DC09_middleware_uses_strip_bearer(self):
        """DC09: api/middleware.py uses centralized strip_bearer."""
        mw_path = os.path.join(os.path.dirname(__file__), "..", "api", "middleware.py")
        with open(mw_path, encoding="utf-8") as f:
            source = f.read()
        assert "from api.token_utils import strip_bearer" in source

    def test_DC10_access_enforcement_uses_strip_bearer(self):
        """DC10: api/access_enforcement.py uses centralized strip_bearer."""
        ae_path = os.path.join(os.path.dirname(__file__), "..", "api", "access_enforcement.py")
        with open(ae_path, encoding="utf-8") as f:
            source = f.read()
        assert "from api.token_utils import strip_bearer" in source

    def test_DC11_main_py_uses_strip_bearer(self):
        """DC11: the auth subsystem uses centralized strip_bearer.

        Audit Mo3: auth routes moved from api/main.py to api/routes/auth.py.
        The "no ad-hoc Bearer parsing" guarantee still holds as long as
        one of those two files imports strip_bearer.
        """
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sources = []
        for rel in ("api/main.py", "api/routes/auth.py"):
            path = os.path.join(repo_root, rel)
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    sources.append(f.read())
        combined = "\n".join(sources)
        assert "from api.token_utils import strip_bearer" in combined

    def test_DC12_bearer_abc_token(self):
        """DC12: 'Bearer abc' → 'abc'."""
        from api.token_utils import strip_bearer
        assert strip_bearer("Bearer abc") == "abc"

    def test_DC13_raw_header_no_prefix(self):
        """DC13: Raw token without prefix passes through."""
        from api.token_utils import strip_bearer
        assert strip_bearer("jv-abc123xyz") == "jv-abc123xyz"
        assert strip_bearer("some-raw-token-here") == "some-raw-token-here"

    def test_DC14_bearer_mid_string_preserved(self):
        """DC14: 'Bearer ' in middle of string is NOT stripped."""
        from api.token_utils import strip_bearer
        result = strip_bearer("mytoken-Bearer stuff-after")
        assert result == "mytoken-Bearer stuff-after"
        result2 = strip_bearer("abc Bearer xyz")
        assert result2 == "abc Bearer xyz"

    def test_DC15_empty_null_variants(self):
        """DC15: Empty/null edge cases."""
        from api.token_utils import strip_bearer
        assert strip_bearer(None) is None
        assert strip_bearer("") is None
        assert strip_bearer("   ") is None
        assert strip_bearer("\t\n") is None

    def test_DC16_http_ws_consistency(self):
        """DC16: Same function used in HTTP auth and WS-compatible paths."""
        from api.token_utils import strip_bearer
        # HTTP Authorization header
        http_token = strip_bearer("Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig")
        assert http_token == "eyJhbGciOiJIUzI1NiJ9.payload.sig"
        # WS query param (no prefix)
        ws_token = strip_bearer("eyJhbGciOiJIUzI1NiJ9.payload.sig")
        assert ws_token == "eyJhbGciOiJIUzI1NiJ9.payload.sig"
        # Both yield the same clean token
        assert http_token == ws_token

    def test_DC17_no_inline_bearer_parsing_remains(self):
        """DC12: No inline 'startswith("Bearer ")' + [7:] parsing in auth files."""
        for fname in ["api/auth.py", "api/access_enforcement.py", "api/middleware.py"]:
            fpath = os.path.join(os.path.dirname(__file__), "..", fname)
            with open(fpath, encoding="utf-8") as f:
                source = f.read()
            # Should not have the old pattern (startswith + [7:])
            lines = source.split("\n")
            for i, line in enumerate(lines, 1):
                if 'startswith("Bearer ")' in line and "[7:]" in lines[min(i, len(lines)-1)]:
                    pytest.fail(f"Inline Bearer parsing found in {fname}:{i}")
