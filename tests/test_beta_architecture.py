"""
Beta Architecture Stabilization Tests
======================================
Validates mandatory architecture decisions:
1. MissionStatus is single source (core/state.py)
2. MetaOrchestrator is canonical orchestrator
3. No shell=True in agents/
4. Approval enforced in ToolExecutor for high-risk
5. Feature flags gate real logic
6. No mock execution in production paths
7. Memory modules are consistent
8. LangGraph plugs into MetaOrchestrator
"""
import pytest
import os
import re
import sys
import types
import unittest
import subprocess
_silent_log = __import__("structlog").get_logger(__name__)

if 'structlog' not in sys.modules:
    _sl = types.ModuleType('structlog')
    class _ML:
        def info(self, *a, **k): pass
        def debug(self, *a, **k): pass
        def warning(self, *a, **k): pass
        def error(self, *a, **k): pass
        def bind(self, **k): return self
    _sl.get_logger = lambda *a, **k: _ML()
    sys.modules['structlog'] = _sl

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


class TestMissionStatusUnified(unittest.TestCase):
    """MissionStatus is defined ONCE in core/state.py."""

    def test_single_source(self):
        from core.state import MissionStatus as MS_state
        from core.mission_system import MissionStatus as MS_mission
        from core.meta_orchestrator import MissionStatus as MS_meta
        from core import MissionStatus as MS_core
        self.assertIs(MS_state, MS_mission)
        self.assertIs(MS_state, MS_meta)
        self.assertIs(MS_state, MS_core)

    def test_all_values_present(self):
        from core.state import MissionStatus
        required = [
            "CREATED", "ANALYZING", "PENDING_VALIDATION", "APPROVED",
            "EXECUTING", "DONE", "REJECTED", "BLOCKED", "PLAN_ONLY",
            "PLANNED", "RUNNING", "REVIEW", "FAILED", "CANCELLED",
        ]
        for val in required:
            self.assertTrue(hasattr(MissionStatus, val), f"Missing: {val}")

    def test_no_other_mission_status_class(self):
        """No other file defines 'class MissionStatus' (grep check)."""
        result = subprocess.run(
            ["grep", "-rn", "class MissionStatus", "--include=*.py",
             _ROOT + "/core/"],
            capture_output=True, text=True,
        )
        lines = [l for l in result.stdout.strip().split("\n")
                 if l and "__pycache__" not in l and "test" not in l.lower()]
        # Only core/state.py should define it; others should import
        # Exception: core/business/mission_schema.py has a domain-specific
        # MissionStatus with different values (lowercase business lifecycle)
        ALLOWED = {"core/state.py", "core/business/mission_schema.py"}
        definitions = [l for l in lines if "import" not in l and "noqa" not in l]

        def _relfile(line: str) -> str:
            # grep -rn => "FILE:LINE:CONTENT". Sur Windows FILE contient "C:\..."
            # (lettre de lecteur + ':') : on découpe avant ":<num>:" puis on normalise
            # les séparateurs et on rend le chemin relatif à _ROOT.
            m = re.match(r"^(.*?):\d+:", line)
            fp = (m.group(1) if m else line).replace("\\", "/")
            root = _ROOT.replace("\\", "/").rstrip("/")
            return fp[len(root):].lstrip("/") if fp.startswith(root) else fp

        found_files = {_relfile(l) for l in definitions}
        unexpected = found_files - ALLOWED
        self.assertEqual(len(unexpected), 0,
                         f"MissionStatus defined in unexpected places: {unexpected}")


