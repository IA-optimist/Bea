"""
tests/test_kernel_execution.py — Kernel execution-level convergence tests.

Validates:
  - ToolExecutor emits kernel tool events
  - PlanRunner emits kernel step events
  - PromotionPipeline emits kernel patch events
  - Event adapter maps execution events deterministically
  - No secret leakage in kernel execution events
  - No regression in execution behavior
  - All emissions are fail-open
  - Execution trace queries work
"""
import inspect


# ═══════════════════════════════════════════════════════════════
# 1 — ToolExecutor Kernel Event Wiring
# ═══════════════════════════════════════════════════════════════

class TestToolExecutorKernelEvents:

    def test_KE01_tool_invoked_wired(self):
        """ToolExecutor.execute() emits kernel tool.invoked."""
        from core.tool_executor import ToolExecutor
        source = inspect.getsource(ToolExecutor.execute)
        assert "emit_kernel_event" in source
        assert '"tool.invoked"' in source

    def test_KE02_tool_completed_wired(self):
        """ToolExecutor.execute() emits kernel tool.completed on success."""
        from core.tool_executor import ToolExecutor
        source = inspect.getsource(ToolExecutor.execute)
        assert '"tool.completed"' in source

    def test_KE03_tool_failed_wired(self):
        """ToolExecutor.execute() emits kernel tool.failed on failure."""
        from core.tool_executor import ToolExecutor
        source = inspect.getsource(ToolExecutor.execute)
        assert '"tool.failed"' in source

    def test_KE04_tool_events_fail_open(self):
        """All kernel tool emissions are in try/except blocks."""
        from core.tool_executor import ToolExecutor
        source = inspect.getsource(ToolExecutor.execute)
        # Count kernel emission blocks
        import re
        kernel_blocks = list(re.finditer(r'emit_kernel_event\(', source))
        assert len(kernel_blocks) >= 3  # invoked, completed/failed (success), failed (exception)
        for match in kernel_blocks:
            preceding = source[max(0, match.start() - 200):match.start()]
            assert "try:" in preceding, f"emit_kernel_event not in try/except at pos {match.start()}"

    def test_KE05_no_raw_params_in_kernel_events(self):
        """Kernel tool events do not include raw parameter values."""
        from core.tool_executor import ToolExecutor
        source = inspect.getsource(ToolExecutor.execute)
        # Find kernel emit blocks
        import re
        for match in re.finditer(r'emit_kernel_event\([^)]+\)', source, re.DOTALL):
            block = match.group(0)
            # Should not contain 'params=' or raw param values
            assert "params=" not in block or "param_keys" in block, \
                f"Raw params found in kernel event: {block[:100]}"

    def test_KE06_approval_blocked_no_completed(self):
        """Approval-blocked tools emit tool.invoked but NOT tool.completed."""
        from core.tool_executor import ToolExecutor
        source = inspect.getsource(ToolExecutor.execute)
        # The tool.invoked emission happens BEFORE execution
        # tool.completed/failed only happens AFTER _execute_with_retry()
        # Approval blocking returns BEFORE _execute_with_retry(), so no false completed
        invoked_pos = source.find('"tool.invoked"')
        execute_pos = source.find('_execute_with_retry')
        completed_pos = source.find('"tool.completed"')
        assert invoked_pos < execute_pos < completed_pos, \
            "tool.invoked must be before execution, tool.completed after"

    def test_KE07_tool_execute_still_works(self):
        """ToolExecutor basic execution path is unchanged."""
        from core.tool_executor import ToolExecutor
        te = ToolExecutor()
        # Unknown tool returns error
        result = te.execute("nonexistent_tool", {})
        assert result["ok"] is False
        assert "unknown_tool" in result["error"]

    def test_KE08_tool_event_includes_mission_id(self):
        """Kernel tool events include mission_id context."""
        from core.tool_executor import ToolExecutor
        source = inspect.getsource(ToolExecutor.execute)
        # All 3 emission points should include mission_id
        import re
        for match in re.finditer(r'emit_kernel_event\([^)]+\)', source, re.DOTALL):
            block = match.group(0)
            assert "mission_id" in block, f"Missing mission_id in: {block[:80]}"

    def test_KE09_tool_event_includes_duration(self):
        """Kernel tool completion events include duration_ms."""
        from core.tool_executor import ToolExecutor
        source = inspect.getsource(ToolExecutor.execute)
        # Find completed/failed events
        for keyword in ['"tool.completed"', '"tool.failed"']:
            pos = source.find(keyword)
            if pos > 0:
                block = source[pos:pos + 300]
                assert "duration_ms" in block, f"Missing duration_ms near {keyword}"


