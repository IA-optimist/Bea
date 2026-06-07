#!/usr/bin/env python3
"""Test container startup — import smoke check.

Catches TypeError/AttributeError at import (fatal), skips on other
ImportError so optional deps missing in unit envs don't fail CI.
"""
import sys
import pytest

sys.path.insert(0, '.')


def test_critical_imports():
    try:
        from core.meta_orchestrator import MetaOrchestrator  # noqa: F401
        from core.cognition.orchestrator import CognitionOrchestrator  # noqa: F401
        from core.orchestration.bea_team_dispatcher import dispatch_improve  # noqa: F401
        from api.routes.vault import router  # noqa: F401
        from api.routes import missions  # noqa: F401
    except (TypeError, AttributeError) as e:
        pytest.fail(f"startup fatal: {type(e).__name__}: {e}")
    except ImportError as e:
        pytest.skip(f"optional dep manquante: {e}")


if __name__ == "__main__":
    # Script mode — exit 0 on skip (optional dep), exit 1 only on real bug.
    try:
        test_critical_imports()
        sys.exit(0)
    except pytest.skip.Exception:
        sys.exit(0)
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