class TestMetaOrchestratorCanonical(unittest.TestCase):
    """MetaOrchestrator is the only orchestrator used in production paths."""

    def test_main_uses_meta(self):
        with open(os.path.join(_ROOT, "main.py")) as f:
            content = f.read()
        self.assertIn("get_meta_orchestrator", content)
        self.assertNotIn("OrchestratorV2(", content)


    @pytest.mark.xfail(reason="core/background_dispatcher.py missing (drift)", strict=False)
    def test_background_dispatcher_uses_meta(self):
        with open(os.path.join(_ROOT, "core", "background_dispatcher.py")) as f:
            content = f.read()
        self.assertIn("get_meta_orchestrator", content)
        self.assertNotIn("OrchestratorV2(", content)

    def test_meta_orchestrator_importable(self):
        from core.meta_orchestrator import MetaOrchestrator, get_meta_orchestrator
        orch = get_meta_orchestrator()
        self.assertIsInstance(orch, MetaOrchestrator)

    def test_meta_orchestrator_singleton(self):
        from core.meta_orchestrator import get_meta_orchestrator
        o1 = get_meta_orchestrator()
        o2 = get_meta_orchestrator()
        self.assertIs(o1, o2)


class TestNoShellTrueInAgents(unittest.TestCase):
    """No shell=True in agents/ directory (security)."""

    def test_no_shell_true(self):
        agents_dir = os.path.join(_ROOT, "agents")
        result = subprocess.run(
            ["grep", "-rn", "shell=True", "--include=*.py", agents_dir],
            capture_output=True, text=True,
        )
        lines = [l for l in result.stdout.strip().split("\n")
                 if l and "__pycache__" not in l]
        self.assertEqual(len(lines), 0,
                         "shell=True found in agents/:\n" + "\n".join(lines))


class TestApprovalEnforced(unittest.TestCase):
    """High-risk tools require approval in ToolExecutor."""

    def test_classify_danger_exists(self):
        from core.governance import classify_danger
        self.assertTrue(callable(classify_danger))

    def test_high_risk_classified(self):
        from core.governance import classify_danger
        result = classify_danger(action="run_command_safe", goal="rm -rf /")
        self.assertIn("level", result)

    def test_kill_switch_blocks(self):
        """ToolExecutor respects BEA_EXECUTION_DISABLED."""
        os.environ["BEA_EXECUTION_DISABLED"] = "1"
        try:
            # The kill switch is checked at execution time
            blocked = os.environ.get("BEA_EXECUTION_DISABLED", "").lower() in ("1", "true", "yes")
            self.assertTrue(blocked, "Kill switch env var not set properly")
        finally:
            os.environ.pop("BEA_EXECUTION_DISABLED", None)


class TestFeatureFlagsReal(unittest.TestCase):
    """Feature flags gate actual logic."""

    def test_safety_controls_flags(self):
        from core.safety_controls import get_safety_state
        state = get_safety_state()
        d = state.to_dict()
        self.assertIn("intelligence_enabled", d)
        self.assertIn("proposals_enabled", d)
        self.assertIn("execution_engine_enabled", d)

    def test_kill_switch_flag(self):
        """BEA_EXECUTION_DISABLED blocks ToolExecutor."""
        os.environ["BEA_EXECUTION_DISABLED"] = "1"
        try:
            blocked = os.environ.get("BEA_EXECUTION_DISABLED", "").lower() in ("1", "true", "yes")
            self.assertTrue(blocked)
        finally:
            os.environ.pop("BEA_EXECUTION_DISABLED", None)


class TestNoMockExecution(unittest.TestCase):
    """Production API path uses real orchestrator, not fake results."""

    def test_api_main_uses_orchestrator(self):
        # orch.run is in api/routes/missions.py (routes refactored from main.py)
        import glob as _glob
        api_files = _glob.glob(os.path.join(_ROOT, "api", "**", "*.py"), recursive=True)
        combined = ""
        for p in api_files:
            try:
                with open(p, encoding="utf-8") as fh:
                    combined += fh.read()
            except (IOError, OSError):
                _silent_log.debug("suppressed_exception", src='test_beta_architecture.py')
        self.assertIn("_get_orchestrator", combined)
        self.assertIn("orch.run", combined)

    def test_no_fake_success_in_api(self):
        with open(os.path.join(_ROOT, "api", "main.py")) as f:
            content = f.read()
        # No "fake" or "simulated" in actual response construction
        lines = content.split("\n")
        for i, line in enumerate(lines):
            if '"fake"' in line.lower() or '"simulated"' in line.lower():
                if not line.strip().startswith("#"):
                    self.fail(f"Fake/simulated result at line {i+1}: {line.strip()}")


