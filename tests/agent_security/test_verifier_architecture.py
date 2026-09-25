from __future__ import annotations

"""
Static architecture tests — belt-and-suspenders checks.
Cannot guarantee runtime safety but make bypass visible in CI.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent


class TestArchitectureIntegrity:
    def test_verifier_broker_exists(self):
        assert (REPO_ROOT / "agent_security" / "verifier" / "broker.py").exists()

    def test_verifier_policy_exists(self):
        assert (REPO_ROOT / "agent_security" / "verifier" / "policy.py").exists()

    def test_verifier_audit_exists(self):
        assert (REPO_ROOT / "agent_security" / "verifier" / "audit.py").exists()

    def test_policy_has_no_llm_imports(self):
        """policy.py must never import any LLM client — deterministic only."""
        content = (REPO_ROOT / "agent_security" / "verifier" / "policy.py").read_text()
        # Check import statements specifically, not string literals (which may name APIs)
        forbidden_import_patterns = [
            "import openai", "from openai",
            "import anthropic", "from anthropic",
            "import langchain", "from langchain",
            "import litellm", "from litellm",
            "import ollama", "from ollama",
        ]
        for pattern in forbidden_import_patterns:
            assert pattern not in content.lower(), f"policy.py imports LLM library via: {pattern}"

    def test_policy_has_no_natural_language_processing(self):
        """Policy must not use spacy, nltk, or similar NLP libs."""
        content = (REPO_ROOT / "agent_security" / "verifier" / "policy.py").read_text()
        nlp_libs = ["spacy", "nltk", "transformers", "sentence_transformers"]
        for lib in nlp_libs:
            assert lib not in content.lower()

    def test_audit_does_not_log_raw_parameters(self):
        """audit.py must not serialize intent.parameters values."""
        content = (REPO_ROOT / "agent_security" / "verifier" / "audit.py").read_text()
        # Should NOT have: entry["parameters"] = intent.parameters
        assert '"parameters": intent.parameters' not in content
        assert "'parameters': intent.parameters" not in content

    def test_exceptions_inherit_verifier_error(self):
        from agent_security.verifier.exceptions import (
            VerifierDenied,
            VerifierError,
            VerifierHaltTriggered,
            VerifierHoldRequired,
            VerifierUnavailable,
        )
        for exc_cls in [VerifierDenied, VerifierHaltTriggered, VerifierHoldRequired, VerifierUnavailable]:
            assert issubclass(exc_cls, VerifierError), f"{exc_cls.__name__} must inherit VerifierError"

    def test_integration_status_honest(self):
        from agent_security.verifier.broker import INTEGRATION_STATUS
        interface_only = sum(1 for v in INTEGRATION_STATUS.values() if "INTERFACE_ONLY" in v)
        assert interface_only >= 3, "v0 should honestly report at least 3 unwired effectuors"
        # Keys should match ActionType enum values (lowercase)
        assert "filesystem_read" in INTEGRATION_STATUS
        assert "exec_command" in INTEGRATION_STATUS

    def test_broker_has_required_interface(self):
        from agent_security.verifier.broker import VerifierBroker
        assert callable(getattr(VerifierBroker, "execute", None))
        assert callable(getattr(VerifierBroker, "register_effectuor", None))
        assert callable(getattr(VerifierBroker, "get_integration_status", None))

    def test_intent_is_frozen_model(self):
        """ActionIntent must be immutable so callers cannot tamper after creation."""
        from agent_security.verifier.models import ActionIntent, ActionType, EffectScope
        intent = ActionIntent(
            actor_id="bea",
            action_type=ActionType.FILESYSTEM_READ,
            target="/workspace/x.py",
            declared_scope=EffectScope.LOCAL_READONLY,
        )
        # frozen=True means attribute assignment raises
        with pytest.raises(Exception):
            intent.actor_id = "attacker"  # type: ignore[misc]

    def test_verifier_package_importable(self):
        from agent_security.verifier import (
            ActionIntent,
            VerifierBroker,
            VerifierDenied,
            VerifierPolicy,
        )
        assert VerifierBroker is not None

    def test_policy_evaluate_never_raises(self):
        """policy.evaluate() is guaranteed not to raise — always returns a decision."""
        from agent_security.verifier.policy import VerifierPolicy
        from agent_security.verifier.models import ActionIntent, ActionType, EffectScope

        policy = VerifierPolicy()
        intent = ActionIntent(
            actor_id="bea",
            action_type=ActionType.EXEC_COMMAND,
            target="rm -rf /",
            declared_scope=EffectScope.SYSTEM,
        )
        # Must not raise
        decision = policy.evaluate(intent)
        assert decision is not None
