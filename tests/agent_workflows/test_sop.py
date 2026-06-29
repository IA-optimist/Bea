"""
tests/agent_workflows/test_sop.py — SOP workflow engine tests.
"""
from __future__ import annotations

import pytest

from agent_workflows.verdicts import ReviewVerdict, VerdictSeverity, WorkflowVerdict
from agent_workflows.roles import AgentRole, AgentProfile
from agent_workflows.engine import SOPWorkflowEngine, SOPStep, SOPContext


# ── Helpers ───────────────────────────────────────────────────────────────────

def _verdict(step_id: str, severity: VerdictSeverity, desc: str = "test verdict") -> ReviewVerdict:
    return ReviewVerdict(
        step_id=step_id,
        category="test",
        severity=severity,
        description=desc + " (long enough description to pass min_length=10)",
    )


async def _pass_handler(ctx: SOPContext) -> list[ReviewVerdict]:
    return [_verdict(ctx.current_step, VerdictSeverity.P3, "minor issue")]


async def _fail_p1_handler(ctx: SOPContext) -> list[ReviewVerdict]:
    return [_verdict(ctx.current_step, VerdictSeverity.P1, "critical issue found")]


async def _fail_p0_handler(ctx: SOPContext) -> list[ReviewVerdict]:
    return [_verdict(ctx.current_step, VerdictSeverity.P0, "blocker: stop workflow")]


async def _error_handler(ctx: SOPContext) -> list[ReviewVerdict]:
    raise RuntimeError("unexpected handler error for testing")


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestReviewVerdict:
    def test_p0_is_blocking(self):
        v = _verdict("s", VerdictSeverity.P0)
        assert v.is_blocking
        assert v.is_p0

    def test_p1_is_blocking(self):
        v = _verdict("s", VerdictSeverity.P1)
        assert v.is_blocking
        assert not v.is_p0

    def test_p2_not_blocking(self):
        v = _verdict("s", VerdictSeverity.P2)
        assert not v.is_blocking

    def test_p3_not_blocking(self):
        v = _verdict("s", VerdictSeverity.P3)
        assert not v.is_blocking

    def test_description_required(self):
        with pytest.raises(Exception):
            ReviewVerdict(step_id="s", category="c", severity=VerdictSeverity.P0, description="short")

    def test_workflow_verdict_summary(self):
        wv = WorkflowVerdict(
            workflow_id="wf1",
            verdicts=[
                _verdict("s1", VerdictSeverity.P3),
                _verdict("s2", VerdictSeverity.P2),
            ],
        )
        assert wv.passed  # no P0/P1
        assert "PASS" in wv.summary()

    def test_workflow_verdict_fails_on_p1(self):
        wv = WorkflowVerdict(
            workflow_id="wf2",
            verdicts=[_verdict("s1", VerdictSeverity.P1)],
        )
        assert not wv.passed
        assert "FAIL" in wv.summary()


class TestSOPWorkflowEngine:
    @pytest.mark.asyncio
    async def test_all_pass(self):
        steps = [
            SOPStep("step1", "Step 1", "reviewer", _pass_handler),
            SOPStep("step2", "Step 2", "tester", _pass_handler),
        ]
        engine = SOPWorkflowEngine(steps)
        result = await engine.run("m-1", "test goal")
        assert result.passed
        assert "step1" in result.steps_completed
        assert "step2" in result.steps_completed
        assert result.steps_skipped == []

    @pytest.mark.asyncio
    async def test_p0_stops_workflow(self):
        steps = [
            SOPStep("step1", "Step 1", "reviewer", _pass_handler),
            SOPStep("step2", "Step 2", "reviewer", _fail_p0_handler),
            SOPStep("step3", "Step 3", "tester", _pass_handler),  # should be skipped
        ]
        engine = SOPWorkflowEngine(steps)
        result = await engine.run("m-2", "test p0 stop")
        assert not result.passed
        assert result.stopped_at == "step2"
        assert "step3" in result.steps_skipped
        assert result.verdict.p0_verdicts

    @pytest.mark.asyncio
    async def test_p1_fails_but_continues(self):
        steps = [
            SOPStep("step1", "Step 1", "reviewer", _fail_p1_handler),
            SOPStep("step2", "Step 2", "tester", _pass_handler),
        ]
        engine = SOPWorkflowEngine(steps)
        result = await engine.run("m-3", "test p1 continue")
        assert not result.passed
        assert result.stopped_at is None  # workflow did NOT stop
        assert "step2" in result.steps_completed

    @pytest.mark.asyncio
    async def test_step_error_creates_p1_verdict(self):
        steps = [
            SOPStep("step1", "Raises", "coder", _error_handler, required=True),
        ]
        engine = SOPWorkflowEngine(steps)
        result = await engine.run("m-4", "test error handling")
        assert "step1" in result.steps_completed  # error is handled, step listed as completed
        p1_verdicts = [v for v in result.verdict.verdicts if v.severity == VerdictSeverity.P1]
        assert len(p1_verdicts) == 1
        assert "engine_error" in p1_verdicts[0].category

    @pytest.mark.asyncio
    async def test_empty_workflow(self):
        engine = SOPWorkflowEngine(steps=[])
        result = await engine.run("m-5", "empty workflow")
        assert result.passed  # no verdicts = pass
        assert result.steps_completed == []


class TestAgentProfile:
    def test_from_role_sets_capabilities(self):
        profile = AgentProfile.from_role("abc123", AgentRole.CODER)
        assert "write" in profile.capabilities
        assert "sandbox" in profile.capabilities

    def test_gatekeeper_has_no_capabilities(self):
        profile = AgentProfile.from_role("gk1", AgentRole.GATEKEEPER)
        assert len(profile.capabilities) == 0

    def test_researcher_read_only(self):
        profile = AgentProfile.from_role("res1", AgentRole.RESEARCHER)
        assert "read" in profile.capabilities
        assert "write" not in profile.capabilities
        assert "execute" not in profile.capabilities