# ═══════════════════════════════════════════════════════════════
# 2 — PlanRunner Kernel Event Wiring
# ═══════════════════════════════════════════════════════════════

class TestPlanRunnerKernelEvents:

    def test_KE10_step_started_wired(self):
        """PlanRunner._emit() emits kernel step.started."""
        from core.planning.plan_runner import PlanRunner
        source = inspect.getsource(PlanRunner._emit)
        assert "emit_kernel_event" in source
        assert '"step.started"' in source

    def test_KE11_step_completed_wired(self):
        """PlanRunner._emit() emits kernel step.completed."""
        from core.planning.plan_runner import PlanRunner
        source = inspect.getsource(PlanRunner._emit)
        assert '"step.completed"' in source

    def test_KE12_step_failed_wired(self):
        """PlanRunner._emit() emits kernel step.failed."""
        from core.planning.plan_runner import PlanRunner
        source = inspect.getsource(PlanRunner._emit)
        assert '"step.failed"' in source

    def test_KE13_runner_event_mapping_complete(self):
        """All PlanRunner events map to kernel types."""
        from core.planning.plan_runner import PlanRunner
        source = inspect.getsource(PlanRunner._emit)
        # The _RUNNER_TO_KERNEL mapping should cover all emitted events
        expected_mappings = [
            "step_started", "step_completed", "step_failed",
            "step_needs_approval", "run_started", "run_completed",
        ]
        for event in expected_mappings:
            assert f'"{event}"' in source, f"Missing mapping for {event}"

    def test_KE14_runner_kernel_emission_fail_open(self):
        """PlanRunner kernel emissions are wrapped in try/except."""
        from core.planning.plan_runner import PlanRunner
        source = inspect.getsource(PlanRunner._emit)
        assert source.count("try:") >= 2  # cognitive + kernel
        assert source.count("except Exception") >= 2

    def test_KE15_runner_includes_step_context(self):
        """Kernel step events include step_id and step_name."""
        from core.planning.plan_runner import PlanRunner
        source = inspect.getsource(PlanRunner._emit)
        # The kernel emission block should reference step.step_id
        assert 'kwargs["step_id"]' in source
        assert 'kwargs["step_name"]' in source

    def test_KE16_runner_approval_event_correct(self):
        """step_needs_approval maps to approval.requested with correct context."""
        from core.planning.plan_runner import PlanRunner
        source = inspect.getsource(PlanRunner._emit)
        assert '"approval.requested"' in source
        assert 'kwargs["target_id"]' in source

    def test_KE17_runner_still_functional(self):
        """PlanRunner instantiation and basic interface unchanged."""
        from core.planning.plan_runner import PlanRunner
        runner = PlanRunner()
        assert hasattr(runner, "start")
        assert hasattr(runner, "resume")
        assert hasattr(runner, "pause")
        assert hasattr(runner, "cancel")
        assert hasattr(runner, "_emit")


# ═══════════════════════════════════════════════════════════════
# 3 — PromotionPipeline Kernel Event Wiring
# ═══════════════════════════════════════════════════════════════

