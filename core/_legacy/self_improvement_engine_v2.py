"""
core/self_improvement_engine.py — DEPRECATED re-export shim.

Canonical location: core/self_improvement/engine.py (SelfImprovementEngine V3).
This file re-exports the legacy API for backward compatibility:
    - run_improvement_cycle()
    - get_improvement_report()

Callers should migrate to:
    from core.self_improvement.engine import SelfImprovementEngine
"""
from __future__ import annotations

import structlog

log = structlog.get_logger(__name__)

# Re-export V3 engine for callers that still use this module path.
try:
    from core.self_improvement.engine import SelfImprovementEngine

    _engine = None

    def _get_engine() -> SelfImprovementEngine:
        global _engine
        if _engine is None:
            _engine = SelfImprovementEngine()
        return _engine

    def run_improvement_cycle():
        """Deprecated: use SelfImprovementEngine directly."""
        log.warning("deprecated_call", fn="run_improvement_cycle",
                    msg="Use SelfImprovementEngine.run_cycle() instead")
        engine = _get_engine()
        if hasattr(engine, 'run_cycle'):
            return engine.run_cycle()
        return {"status": "skipped", "reason": "engine has no run_cycle method"}

    def get_improvement_report():
        """Deprecated: use SelfImprovementEngine directly."""
        log.warning("deprecated_call", fn="get_improvement_report",
                    msg="Use SelfImprovementEngine.get_report() instead")
        engine = _get_engine()
        if hasattr(engine, 'get_report'):
            return engine.get_report()
        return None

except ImportError:
    def run_improvement_cycle():
        return {"status": "unavailable", "reason": "V3 engine not loaded"}

    def get_improvement_report():
        return None
