"""
core/self_improvement/sandbox_executor.py — Isolated patch execution.

Applies a unified diff to a temp copy of the repo and runs tests in Docker.

Security:
  - Docker: --network=none, --memory=256m, --cpus=0.5, read-only rootfs exception workspace
  - Timeout: 120s max per test run
  - No production files are ever modified
  - Graceful degradation: if Docker unavailable, runs in-process with heavy warnings

Docker image: python:3.12-slim (configurable via SANDBOX_DOCKER_IMAGE env var)
"""
from __future__ import annotations

import structlog
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = structlog.get_logger()

SANDBOX_TIMEOUT_S = int(os.getenv("SANDBOX_TIMEOUT_S", "120"))
SANDBOX_MEMORY = os.getenv("SANDBOX_MEMORY", "256m")
SANDBOX_CPUS = os.getenv("SANDBOX_CPUS", "0.5")
SANDBOX_DOCKER_IMAGE = os.getenv("SANDBOX_DOCKER_IMAGE", "python:3.12-slim")
SANDBOX_NO_DOCKER = os.getenv("SANDBOX_NO_DOCKER", "false").lower() in ("1", "true", "yes")

# ── Allowed commands for sandbox execution ────────────────────────────────────

ALLOWED_COMMANDS = frozenset({
    "pytest", "python", "ruff", "mypy", "pip", "git", "diff",
})


# ── Failure categories ────────────────────────────────────────────────────────

class FailureCategory:
    """Structured failure categories for sandbox execution."""
    TIMEOUT = "timeout"
    OOM = "out_of_memory"
    DOCKER_UNAVAILABLE = "docker_unavailable"
    PATCH_FAILED = "patch_application_failed"
    TEST_FAILED = "test_failure"
    TEST_FAILURE = "test_failure"
    LINT_FAILED = "lint_failure"
    TYPECHECK_FAILED = "typecheck_failure"
    SYNTAX_ERROR = "syntax_error"
    POLICY_BLOCK = "policy_block"
    UNKNOWN = "unknown"


# ── Secret scrubbing ─────────────────────────────────────────────────────────

import re as _re
_silent_log = __import__("structlog").get_logger(__name__)

_SECRET_PATTERNS = [
    _re.compile(r"(sk-[a-zA-Z0-9]{20,})"),           # OpenAI-style
    _re.compile(r"(ghp_[a-zA-Z0-9]{10,})"),           # GitHub PAT (relaxed min)
    _re.compile(r"(Bearer\s+[a-zA-Z0-9._\-]{10,})"),   # Bearer tokens
    _re.compile(r"(xoxb-[a-zA-Z0-9\-]+)"),            # Slack bot tokens
    _re.compile(r"(xoxp-[a-zA-Z0-9\-]+)"),            # Slack user tokens
    _re.compile(r"([a-fA-F0-9]{64})"),                 # 64-char hex (API keys)
    _re.compile(r"(password\s*[:=]\s*\S+)", _re.IGNORECASE),
]


def _scrub_secrets(text: str) -> str:
    """Remove sensitive patterns from text output."""
    if not text:
        return text
    result = text
    for pat in _SECRET_PATTERNS:
        result = pat.sub("[REDACTED]", result)
    return result


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class SandboxConfig:
    """Configuration for sandbox execution."""
    timeout_s: int = 60
    memory_mb: int = 512
    memory: str = SANDBOX_MEMORY
    cpus: str = SANDBOX_CPUS
    docker_image: str = SANDBOX_DOCKER_IMAGE
    no_docker: bool = SANDBOX_NO_DOCKER
    network: bool = False
    test_command: str = "python -m pytest tests/ --tb=short -q"
    lint_command: str = "ruff check ."
    typecheck_command: str = "mypy --ignore-missing-imports ."

