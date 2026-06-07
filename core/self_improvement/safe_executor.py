"""
SafeSelfImprovementExecutor — applies exactly ONE improvement candidate safely.

Protected files (NEVER modified — raises ValueError if targeted):
  See core/self_improvement/protected_paths.py (PROTECTED_FILES_ARCH)

Allowed write targets:
  PROMPT_TWEAK    → workspace/prompts/{domain}.txt
  TOOL_PREFERENCE → workspace/preferences/tool_prefs.json
  RETRY_STRATEGY  → workspace/preferences/retry_config.json
  SKIP_PATTERN    → workspace/preferences/skip_patterns.json

All writes are atomic (tmp + rename). Backup is kept for rollback.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("bea.self_improvement.safe_executor")

from core.self_improvement.protected_paths import PROTECTED_FILES_ARCH as PROTECTED_FILES, PROTECTED_DIRS


@dataclass
class ExecutionResult:
    success: bool = False
    output: str = ""
    error: str = ""
    applied_change: str = ""
    changed_file: str = ""
    rollback_triggered: bool = False
    backup_text: str | None = None

_WORKSPACE = Path("workspace")


@dataclass
class PatchResult:  # SI-specific result for code patches
    success: bool
    applied_change: str
    rollback_triggered: bool
    error: str = ""
    confidence: float = 0.0  # 0.0-1.0 confidence in the change
    risk_level: str = "low"  # low/medium/high
    diff_summary: str = ""   # human-readable change description
    revert_path: str = ""    # path to backup file for reversal


class SafeSelfImprovementExecutor:
    """
    Applies the top-1 improvement candidate.
    Any exception during write triggers a rollback and returns success=False.
    """

    def execute(self, candidate) -> ExecutionResult:
        """
        Dispatches to the appropriate handler based on candidate.type.
        Returns ExecutionResult — never raises.
        """
        ctype = getattr(candidate, "type", "")
        logger.info(
            "[SafeExecutor] applying type=%s domain=%s",
            ctype,
            getattr(candidate, "domain", "?"),
        )

        try:
            if ctype == "PROMPT_TWEAK":
                return self._apply_prompt_tweak(candidate)
            if ctype == "TOOL_PREFERENCE":
                return self._apply_tool_preference(candidate)
            if ctype == "RETRY_STRATEGY":
                return self._apply_retry_strategy(candidate)
            if ctype == "SKIP_PATTERN":
                return self._apply_skip_pattern(candidate)
            return ExecutionResult(
                success=False,
                applied_change="",
                rollback_triggered=False,
                error=f"Unknown candidate type: {ctype!r}",
            )
        except Exception as exc:
            logger.warning("[SafeExecutor] unexpected error: %s", exc)
            return ExecutionResult(
                success=False,
                applied_change="",
                rollback_triggered=True,
                error=str(exc),
            )

    # ── Handlers ─────────────────────────────────────────────────────────────

    def _apply_prompt_tweak(self, candidate) -> ExecutionResult:
        domain = getattr(candidate, "domain", "general")
        description = getattr(candidate, "description", "")

        prompts_dir = _WORKSPACE / "prompts"
        prompts_dir.mkdir(parents=True, exist_ok=True)

        target = prompts_dir / f"{domain}.txt"
        self._assert_safe(target)

        backup = target.read_text("utf-8") if target.exists() else None

        try:
            ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            if backup:
                content = backup + f"\n\n# Update {ts}: {description}\n"
            else:
                content = (
                    f"# Prompt tweak for {domain}\n"
                    f"# Applied: {ts}\n"
                    f"# {description}\n"
                )
            _atomic_write(target, content)
            return ExecutionResult(
                success=True,
                applied_change=f"PROMPT_TWEAK: wrote {target}",
                rollback_triggered=False,
            )
        except Exception as exc:
            _rollback(target, backup)
            return ExecutionResult(
                success=False,
                applied_change="",
                rollback_triggered=True,
                error=str(exc),
            )

    def _apply_tool_preference(self, candidate) -> ExecutionResult:
        domain = getattr(candidate, "domain", "general")
        description = getattr(candidate, "description", "")

        prefs_dir = _WORKSPACE / "preferences"
        prefs_dir.mkdir(parents=True, exist_ok=True)

        target = prefs_dir / "tool_prefs.json"
        self._assert_safe(target)

        backup_text = target.read_text("utf-8") if target.exists() else None
        data: dict = {}
        if backup_text:
            try:
                data = json.loads(backup_text)
            except Exception:
                data = {}

        try:
            data[domain] = {
                "preference_note": description,
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            _atomic_write(target, json.dumps(data, indent=2))
            return ExecutionResult(
                success=True,
                applied_change=f"TOOL_PREFERENCE: updated {target} domain={domain}",
                rollback_triggered=False,
            )
        except Exception as exc:
            _rollback_text(target, backup_text)
            return ExecutionResult(
                success=False,
                applied_change="",
                rollback_triggered=True,
                error=str(exc),
            )

    def _apply_retry_strategy(self, candidate) -> ExecutionResult:
        domain = getattr(candidate, "domain", "general")
        description = getattr(candidate, "description", "")

        prefs_dir = _WORKSPACE / "preferences"
        prefs_dir.mkdir(parents=True, exist_ok=True)

        target = prefs_dir / "retry_config.json"
        self._assert_safe(target)

        backup_text = target.read_text("utf-8") if target.exists() else None
        data: dict = {}
        if backup_text:
            try:
                data = json.loads(backup_text)
            except Exception:
                data = {}

        try:
            data[domain] = {
                "max_retries": 3,
                "delay_s": 2,
                "strategy_note": description,
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            _atomic_write(target, json.dumps(data, indent=2))
            return ExecutionResult(
                success=True,
                applied_change=f"RETRY_STRATEGY: updated {target} domain={domain}",
                rollback_triggered=False,
            )
        except Exception as exc:
            _rollback_text(target, backup_text)
            return ExecutionResult(
                success=False,
                applied_change="",
                rollback_triggered=True,
                error=str(exc),
            )

    def _apply_skip_pattern(self, candidate) -> ExecutionResult:
        domain = getattr(candidate, "domain", "general")
        description = getattr(candidate, "description", "")

        prefs_dir = _WORKSPACE / "preferences"
        prefs_dir.mkdir(parents=True, exist_ok=True)

        target = prefs_dir / "skip_patterns.json"
        self._assert_safe(target)

        backup_text = target.read_text("utf-8") if target.exists() else None
        data: dict = {"patterns": []}
        if backup_text:
            try:
                data = json.loads(backup_text)
                if "patterns" not in data:
                    data["patterns"] = []
            except Exception:
                data = {"patterns": []}

        try:
            data["patterns"].append({
                "domain": domain,
                "pattern": description,
                "added_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })
            _atomic_write(target, json.dumps(data, indent=2))
            return ExecutionResult(
                success=True,
                applied_change=f"SKIP_PATTERN: added pattern to {target}",
                rollback_triggered=False,
            )
        except Exception as exc:
            _rollback_text(target, backup_text)
            return ExecutionResult(
                success=False,
                applied_change="",
                rollback_triggered=True,
                error=str(exc),
            )

    # ── Safety guard ─────────────────────────────────────────────────────────

    def _assert_safe(self, path: Path) -> None:
        """
        Raises ValueError if path matches any protected file or directory.
        Checks both PROTECTED_FILES (exact suffixes) and PROTECTED_DIRS (prefixes).
        """
        normalized = str(path).replace("\\", "/")

        # Vérifier les répertoires protégés (whitelist négative)
        for protected_dir in PROTECTED_DIRS:
            if normalized.startswith(protected_dir) or f"/{protected_dir}" in normalized:
                raise ValueError(
                    f"Attempt to modify file in protected directory: {path} "
                    f"(protected dir: {protected_dir})"
                )

        # Vérifier les fichiers protégés individuels
        for protected in PROTECTED_FILES:
            if normalized.endswith(protected) or protected in normalized:
                raise ValueError(f"Attempt to modify protected file: {path}")


# ── Atomic write helpers ──────────────────────────────────────────────────────

def _atomic_write(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, "utf-8")
    tmp.replace(path)


def _rollback(path: Path, backup: str | None) -> None:
    try:
        if backup is not None:
            path.write_text(backup, "utf-8")
        elif path.exists():
            path.unlink()
    except Exception as e:
        logger.debug(f"rollback failed: {e}")


def _rollback_text(path: Path, backup_text: str | None) -> None:
    _rollback(path, backup_text)


# ── Singleton ─────────────────────────────────────────────────────────────────

_executor: SafeSelfImprovementExecutor | None = None


def get_safe_executor() -> SafeSelfImprovementExecutor:
    global _executor
    if _executor is None:
        _executor = SafeSelfImprovementExecutor()
    return _executor


# Backward compatibility alias
# Legacy alias removed — use PatchResult directly or executor.contracts.ExecutionResult
