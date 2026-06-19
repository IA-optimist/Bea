"""
Tests — MetaOrchestrator
Core functionality tests for the main orchestration entry point.

Coverage:
    1. MetaOrchestrator initialization and lazy loading
    2. State machine transitions (CREATED → PLANNED → RUNNING → DONE)
    3. Circuit breaker behavior
    4. Mission context management
    5. Event stream integration
    6. Decision trace
"""
import sys
import os
import tempfile
import types
import pytest
import time
from unittest.mock import Mock, patch

# Bootstrap path & mock structlog
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    import structlog  # noqa: F401
except ImportError:
    mock_sl = types.ModuleType("structlog")
    mock_sl.get_logger = lambda *a, **k: types.SimpleNamespace(
        debug=lambda *a, **k: None,
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
    )
    sys.modules["structlog"] = mock_sl

# Mock settings
class _FakeSettings:
    def __init__(self):
        self.workspace_dir = tempfile.mkdtemp()
        self.llm_provider = "openai"
        self.model = "gpt-4"
        self.qdrant_enabled = False
        self.database_url = "sqlite:///test.db"

@pytest.fixture
def settings():
    return _FakeSettings()

@pytest.fixture
def meta_orchestrator(settings):
    """Create a MetaOrchestrator instance with mocked dependencies."""
    from core.meta_orchestrator import MetaOrchestrator
    return MetaOrchestrator(settings=settings)


# ═══════════════════════════════════════════════════════════════
# INITIALIZATION TESTS
# ═══════════════════════════════════════════════════════════════

def test_meta_orchestrator_initialization(settings):
    """MetaOrchestrator should initialize with proper defaults."""
    from core.meta_orchestrator import MetaOrchestrator
    
    mo = MetaOrchestrator(settings=settings)
    
    assert mo.s == settings
    assert mo._bea is None  # Lazy loaded
    assert mo._v2 is None  # Lazy loaded
    assert len(mo._missions) == 0
    assert mo._circuit_breaker is not None
    print("[OK] test_meta_orchestrator_initialization")


def test_lazy_loading_bea(meta_orchestrator):
    """BeaOrchestrator should be lazy loaded on first access."""
    with patch('core.bea_executor.BeaOrchestrator') as MockBea:
        mock_instance = Mock()
        MockBea.return_value = mock_instance
        
        # First access should trigger loading
        bea = meta_orchestrator.bea
        assert bea is not None
        MockBea.assert_called_once()
        
        # Second access should reuse same instance
        bea2 = meta_orchestrator.bea
        assert bea is bea2
        assert MockBea.call_count == 1
    print("[OK] test_lazy_loading_bea")


def test_lazy_loading_v2(meta_orchestrator):
    """OrchestratorV2 should be lazy loaded on first access."""
    with patch('core.orchestrator_v2.OrchestratorV2') as MockV2:
        mock_instance = Mock()
        MockV2.return_value = mock_instance
        
        v2 = meta_orchestrator.v2
        assert v2 is not None
        MockV2.assert_called_once()
    print("[OK] test_lazy_loading_v2")


# ═══════════════════════════════════════════════════════════════
# STATE MACHINE TESTS
# ═══════════════════════════════════════════════════════════════

def test_mission_context_creation():
    """MissionContext should be created with proper fields."""
    from core.meta_orchestrator import MissionContext
    from core.state import MissionStatus
    
    ctx = MissionContext(
        mission_id="test-123",
        goal="Test mission",
        mode="bea-research",
        status=MissionStatus.CREATED,
        created_at=time.time(),
        updated_at=time.time(),
    )
    
    assert ctx.mission_id == "test-123"
    assert ctx.goal == "Test mission"
    assert ctx.status == MissionStatus.CREATED
    assert ctx.result is None
    assert ctx.error is None
    print("[OK] test_mission_context_creation")