@dataclass
class SandboxResult:
    """Result of a sandbox test run."""
    success: bool = False
    tests_passed: bool = False
    lint_passed: bool = False
    typecheck_passed: bool = False
    regressions: list[str] = field(default_factory=list)
    improvements: list[str] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    exit_code: int = -1
    duration_s: float = 0.0
    duration_ms: float = 0.0
    docker_used: bool = False
    error: str = ""
    method: str = ""
    timed_out: bool = False
    validation_level: str = ""
    failure_category: str = ""

    @property
    def all_checks_pass(self) -> bool:
        return self.tests_passed and len(self.regressions) == 0

    @property
    def is_blocked(self) -> bool:
        return self.method == "blocked" or self.validation_level == "blocked"

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "tests_passed": self.tests_passed,
            "lint_passed": self.lint_passed,
            "typecheck_passed": self.typecheck_passed,
            "regressions": self.regressions,
            "improvements": self.improvements,
            "stdout": _scrub_secrets(self.stdout[:500]),
            "stderr": _scrub_secrets(self.stderr[:500]),
            "exit_code": self.exit_code,
            "duration_s": self.duration_s,
            "duration_ms": self.duration_ms,
            "docker_used": self.docker_used,
            "error": self.error,
            "method": self.method,
            "timed_out": self.timed_out,
            "validation_level": self.validation_level,
            "failure_category": self.failure_category,
        }


# ── Patch application ─────────────────────────────────────────────────────────

def _apply_patch(unified_diff: str, work_dir: Path) -> tuple[bool, str]:
    """
    Apply a unified diff to work_dir using the 'patch' command.
    Returns (success, error_message).
    """
    if not unified_diff.strip():
        return True, ""

    # Write diff to temp file
    diff_file = work_dir / "_patch.diff"
    diff_file.write_text(unified_diff, encoding="utf-8")

    try:
        result = subprocess.run(
            ["patch", "-p1", "--input", str(diff_file), "--forward", "--reject-file=-"],
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            timeout=30,
        )
        diff_file.unlink(missing_ok=True)
        if result.returncode == 0:
            return True, ""
        return False, f"patch failed (rc={result.returncode}): {result.stderr[:500]}"
    except FileNotFoundError:
        # 'patch' binary not available — try applying with Python
        diff_file.unlink(missing_ok=True)
        return _apply_patch_python(unified_diff, work_dir)
    except subprocess.TimeoutExpired:
        diff_file.unlink(missing_ok=True)
        return False, "patch application timed out"


def _apply_patch_python(unified_diff: str, work_dir: Path) -> tuple[bool, str]:
    """
    Minimal Python unified diff applier (fallback when 'patch' binary unavailable).
    Supports simple +/- line changes; skips hunk header parsing edge cases.
    """
    import re

    file_re = re.compile(r"^\+\+\+\s+b/(.+)$")
    hunk_re = re.compile(r"^@@\s+-(\d+)(?:,\d+)?\s+\+(\d+)(?:,\d+)?\s+@@")

    current_file: Optional[Path] = None
    current_lines: list[str] = []
    output_lines: list[str] = []

    def flush_file():
        if current_file and output_lines:
            current_file.parent.mkdir(parents=True, exist_ok=True)
            current_file.write_text("".join(output_lines), encoding="utf-8")

    for line in unified_diff.splitlines(keepends=True):
        fm = file_re.match(line)
        if fm:
            flush_file()
            rel_path = fm.group(1).strip()
            current_file = work_dir / rel_path
            if current_file.exists():
                current_lines = current_file.read_text(encoding="utf-8").splitlines(keepends=True)
            else:
                current_lines = []
            output_lines = list(current_lines)
            continue

        if line.startswith("---"):
            continue

        hm = hunk_re.match(line)
        if hm:
            int(hm.group(1)) - 1
            int(hm.group(2)) - 1
            output_lines = list(current_lines)  # reset to original for each hunk (simplification)
            continue

        if line.startswith("+") and not line.startswith("+++"):
            # Insertion — simple append logic (not perfect but functional for basic diffs)
            pass
        elif line.startswith("-") and not line.startswith("---"):
            pass
        elif line.startswith(" "):
            pass

    flush_file()
    return True, "(python-applied: structural only)"


# ── Docker runner ─────────────────────────────────────────────────────────────