class TestPromotionPipelineKernelEvents:

    def test_KE18_patch_proposed_wired(self):
        """PromotionPipeline emits kernel step.started for patch_proposed."""
        from core.self_improvement.promotion_pipeline import PromotionPipeline
        source = inspect.getsource(PromotionPipeline.execute)
        assert "emit_kernel_event" in source
        # patch proposed → step.started
        kernel_calls = [i for i in range(len(source)) if source[i:].startswith("emit_kernel_event")]
        assert len(kernel_calls) >= 2  # proposed + decision

    def test_KE19_patch_decision_wired(self):
        """PromotionPipeline emits kernel step.completed/failed for decisions."""
        from core.self_improvement.promotion_pipeline import PromotionPipeline
        source = inspect.getsource(PromotionPipeline.execute)
        assert '"step.completed"' in source
        assert '"step.failed"' in source

    def test_KE20_promotion_result_wired(self):
        """PromotionPipeline._emit_event emits kernel event for legacy path."""
        from core.self_improvement.promotion_pipeline import PromotionPipeline
        source = inspect.getsource(PromotionPipeline._emit_event)
        assert "emit_kernel_event" in source

    def test_KE21_promotion_events_fail_open(self):
        """All kernel emissions in PromotionPipeline are fail-open."""
        from core.self_improvement.promotion_pipeline import PromotionPipeline
        import re
        # Check execute() and _emit_event() — each kernel try block
        # must have a matching except within reasonable distance
        for method_name in ("execute", "_emit_event"):
            method = getattr(PromotionPipeline, method_name, None)
            if not method:
                continue
            source = inspect.getsource(method)
            # Find all try blocks containing emit_kernel_event
            try_blocks = list(re.finditer(
                r'try:\s*\n.*?from kernel\.convergence\.event_bridge.*?except\s+Exception',
                source, re.DOTALL,
            ))
            kernel_calls = len(re.findall(r'from kernel\.convergence\.event_bridge', source))
            assert kernel_calls > 0, f"No kernel imports in {method_name}"
            assert len(try_blocks) >= kernel_calls, \
                f"{method_name}: {kernel_calls} kernel imports but only {len(try_blocks)} try/except blocks"

    def test_KE22_promotion_no_secret_leakage(self):
        """Kernel events from PromotionPipeline don't include sensitive data."""
        from core.self_improvement.promotion_pipeline import PromotionPipeline
        source = inspect.getsource(PromotionPipeline)
        import re
        for match in re.finditer(r'emit_kernel_event\([^)]+\)', source, re.DOTALL):
            block = match.group(0)
            # Should not reference diff content, file contents, or API keys
            for danger in ["unified_diff", "api_key", "secret", "password", "token"]:
                assert danger not in block.lower(), f"Sensitive data '{danger}' in emission: {block[:80]}"


# ═══════════════════════════════════════════════════════════════
# 4 — Event Adapter Determinism
# ═══════════════════════════════════════════════════════════════

class TestEventAdapterDeterminism:

    def test_KE23_execution_events_mapped(self):
        """Core execution events map to kernel tool events."""
        from kernel.adapters.event_adapter import CORE_TO_KERNEL_EVENT
        assert CORE_TO_KERNEL_EVENT["execution.tool_requested"] == "tool.invoked"
        assert CORE_TO_KERNEL_EVENT["execution.tool_completed"] == "tool.completed"
        assert CORE_TO_KERNEL_EVENT["execution.tool_failed"] == "tool.failed"

    def test_KE24_lab_events_mapped(self):
        """Lab events map to step lifecycle events."""
        from kernel.adapters.event_adapter import CORE_TO_KERNEL_EVENT
        assert CORE_TO_KERNEL_EVENT["lab.patch_proposed"] == "step.started"
        assert CORE_TO_KERNEL_EVENT["lab.patch_validated"] == "step.completed"
        assert CORE_TO_KERNEL_EVENT["lab.patch_rejected"] == "step.failed"

    def test_KE25_mapping_is_deterministic(self):
        """Same input always produces same output."""
        from kernel.adapters.event_adapter import core_event_to_kernel_type
        for _ in range(10):
            assert core_event_to_kernel_type("execution.tool_requested") == "tool.invoked"
            assert core_event_to_kernel_type("mission.created") == "mission.created"

    def test_KE26_all_mapped_events_canonical(self):
        """All mapped kernel events exist in CANONICAL_EVENTS."""
        from kernel.adapters.event_adapter import CORE_TO_KERNEL_EVENT
        from kernel.events.canonical import CANONICAL_EVENTS
        for kernel_type in set(CORE_TO_KERNEL_EVENT.values()):
            assert kernel_type in CANONICAL_EVENTS, f"{kernel_type} not canonical"