def test_valid_state_transitions(meta_orchestrator):
    """Valid state transitions should succeed."""
    from core.meta_orchestrator import MissionContext
    from core.state import MissionStatus
    
    ctx = MissionContext(
        mission_id="test-123",
        goal="Test mission",
        mode="bea-research",
        status=MissionStatus.CREATED,
        created_at=time.time(),
        updated_at=time.time(),
    )
    
    # Mock persistence to avoid DB calls
    with patch('core.mission_persistence.get_mission_persistence'):
        # CREATED → PLANNED (valid)
        meta_orchestrator._transition(ctx, MissionStatus.PLANNED)
        assert ctx.status == MissionStatus.PLANNED
        
        # PLANNED → RUNNING (valid)
        meta_orchestrator._transition(ctx, MissionStatus.RUNNING)
        assert ctx.status == MissionStatus.RUNNING
        
        # RUNNING → REVIEW (valid)
        meta_orchestrator._transition(ctx, MissionStatus.REVIEW)
        assert ctx.status == MissionStatus.REVIEW
        
        # REVIEW → DONE (valid)
        meta_orchestrator._transition(ctx, MissionStatus.DONE)
        assert ctx.status == MissionStatus.DONE
    
    print("[OK] test_valid_state_transitions")


@pytest.mark.stale
@pytest.mark.xfail(reason="transition error message drift", strict=False)
def test_invalid_state_transition_raises(meta_orchestrator):
    """Invalid state transitions should raise ValueError."""
    from core.meta_orchestrator import MissionContext
    from core.state import MissionStatus
    
    ctx = MissionContext(
        mission_id="test-123",
        goal="Test mission",
        mode="bea-research",
        status=MissionStatus.CREATED,
        created_at=time.time(),
        updated_at=time.time(),
    )
    
    with patch('core.mission_persistence.get_mission_persistence'):
        # CREATED → DONE (invalid - must go through intermediate states)
        with pytest.raises(ValueError, match="Transition interdite"):
            meta_orchestrator._transition(ctx, MissionStatus.DONE)
    
    print("[OK] test_invalid_state_transition_raises")


# ═══════════════════════════════════════════════════════════════
# CIRCUIT BREAKER TESTS
# ═══════════════════════════════════════════════════════════════

def test_circuit_breaker_opens_after_failures():
    """Circuit breaker should open after threshold failures."""
    from core.meta_orchestrator import _CircuitBreaker
    
    cb = _CircuitBreaker(failure_threshold=3, reset_s=60.0)
    
    assert not cb.is_open
    
    # Record failures
    cb.record_failure()
    assert not cb.is_open
    
    cb.record_failure()
    assert not cb.is_open
    
    cb.record_failure()
    assert cb.is_open  # Should open after 3rd failure
    
    status = cb.status()
    assert status["open"] is True
    assert status["failures"] == 3
    
    print("[OK] test_circuit_breaker_opens_after_failures")


def test_circuit_breaker_resets_on_success():
    """Circuit breaker should reset failure count on success."""
    from core.meta_orchestrator import _CircuitBreaker
    
    cb = _CircuitBreaker(failure_threshold=3, reset_s=60.0)
    
    cb.record_failure()
    cb.record_failure()
    assert not cb.is_open
    
    cb.record_success()
    status = cb.status()
    assert status["failures"] == 0
    assert not cb.is_open
    
    print("[OK] test_circuit_breaker_resets_on_success")


def test_circuit_breaker_auto_resets_after_timeout():
    """Circuit breaker should auto-reset after timeout period."""
    from core.meta_orchestrator import _CircuitBreaker
    
    cb = _CircuitBreaker(failure_threshold=2, reset_s=0.1)  # 100ms reset
    
    cb.record_failure()
    cb.record_failure()
    assert cb.is_open
    
    # Wait for auto-reset
    time.sleep(0.15)
    
    # Should be closed now
    assert not cb.is_open
    
    print("[OK] test_circuit_breaker_auto_resets_after_timeout")


# ═══════════════════════════════════════════════════════════════
# HELPER METHODS TESTS
# ═══════════════════════════════════════════════════════════════