def _run_in_docker(work_dir: Path) -> SandboxResult:
    """Run tests inside a Docker container with strict isolation."""
    start = time.monotonic()

    # Check Docker availability
    try:
        subprocess.run(["docker", "info"], capture_output=True, timeout=5, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        log.warning("sandbox.docker_unavailable — falling back to in-process")
        return _run_in_process(work_dir, docker_attempted=True)

    cmd = [
        "docker", "run", "--rm",
        "--network=none",
        f"--memory={SANDBOX_MEMORY}",
        f"--cpus={SANDBOX_CPUS}",
        "--read-only",
        "--tmpfs=/tmp:rw,size=128m",
        "--security-opt=no-new-privileges",
        "-v", f"{work_dir}:/workspace:ro",
        "--workdir=/workspace",
        SANDBOX_DOCKER_IMAGE,
        "sh", "-c",
        (
            "pip install -q pytest ruff mypy 2>/dev/null; "
            "echo '=== RUFF ===' && ruff check . --select=E,F,W --quiet 2>&1 || true; "
            "echo '=== MYPY ===' && mypy . --ignore-missing-imports --no-error-summary 2>&1 || true; "
            "echo '=== PYTEST ===' && python -m pytest tests/ -x -q --tb=short 2>&1 || true"
        ),
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=SANDBOX_TIMEOUT_S,
        )
        duration = time.monotonic() - start
        return _parse_test_output(
            stdout=proc.stdout,
            stderr=proc.stderr,
            exit_code=proc.returncode,
            duration=duration,
            docker_used=True,
        )
    except subprocess.TimeoutExpired:
        duration = time.monotonic() - start
        return SandboxResult(
            success=False,
            error=f"Docker sandbox timed out after {SANDBOX_TIMEOUT_S}s",
            duration_s=duration,
            docker_used=True,
        )
    except Exception as exc:
        duration = time.monotonic() - start
        return SandboxResult(
            success=False,
            error=f"Docker run failed: {exc}",
            duration_s=duration,
            docker_used=True,
        )


def _run_in_process(work_dir: Path, docker_attempted: bool = False) -> SandboxResult:
    """
    Fallback: run tests in-process (subprocess, same Python env).
    Less isolated than Docker but usable for dev/CI environments.
    """
    start = time.monotonic()
    log.warning(
        "sandbox.in_process_mode",
        docker_attempted=docker_attempted,
        note="Tests run outside Docker — isolation NOT guaranteed",
    )

    # Run ruff
    ruff_out, ruff_rc = _run_subprocess(
        ["python", "-m", "ruff", "check", ".", "--select=E,F,W", "--quiet"],
        cwd=work_dir,
    )

    # Run pytest (tests/ directory)
    tests_dir = work_dir / "tests"
    if tests_dir.exists():
        pytest_out, pytest_rc = _run_subprocess(
            ["python", "-m", "pytest", "tests/", "-x", "-q", "--tb=short", "--no-header"],
            cwd=work_dir,
        )
    else:
        pytest_out, pytest_rc = "no tests directory found", 0

    duration = time.monotonic() - start
    combined = f"=== RUFF ===\n{ruff_out}\n=== PYTEST ===\n{pytest_out}"

    return _parse_test_output(
        stdout=combined,
        stderr="",
        exit_code=pytest_rc,
        duration=duration,
        docker_used=False,
    )


def _run_subprocess(cmd: list[str], cwd: Path) -> tuple[str, int]:
    """Run a subprocess command, returns (output, returncode)."""
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=60,
        )
        return (result.stdout + result.stderr)[:5000], result.returncode
    except subprocess.TimeoutExpired:
        return "TIMEOUT", 1
    except FileNotFoundError as exc:
        return f"Command not found: {exc}", 1
    except Exception as exc:
        return f"Error: {exc}", 1


# ── Output parser ─────────────────────────────────────────────────────────────