# ═══════════════════════════════════════════════════════════════
# 5 — Execution Trace Queries
# ═══════════════════════════════════════════════════════════════

class TestExecutionTrace:

    def test_KE27_recent_tool_events(self):
        """get_recent_tool_events returns list."""
        from kernel.convergence.execution_trace import get_recent_tool_events
        events = get_recent_tool_events(limit=10)
        assert isinstance(events, list)

    def test_KE28_failed_tools(self):
        """get_failed_tools returns list."""
        from kernel.convergence.execution_trace import get_failed_tools
        failures = get_failed_tools(limit=10)
        assert isinstance(failures, list)

    def test_KE29_step_timeline(self):
        """get_step_timeline returns list."""
        from kernel.convergence.execution_trace import get_step_timeline
        steps = get_step_timeline(limit=10)
        assert isinstance(steps, list)

    def test_KE30_execution_summary(self):
        """get_execution_summary returns dict with expected keys."""
        from kernel.convergence.execution_trace import get_execution_summary
        summary = get_execution_summary()
        assert isinstance(summary, dict)
        if "error" not in summary:
            assert "tools_invoked" in summary
            assert "steps_started" in summary
            assert "missions_created" in summary
            assert "total_events" in summary

    def test_KE31_trace_api_endpoints_exist(self):
        """Kernel API has trace endpoints."""
        from api.routes.kernel import router
        paths = [r.path for r in router.routes]
        assert any("trace/tools" in p for p in paths)
        assert any("trace/failures" in p for p in paths)
        assert any("trace/steps" in p for p in paths)
        assert any("trace/summary" in p for p in paths)


# ═══════════════════════════════════════════════════════════════
# 6 — Invariants
# ═══════════════════════════════════════════════════════════════

class TestExecutionInvariants:

    def test_KE32_no_kernel_import_in_critical_zone_unconditional(self):
        """Kernel imports in ToolExecutor/PlanRunner are all inside try/except."""
        for module_path in [
            "core.tool_executor",
            "core.planning.plan_runner",
        ]:
            mod = __import__(module_path, fromlist=["_"])
            source = inspect.getsource(mod)
            # Find all kernel imports
            import re
            for match in re.finditer(r'from kernel', source):
                preceding = source[max(0, match.start() - 200):match.start()]
                assert "try:" in preceding, \
                    f"Unconditional kernel import in {module_path} at pos {match.start()}"

    def test_KE33_tool_executor_execution_unchanged(self):
        """ToolExecutor._execute_with_retry still exists and is callable."""
        from core.tool_executor import ToolExecutor
        te = ToolExecutor()
        assert hasattr(te, "_execute_with_retry")
        assert callable(te._execute_with_retry)

    def test_KE34_plan_runner_execution_unchanged(self):
        """PlanRunner._execute_steps still exists."""
        from core.planning.plan_runner import PlanRunner
        runner = PlanRunner()
        assert hasattr(runner, "_execute_steps")

    def test_KE35_cognitive_journal_still_primary(self):
        """Cognitive journal emissions are still present in ToolExecutor."""
        from core.tool_executor import ToolExecutor
        source = inspect.getsource(ToolExecutor.execute)
        assert "emit_tool_execution" in source
        assert "TOOL_EXECUTION_REQUESTED" in source