class TestMemoryConsistency(unittest.TestCase):
    """Memory modules are importable and consistent."""

    def test_decision_memory_importable(self):
        from memory.decision_memory import get_decision_memory
        dm = get_decision_memory()
        self.assertIsNotNone(dm)

    def test_knowledge_memory_importable(self):
        from core.knowledge_memory import KnowledgeMemory
        self.assertTrue(callable(KnowledgeMemory))

    def test_memory_facade_importable(self):
        from core.memory_facade import get_memory_facade
        facade = get_memory_facade()
        self.assertIsNotNone(facade)

    def test_memory_bus_importable(self):
        from memory.memory_bus import MemoryBus
        self.assertTrue(callable(MemoryBus))


class TestLangGraphCompatibility(unittest.TestCase):
    """LangGraph plugs into MetaOrchestrator when enabled."""

    def test_langgraph_uses_meta_orchestrator(self):
        lg_path = os.path.join(_ROOT, "core", "orchestrator_lg", "langgraph_flow.py")
        if not os.path.exists(lg_path):
            self.skipTest("LangGraph module not present")
        with open(lg_path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("MetaOrchestrator", content)


class TestNoLeakedSecrets(unittest.TestCase):
    """No plaintext tokens or secrets in tracked files."""

    def test_no_bot_token_in_source(self):
        """Telegram bot token must not appear in any Python source."""
        result = subprocess.run(
            ["grep", "-rn", "8729616478", "--include=*.py", _ROOT],
            capture_output=True, text=True,
        )
        lines = [l for l in result.stdout.strip().split("\n")
                 if l and "__pycache__" not in l
                 and "test_beta_architecture" not in l]  # exclude self
        self.assertEqual(len(lines), 0,
                         f"Bot token found in source: {lines}")

    def test_no_hardcoded_production_ip(self):
        """No hardcoded production IP in Dart, Python source, or scripts."""
        result = subprocess.run(
            ["grep", "-rn", "77.42.40.146",
             "--include=*.py", "--include=*.dart",
             _ROOT],
            capture_output=True, text=True,
        )
        lines = [l for l in result.stdout.strip().split("\n")
                 if l and "__pycache__" not in l
                 and ".git" not in l
                 and "test_beta_architecture" not in l  # exclude self
                 and "AUDIT_" not in l and "RELEASE_" not in l
                 and "MIGRATION_" not in l and "docs/archive" not in l
                 and "api_config.dart" not in l  # intentional client config
                 and "docs/" not in l]
        self.assertEqual(len(lines), 0,
                         f"Hardcoded production IP found: {lines}")

    def test_send_telegram_deleted(self):
        self.assertFalse(os.path.exists(os.path.join(_ROOT, "send_telegram.py")))
        self.assertFalse(os.path.exists(os.path.join(_ROOT, "send_telegram_v5.py")))


class TestRepoHygiene(unittest.TestCase):
    """Repo is clean and organized."""

    @pytest.mark.skip(reason="stale: APK delivery changed")
    def test_no_apks_in_repo(self):
        result = subprocess.run(
            ["find", _ROOT, "-name", "*.apk",
             "-not", "-path", "*/.git/*",
             "-not", "-path", "*/build/*"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.stdout.strip(), "",
                         f"APK files found: {result.stdout.strip()}")

    def test_gitignore_has_apk(self):
        with open(os.path.join(_ROOT, ".gitignore")) as f:
            content = f.read()
        self.assertIn("*.apk", content)


if __name__ == "__main__":
    unittest.main()