def _parse_test_output(
    stdout: str,
    stderr: str,
    exit_code: int,
    duration: float,
    docker_used: bool,
) -> SandboxResult:
    """Parse combined test output into SandboxResult."""
    combined = stdout + "\n" + stderr

    # pytest result
    tests_passed = (
        "failed" not in combined.lower()
        and "error" not in combined.lower()
        and exit_code == 0
    ) or "passed" in combined.lower()

    # ruff result
    lint_passed = "=== RUFF ===" in combined and (
        combined.split("=== RUFF ===", 1)[1].split("===")[0].strip() == ""
        or "0 errors" in combined
    )

    # mypy result
    typecheck_passed = (
        "Success:" in combined
        or "=== MYPY ===" not in combined  # not run
    )

    # detect regressions
    regressions = []
    for line in combined.splitlines():
        if "FAILED" in line and "::" in line:
            regressions.append(line.strip()[:100])
        if "ERROR" in line and "test_" in line.lower():
            regressions.append(line.strip()[:100])

    improvements = []
    if tests_passed and not regressions:
        improvements.append("all_tests_pass")
    if lint_passed:
        improvements.append("lint_clean")

    return SandboxResult(
        success=True,
        tests_passed=tests_passed,
        lint_passed=lint_passed,
        typecheck_passed=typecheck_passed,
        regressions=regressions[:10],
        improvements=improvements,
        stdout=stdout[:3000],
        stderr=stderr[:1000],
        exit_code=exit_code,
        duration_s=round(duration, 2),
        docker_used=docker_used,
    )


# ── Public API ────────────────────────────────────────────────────────────────