def test_setup_event_stream(meta_orchestrator):
    """Event stream setup should register streams properly."""
    from core.meta_orchestrator import MissionContext
    from core.state import MissionStatus
    
    ctx = MissionContext(
        mission_id="test-123",
        goal="Test mission",
        mode="bea-research",
        status=MissionStatus.CREATED,
        created_at=time.time(),
        updated_at=time.time(),
    )
    
    with patch('core.event_stream.EventStream') as MockEventStream:
        with patch('core.event_stream.register_mission_stream'):
            with patch('core.event_stream.register_ws_stream'):
                mock_stream = Mock()
                MockEventStream.return_value = mock_stream

                meta_orchestrator._setup_event_stream("test-123", ctx)

                assert ctx.metadata.get("event_stream") == mock_stream
    
    print("[OK] test_setup_event_stream")


def test_check_circuit_breaker_when_open(meta_orchestrator):
    """Circuit breaker check should fail mission when open."""
    from core.meta_orchestrator import MissionContext
    from core.state import MissionStatus
    
    ctx = MissionContext(
        mission_id="test-123",
        goal="Test mission",
        mode="bea-research",
        status=MissionStatus.CREATED,
        created_at=time.time(),
        updated_at=time.time(),
    )
    
    # Force circuit breaker open
    meta_orchestrator._circuit_breaker._failures = 10
    meta_orchestrator._circuit_breaker._open_until = time.time() + 60
    
    with patch('core.mission_persistence.get_mission_persistence'):
        result = meta_orchestrator._check_circuit_breaker("test-123", ctx)
        
        assert result is True  # Should return True when open
        assert ctx.status == MissionStatus.FAILED
        assert "Circuit breaker" in ctx.error
    
    print("[OK] test_check_circuit_breaker_when_open")


def test_initialize_decision_trace(meta_orchestrator):
    """Decision trace should be initialized properly."""
    with patch('core.orchestration.decision_trace.DecisionTrace') as MockTrace:
        mock_trace = Mock()
        MockTrace.return_value = mock_trace
        
        trace, needs_approval = meta_orchestrator._initialize_decision_trace("test-123")
        
        assert trace == mock_trace
        assert needs_approval is False
        MockTrace.assert_called_once_with(mission_id="test-123")
    
    print("[OK] test_initialize_decision_trace")


# ═══════════════════════════════════════════════════════════════
# INTEGRATION TESTS (mocked dependencies)
# ═══════════════════════════════════════════════════════════════

@pytest.mark.skip(reason="requires full dependency mocking - integration test")
def test_run_mission_simple(meta_orchestrator):
    """Simple mission execution should work end-to-end."""
    # This would require extensive mocking of all dependencies
    # Skipped for now - focus on unit tests
    pass


def test_mission_context_to_dict():
    """MissionContext.to_dict() should serialize properly."""
    from core.meta_orchestrator import MissionContext
    from core.state import MissionStatus
    
    ctx = MissionContext(
        mission_id="test-123",
        goal="Test mission with a very long goal that should be truncated" * 10,
        mode="bea-research",
        status=MissionStatus.DONE,
        created_at=1234567890.0,
        updated_at=1234567900.0,
        result="Success result" * 100,  # Long result
    )
    
    d = ctx.to_dict()
    
    assert d["mission_id"] == "test-123"
    assert len(d["goal"]) <= 200  # Should be truncated
    # Note: result truncation is done at serialization time, not in to_dict()
    # We'll just check that result exists
    assert "result" in d
    assert d["status"] == "DONE"
    
    print("[OK] test_mission_context_to_dict")


def test_mission_context_get_output():
    """MissionContext.get_output() should retrieve agent outputs."""
    from core.meta_orchestrator import MissionContext
    from core.state import MissionStatus
    
    ctx = MissionContext(
        mission_id="test-123",
        goal="Test mission",
        mode="bea-research",
        status=MissionStatus.RUNNING,
        created_at=time.time(),
        updated_at=time.time(),
        metadata={
            "agent_outputs": {
                "scout-research": "Research findings",
                "lens-reviewer": "Review complete",
            }
        }
    )
    
    output = ctx.get_output("scout-research")
    assert output == "Research findings"
    
    output = ctx.get_output("lens-reviewer")
    assert output == "Review complete"
    
    output = ctx.get_output("nonexistent-agent")
    assert output == ""
    
    print("[OK] test_mission_context_get_output")


# ═══════════════════════════════════════════════════════════════
# RUN ALL TESTS
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
