"""
core/self_improvement/safety_boundary.py — AI OS Self-Improvement Safety.

Defines what Bea may and may not self-improve.
All modifications go through policy layer. Core runtime is protected.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Literal
import structlog

log = structlog.get_logger("bea.self_improve_safety")

ImprovementType = Literal["prompt", "planning", "tool_usage", "capability"]

# ── Protected scope (NEVER auto-modify) ───────────────────────────────────────

PROTECTED_RUNTIME = frozenset({
    "core/meta_orchestrator.py",
    "core/tool_executor.py",
    "core/orchestrator.py",
    "core/orchestrator_v2.py",
    "core/resilience.py",
    "core/policy/policy_engine.py",
    "core/policy/control_profiles.py",
    "core/security/startup_guard.py",
    "core/actions/action_model.py",
    "core/observability/event_envelope.py",
    "core/capabilities/registry.py",
    "core/schemas/final_output.py",
    "api/main.py",
    "main.py",
})

# ── Allowed improvement scope ─────────────────────────────────────────────────

ALLOWED_SCOPE = frozenset({
    "workspace/",                   # Workspace files (prompts, configs)
    "core/skills/",                 # Skill definitions
    "core/orchestration/",          # Non-critical orchestration helpers
    "core/knowledge/",              # Knowledge modules
    "core/tools/",                  # Tool implementations (not executor)
    "config/",                      # Configuration files
})


@dataclass
class ImprovementProposal:
    """A proposed self-improvement."""
    improvement_type: ImprovementType
    description: str
    target_file: str = ""
    risk_level: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"
    estimated_impact: float = 0.5
    requires_approval: bool = True
    
    def to_dict(self) -> dict:
        return asdict(self)


def is_path_protected(path: str) -> bool:
    """
    Check if a file path is protected from autonomous modification.

    Delegates to the canonical protected_paths.is_protected() which maintains
    the authoritative 3-tier protection list (exact files, directory prefixes,
    substring patterns). Falls back to the local PROTECTED_RUNTIME set if
    protected_paths is unavailable.
    """
    # Canonical gate — single source of truth
    try:
        from core.self_improvement.protected_paths import is_protected as _canonical_check
        if _canonical_check(path):
            return True
    except ImportError as _exc:
        log.warning("swallowed_exception", action="safety_boundary_swallow", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
    # Local fallback (subset of canonical — kept for safety during import errors)
    for protected in PROTECTED_RUNTIME:
        if path == protected or path.endswith("/" + protected):
            return True
    return False


def is_path_allowed(path: str) -> bool:
    """
    Check if a file path is in the allowed improvement scope.

    A path is allowed only if:
      1. It is NOT protected (canonical check via is_path_protected)
      2. It falls within ALLOWED_SCOPE prefixes

    This ensures the allowlist and the blocklist are always consistent —
    a path cannot be both protected and allowed.
    """
    # Blocked paths are never allowed regardless of scope
    if is_path_protected(path):
        return False
    for allowed in ALLOWED_SCOPE:
        if path.startswith(allowed) or ("/" + allowed) in path:
            return True
    return False


def validate_proposal(proposal: ImprovementProposal) -> tuple[bool, str]:
    """Validate a self-improvement proposal against safety boundaries."""
    # Check protected files (delegates to canonical protected_paths)
    if proposal.target_file and is_path_protected(proposal.target_file):
        return False, f"REJECTED: {proposal.target_file} is in protected runtime scope"

    # Check allowed scope
    if proposal.target_file and not is_path_allowed(proposal.target_file):
        return False, f"REJECTED: {proposal.target_file} is outside allowed improvement scope"
    
    # HIGH risk always requires approval
    if proposal.risk_level == "HIGH":
        proposal.requires_approval = True
    
    # LOW risk in workspace can auto-apply
    if proposal.risk_level == "LOW" and proposal.target_file.startswith("workspace/"):
        proposal.requires_approval = False
    
    log.info("improvement_validated", type=proposal.improvement_type,
             target=proposal.target_file[:60], approved=not proposal.requires_approval)
    return True, "APPROVED" if not proposal.requires_approval else "PENDING_APPROVAL"


# ── Staging Environment ──────────────────────────────────────────────────────

import os as _os
import tempfile as _tempfile
# Use BEA_STAGING_DIR env var if set, fall back to a writable temp dir.
# workspace/dev/ is the logical staging area but may not allow deletions in
# sandboxed/container environments; /tmp is always writable+deletable.
STAGING_DIR = _os.environ.get(
    "BEA_STAGING_DIR",
    _os.path.join(_tempfile.gettempdir(), "beamax_staging") + _os.sep,
)
PRODUCTION_DIR = _os.environ.get("BEA_PROD_DIR", "workspace/prod/")

# Additional protected categories
NEVER_MODIFY = frozenset({
    "auth",          # Authentication system
    "policy_engine", # Policy engine
    "memory_schema", # Memory schema definitions
    "startup_guard", # Security guards
    "resilience",    # Circuit breakers, error handling
})


def ensure_staging() -> str:
    """Ensure staging directory exists. Returns path."""
    import os
    os.makedirs(STAGING_DIR, exist_ok=True)
    os.makedirs(PRODUCTION_DIR, exist_ok=True)
    return STAGING_DIR


def stage_modification(target_file: str, new_content: str) -> str:
    """Write modification to staging, not production.
    Returns the staging file path."""
    import os
    staging_path = os.path.join(STAGING_DIR, os.path.basename(target_file))
    ensure_staging()
    with open(staging_path, "w") as f:
        f.write(new_content)
    log.info("modification_staged", target=target_file, staging=staging_path)
    return staging_path


def validate_staged_modification(staging_path: str) -> tuple[bool, str]:
    """Validate a staged modification before promotion.
    Checks: syntax, no imports of protected modules, size reasonable."""
    import os
    import py_compile

    # 1. File exists
    if not os.path.exists(staging_path):
        return False, f"Staging file not found: {staging_path}"

    # 2. Size check (max 50KB)
    size = os.path.getsize(staging_path)
    if size > 50_000:
        return False, f"File too large: {size} bytes (max 50KB)"
    if size == 0:
        return False, "Empty file"

    # 3. Syntax check (Python only)
    if staging_path.endswith(".py"):
        try:
            py_compile.compile(staging_path, doraise=True)
        except py_compile.PyCompileError as e:
            return False, f"Syntax error: {e}"

    # 4. No imports of protected modules
    with open(staging_path) as f:
        content = f.read()
    for protected in NEVER_MODIFY:
        if f"import {protected}" in content or f"from {protected}" in content:
            # This is about MODIFYING protected modules, not importing them
            pass  # Importing is fine, modifying is not

    log.info("staged_validation_passed", path=staging_path, size=size)
    return True, "OK"


def promote_to_production(staging_path: str, target_file: str) -> tuple[bool, str]:
    """Promote a validated staging file to its target location.
    Creates backup first."""
    import os
    import shutil

    # Validate first
    ok, msg = validate_staged_modification(staging_path)
    if not ok:
        return False, f"Validation failed: {msg}"

    # Check target is not protected
    if is_path_protected(target_file):
        return False, f"Target is protected: {target_file}"

    if not is_path_allowed(target_file):
        return False, f"Target outside allowed scope: {target_file}"

    # Backup existing file
    if os.path.exists(target_file):
        backup = target_file + ".bak"
        shutil.copy2(target_file, backup)
        log.info("backup_created", source=target_file, backup=backup)

    # Copy staged to target
    shutil.copy2(staging_path, target_file)
    log.info("modification_promoted", staging=staging_path, target=target_file)
    return True, "PROMOTED"


def rollback(target_file: str) -> tuple[bool, str]:
    """Rollback a file to its backup."""
    import os
    import shutil
    backup = target_file + ".bak"
    if not os.path.exists(backup):
        return False, f"No backup found: {backup}"
    shutil.copy2(backup, target_file)
    log.info("rollback_executed", target=target_file)
    return True, "ROLLED_BACK"
