"""github_tool — opérations git via subprocess."""
from __future__ import annotations
import os
import subprocess  # nosec B404
from typing import Any

_BEA_ROOT = os.environ.get("BEA_ROOT", "/opt/beamax")
_ALLOWED_ROOTS = (_BEA_ROOT, "/tmp")  # nosec B108 — path-prefix allowlist, not a write target.


def _ok(output: str, logs: list[str] | None = None, risk_level: str = "low") -> dict[str, Any]:
    return {
        "ok": True, "status": "ok",
        "output": output, "result": output,
        "error": None, "logs": logs or [], "risk_level": risk_level,
    }


def _err(error: str, logs: list[str] | None = None, risk_level: str = "low") -> dict[str, Any]:
    return {
        "ok": False, "status": "error",
        "output": "", "result": "",
        "error": error, "logs": logs or [], "risk_level": risk_level,
    }


def _check_path(repo_path: str) -> str | None:
    for root in _ALLOWED_ROOTS:
        if repo_path.startswith(root):
            return None
    return f"blocked_path: {repo_path} not under allowed roots"


def _run(args: list[str], repo_path: str, timeout: int = 15, risk_level: str = "low") -> dict[str, Any]:
    logs = [f"cmd={args}"]
    try:
        proc = subprocess.run(  # nosec B603 B607
            args, capture_output=True, text=True, timeout=timeout, cwd=repo_path
        )
        out = proc.stdout[:2000]
        err = proc.stderr[:500]
        logs.append(f"rc={proc.returncode}")
        if proc.returncode != 0:
            return _err(f"rc={proc.returncode} stderr={err}", logs=logs, risk_level=risk_level)
        return _ok(out or f"(empty stdout) stderr={err}", logs=logs, risk_level=risk_level)
    except subprocess.TimeoutExpired:
        return _err("timeout_exceeded", logs=logs, risk_level=risk_level)
    except FileNotFoundError:
        return _err("git_not_found: git CLI not available in container", logs=logs, risk_level=risk_level)
    except Exception as e:
        return _err(str(e), logs=logs, risk_level=risk_level)


def git_status(repo_path: str) -> dict[str, Any]:
    try:
        blocked = _check_path(repo_path)
        if blocked:
            return _err(blocked)
        return _run(["git", "status", "--short"], repo_path)
    except Exception as e:
        return _err(str(e))


def git_diff(repo_path: str, file: str | None = None) -> dict[str, Any]:
    try:
        blocked = _check_path(repo_path)
        if blocked:
            return _err(blocked)
        cmd = ["git", "diff"]
        if file:
            cmd.append(file)
        return _run(cmd, repo_path)
    except Exception as e:
        return _err(str(e))


def git_log(repo_path: str, n: int = 5) -> dict[str, Any]:
    try:
        blocked = _check_path(repo_path)
        if blocked:
            return _err(blocked)
        return _run(["git", "log", "--oneline", f"-{n}"], repo_path)
    except Exception as e:
        return _err(str(e))


def git_branch(repo_path: str) -> dict[str, Any]:
    try:
        blocked = _check_path(repo_path)
        if blocked:
            return _err(blocked)
        return _run(["git", "branch", "--show-current"], repo_path)
    except Exception as e:
        return _err(str(e))


def git_pull(repo_path: str) -> dict[str, Any]:
    try:
        blocked = _check_path(repo_path)
        if blocked:
            return _err(blocked)
        return _run(["git", "pull", "origin", "master"], repo_path, timeout=30, risk_level="medium")
    except Exception as e:
        return _err(str(e))


def git_branch_create(repo_path: str, branch_name: str) -> dict[str, Any]:
    try:
        blocked = _check_path(repo_path)
        if blocked:
            return _err(blocked)
        return _run(["git", "checkout", "-b", branch_name], repo_path, risk_level="low")
    except Exception as e:
        return _err(str(e))


def git_checkout(repo_path: str, branch: str) -> dict[str, Any]:
    try:
        blocked = _check_path(repo_path)
        if blocked:
            return _err(blocked)
        return _run(["git", "checkout", branch], repo_path, risk_level="low")
    except Exception as e:
        return _err(str(e))


def git_commit(repo_path: str, message: str, files: list[str], approval_mode: str = "SUPERVISED") -> dict[str, Any]:
    try:
        if approval_mode != "auto":
            return _err("blocked_by_policy: git_commit requires approval_mode=auto", risk_level="high")
        blocked = _check_path(repo_path)
        if blocked:
            return _err(blocked, risk_level="high")
        add_result = _run(["git", "add"] + list(files), repo_path, timeout=15, risk_level="high")
        if not add_result["ok"]:
            return add_result
        return _run(["git", "commit", "-m", message], repo_path, timeout=15, risk_level="high")
    except Exception as e:
        return _err(str(e), risk_level="high")


def git_push(repo_path: str, branch: str = "master", approval_mode: str = "SUPERVISED") -> dict[str, Any]:
    try:
        if approval_mode != "auto":
            return _err("blocked_by_policy: git_push requires approval_mode=auto", risk_level="high")
        blocked = _check_path(repo_path)
        if blocked:
            return _err(blocked, risk_level="high")
        return _run(["git", "push", "origin", branch], repo_path, timeout=30, risk_level="high")
    except Exception as e:
        return _err(str(e), risk_level="high")