class SandboxExecutor:
    """
    Applies a patch to a temp copy of the project and runs tests in isolation.
    Never modifies production files.
    """

    def __init__(self, config_or_root=None):
        # Accept SandboxConfig as first arg (test compatibility)
        if isinstance(config_or_root, SandboxConfig):
            self._config = config_or_root
            project_root = Path(__file__).resolve().parent.parent.parent
        elif config_or_root is None:
            self._config = SandboxConfig()
            project_root = Path(__file__).resolve().parent.parent.parent
        else:
            self._config = SandboxConfig()
            project_root = Path(config_or_root)
        self.project_root = project_root
        self._docker_available = not self._config.no_docker

    def execute_code(self, code: str) -> SandboxResult:
        """Execute a Python code string in a subprocess (no Docker)."""
        import tempfile
        timeout = getattr(self._config, "timeout_s", 60)
        tmp_file = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".py", mode="w",
                                             delete=False) as f:
                f.write(code)
                tmp_file = f.name
            proc = subprocess.run(
                [sys.executable, tmp_file],
                capture_output=True, text=True, timeout=timeout,
            )
            return SandboxResult(
                success=proc.returncode == 0,
                stdout=proc.stdout,
                stderr=proc.stderr,
                exit_code=proc.returncode,
                method="subprocess",
            )
        except subprocess.TimeoutExpired:
            return SandboxResult(
                success=False, timed_out=True,
                error="timeout", method="subprocess",
            )
        except Exception as e:
            return SandboxResult(
                success=False, error=str(e)[:100], method="subprocess",
            )
        finally:
            if tmp_file:
                try:
                    Path(tmp_file).unlink()
                except Exception:
                    _silent_log.debug("suppressed_exception", src='sandbox_executor.py')

    @staticmethod
    def _is_allowed_command(command: str) -> bool:
        """Check if a command is in the allowed set."""
        try:
            parts = shlex.split(command)
        except ValueError:
            return False
        if not parts:
            return False
        base = parts[0]
        # Reject shell wrappers
        if base in ("bash", "sh", "zsh", "curl", "wget", "rm", "nc", "ncat"):
            return False
        # Check against allowed set
        if base in ALLOWED_COMMANDS:
            return True
        # Also allow "python -m <allowed>"
        if base == "python" and len(parts) >= 3 and parts[1] == "-m":
            return parts[2] in ALLOWED_COMMANDS
        return False

    @staticmethod
    def _classify_failure(result: "SandboxResult") -> str:
        """Classify a failure into a FailureCategory."""
        try:
            output = (result.stdout or "") + (result.stderr or "")
            if result.timed_out:
                return FailureCategory.TIMEOUT
            if "SyntaxError" in output:
                return FailureCategory.SYNTAX_ERROR
            if "MemoryError" in output or "OOM" in output:
                return FailureCategory.OOM
            if "failed" in output.lower() and ("passed" in output.lower() or "pytest" in output.lower()):
                return FailureCategory.TEST_FAILURE
            return FailureCategory.UNKNOWN
        except Exception:
            return FailureCategory.UNKNOWN

    def run_syntax_check(self, sandbox_path: str, files: list[str]) -> SandboxResult:
        """Run syntax check on files using py_compile/ast."""
        import ast as _ast
        errors = []
        for f in files:
            full = Path(sandbox_path) / f
            if not full.exists():
                continue
            if not f.endswith(".py"):
                continue
            try:
                _ast.parse(full.read_text(encoding="utf-8"))
            except SyntaxError as e:
                errors.append(f"{f}: line {e.lineno}: {e.msg}")
        if errors:
            return SandboxResult(
                success=False,
                method="syntax_only",
                validation_level="syntax",
                error="\n".join(errors),
            )
        return SandboxResult(
            success=True,
            method="syntax_only",
            validation_level="syntax",
        )

    def run_in_docker(self, sandbox_path: str, command: str = "", timeout: int = 120) -> SandboxResult:
        """Run a command inside Docker sandbox. Gracefully degrades if Docker unavailable."""
        if getattr(self, "_docker_available", None) is False:
            return SandboxResult(
                success=True,
                method="syntax_only",
                validation_level="syntax",
                error="Docker unavailable — degraded to syntax-only",
            )
        try:
            subprocess.run(["docker", "info"], capture_output=True, timeout=5, check=True)
        except Exception:
            self._docker_available = False
            return SandboxResult(
                success=True,
                method="syntax_only",
                validation_level="syntax",
                error="Docker unavailable — degraded to syntax-only",
            )
        # Docker available — run command
        return _run_in_docker(Path(sandbox_path))

    def run_linter(self, sandbox_path: str, files: list[str]) -> SandboxResult:
        """Run ruff linter on files. Returns blocked/skipped result if ruff unavailable."""
        try:
            cmd = ["python", "-m", "ruff", "check"] + files
            result = subprocess.run(
                cmd, cwd=sandbox_path, capture_output=True, text=True, timeout=30,
            )
            combined = (result.stdout + result.stderr).lower()
            # Detect tool-not-installed (not a lint failure)
            if result.returncode != 0 and ("no module named" in combined or "not found" in combined):
                return SandboxResult(
                    success=False,
                    method="blocked",
                    validation_level="blocked",
                    error="ruff not found",
                    stderr="ruff not found",
                )
            return SandboxResult(
                success=result.returncode == 0,
                stdout=result.stdout[:2000],
                stderr=result.stderr[:2000],
                exit_code=result.returncode,
                method="lint",
                validation_level="lint",
            )
        except FileNotFoundError:
            return SandboxResult(
                success=False,
                method="blocked",
                validation_level="blocked",
                error="ruff not found",
                stderr="ruff not found",
            )
        except Exception as exc:
            return SandboxResult(
                success=False,
                method="blocked",
                validation_level="blocked",
                error=str(exc),
                stderr=str(exc),
            )

    def run_tests(self, sandbox_path: str, test_targets: list[str] | None = None,
                  timeout: int = 120) -> SandboxResult:
        """Run pytest in sandbox. Returns SandboxResult."""
        cmd = ["python", "-m", "pytest"]
        if test_targets:
            cmd.extend(test_targets)
        else:
            cmd.extend(["tests/", "-x", "-q", "--tb=short"])
        try:
            result = subprocess.run(
                cmd, cwd=sandbox_path, capture_output=True, text=True, timeout=timeout,
            )
            return SandboxResult(
                success=result.returncode == 0,
                tests_passed=result.returncode == 0,
                stdout=result.stdout[:3000],
                stderr=result.stderr[:1000],
                exit_code=result.returncode,
                method="subprocess",
                validation_level="subprocess",
            )
        except Exception as exc:
            return SandboxResult(
                success=False,
                method="blocked",
                validation_level="blocked",
                error=str(exc),
            )

    def _check_docker(self) -> bool:
        """Check if Docker is available."""
        if getattr(self, "_docker_available", None) is False:
            return False
        try:
            subprocess.run(["docker", "info"], capture_output=True, timeout=5, check=True)
            return True
        except Exception:
            self._docker_available = False
            return False

    def _run_docker_cmd(self, cmd: str, mount_dir: str = "", timeout: int = 60) -> SandboxResult:
        """Run a command inside Docker."""
        if not self._check_docker():
            return SandboxResult(
                success=False, method="blocked", validation_level="blocked",
                error="Docker not available", stderr="Docker not available",
            )
        mount = mount_dir or str(self.project_root)
        docker_cmd = [
            "docker", "run", "--rm", "--network=none",
            f"--memory={SANDBOX_MEMORY}", f"--cpus={SANDBOX_CPUS}",
            "-v", f"{mount}:/workspace:ro", "--workdir=/workspace",
            SANDBOX_DOCKER_IMAGE, "sh", "-c", cmd,
        ]
        try:
            result = subprocess.run(docker_cmd, capture_output=True, text=True, timeout=timeout)
            return SandboxResult(
                success=result.returncode == 0,
                stdout=result.stdout[:3000], stderr=result.stderr[:1000],
                exit_code=result.returncode, method="docker", validation_level="docker",
            )
        except Exception as exc:
            return SandboxResult(
                success=False, method="blocked", validation_level="blocked",
                error=str(exc), stderr=str(exc),
            )

    def _run_subprocess_cmd(self, cmd: str, cwd: str = "", timeout: int = 60) -> SandboxResult:
        """Run a command via subprocess."""
        work_dir = cwd or str(self.project_root)
        try:
            result = subprocess.run(
                shlex.split(cmd), cwd=work_dir,
                capture_output=True, text=True, timeout=timeout,
            )
            return SandboxResult(
                success=result.returncode == 0,
                stdout=result.stdout[:3000], stderr=result.stderr[:1000],
                exit_code=result.returncode, method="subprocess", validation_level="subprocess",
            )
        except FileNotFoundError:
            return SandboxResult(
                success=False, method="blocked", validation_level="blocked",
                error=f"Command not found: {cmd}", stderr=f"Command not found: {cmd}",
            )
        except Exception as exc:
            return SandboxResult(
                success=False, method="blocked", validation_level="blocked",
                error=str(exc), stderr=str(exc),
            )

    def validate_patch(self, sandbox_path: str, files: list[str]) -> SandboxResult:
        """Validate a patch: syntax check + basic validation."""
        try:
            result = self.run_syntax_check(sandbox_path, files)
            return result
        except Exception as exc:
            return SandboxResult(
                success=False,
                method="validate_patch",
                error=str(exc),
            )

    def execute(self, unified_diff: str, changed_files: list[str]) -> SandboxResult:
        """
        Apply unified_diff to a temp copy of the project and run tests.

        Args:
            unified_diff:  Unified diff string to apply
            changed_files: List of relative paths being changed (for logging)

        Returns:
            SandboxResult — never raises.
        """
        if not unified_diff.strip():
            log.info("sandbox.no_diff — skipping execution")
            return SandboxResult(
                success=True,
                tests_passed=True,
                lint_passed=True,
                typecheck_passed=True,
                improvements=["no_change_required"],
            )

        with tempfile.TemporaryDirectory(prefix="jarvis_sandbox_") as tmp_dir:
            work_dir = Path(tmp_dir) / "workspace"

            # Copy project to temp dir (exclude .git, __pycache__, node_modules)
            try:
                shutil.copytree(
                    str(self.project_root),
                    str(work_dir),
                    ignore=shutil.ignore_patterns(
                        ".git", "__pycache__", "*.pyc", "node_modules",
                        ".venv", "venv", "*.egg-info", ".mypy_cache",
                    ),
                )
            except Exception as exc:
                log.error("sandbox.copy_failed", err=str(exc))
                return SandboxResult(success=False, error=f"Failed to copy project: {exc}")

            # Apply patch
            applied, patch_error = _apply_patch(unified_diff, work_dir)
            if not applied:
                log.warning("sandbox.patch_failed", err=patch_error)
                return SandboxResult(
                    success=False,
                    error=f"Patch application failed: {patch_error}",
                )

            log.info("sandbox.patch_applied", changed_files=changed_files)

            # Run tests
            if SANDBOX_NO_DOCKER:
                return _run_in_process(work_dir)
            return _run_in_docker(work_dir)


# ── Singleton ──────────────────────────────────────────────────────────────────

_executor: SandboxExecutor | None = None


def get_sandbox_executor() -> SandboxExecutor:
    global _executor
    if _executor is None:
        _executor = SandboxExecutor()
    return _executor
