"""
Source of truth for all protected paths — NEVER allow autonomous modification.

Three tiers:
  PROTECTED_FILES: exact file matches
  PROTECTED_DIRS: directory prefix matches (all files within)
  PROTECTED_PATTERNS: substring matches (auth/, security/, .env, etc.)

Rules:
  - Modification of this file requires explicit human approval
  - safe_executor, code_patcher, and promotion_pipeline ALL consult this
  - Any file matching ANY tier is blocked
"""
from __future__ import annotations


# ── Exact file matches ──────────────────────────────────────────
PROTECTED_FILES: frozenset[str] = frozenset({
    # Architecture core
    "core/meta_orchestrator.py",
    "core/orchestrator.py",
    "core/orchestrator_v2.py",
    "core/tool_executor.py",
    "core/policy_engine.py",
    "core/policy/policy_engine.py",
    "core/governance.py",
    "core/circuit_breaker.py",
    "executor/mission_result.py",
    "api/schemas.py",

    # Auth / security / RBAC
    "api/auth.py",
    "api/access_tokens.py",
    "api/access_enforcement.py",
    "api/middleware.py",

    # Vault / secrets
    "core/security/secret_vault.py",
    "core/security/secret_crypto.py",
    "core/security/secret_policy.py",

    # Runtime entrypoints
    "api/main.py",
    "config/settings.py",
    "main.py",

    # Infrastructure
    ".env",
    "docker-compose.yml",
    "docker/Dockerfile",

    # Kernel gate (self-improvement controller)
    "kernel/improvement/gate.py",

    # Self-improvement core controller (prevent self-modification loops)
    "core/self_improvement_loop.py",
    "core/self_improvement/protected_paths.py",

    # Test infrastructure
    "conftest.py",
})

# ── Architecture core subset (backward compat) ──
PROTECTED_FILES_ARCH: frozenset[str] = frozenset({
    "core/meta_orchestrator.py",
    "core/tool_executor.py",
    "core/orchestrator.py",
    "core/orchestrator_v2.py",
    "executor/mission_result.py",
    "api/schemas.py",
    "core/schemas/final_output.py",
    "core/actions/action_model.py",
    "core/observability/event_envelope.py",
    "core/policy/policy_engine.py",
    "core/resilience.py",
    "core/capabilities/registry.py",

    # Sécurité — JAMAIS modifiable par la SI loop
    "core/security/rbac.py",
    "core/security/startup_guard.py",
    "core/security/input_sanitizer.py",
    "api/auth.py",
    "api/_deps.py",
    "core/self_improvement/protected_paths.py",
    "core/self_improvement/safe_executor.py",

    # V3 Pipeline — JAMAIS modifiable par la SI loop elle-même
    "core/self_improvement/promotion_pipeline.py",
    "core/self_improvement/sandbox_executor.py",
    "core/self_improvement/git_agent.py",
    "core/self_improvement/human_gate.py",
    "core/self_improvement/code_patch_generator.py",
})

# ── Security subset (backward compat) ──
PROTECTED_FILES_SECURITY: frozenset[str] = frozenset({
    ".env",
    "config/settings.py",
    "docker-compose.yml",
    "docker/Dockerfile",
    "core/policy_engine.py",
    "core/circuit_breaker.py",
    "core/execution_guard.py",
    "risk/engine.py",
})

# ── Directory prefixes (all files within blocked) ──
PROTECTED_DIRS: frozenset[str] = frozenset({
    "core/security/",
    "api/routes/token_management.py",
})

# ── Substring patterns ──
PROTECTED_PATTERNS: tuple[str, ...] = (
    ".env",
    "secrets",
    "auth/",
    "security/",
)


def is_protected(filepath: str) -> bool:
    """
    Check if a file is protected from autonomous modification.
    Returns True if file matches ANY protection tier.
    """
    normalized = filepath.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]

    # Exact match
    if normalized in PROTECTED_FILES:
        return True

    # Directory prefix
    for d in PROTECTED_DIRS:
        if normalized.startswith(d):
            return True

    # Substring pattern
    for p in PROTECTED_PATTERNS:
        if p in normalized:
            return True

    return False
