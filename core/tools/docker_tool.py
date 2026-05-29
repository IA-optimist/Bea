"""docker_tool — inspection et gestion des containers Docker."""
from __future__ import annotations
import subprocess  # nosec B404
import logging

logger = logging.getLogger("jarvis.docker_tool")

ALLOWED_CONTAINERS = ["jarvis_core", "jarvis_qdrant", "jarvis_redis"]


def _ok(output: str, logs: list = None, risk_level: str = "low") -> dict:
    return {
        "ok": True, "status": "ok",
        "output": output, "result": output,
        "error": None, "logs": logs or [], "risk_level": risk_level,
    }


def _err(error: str, logs: list = None, risk_level: str = "low") -> dict:
    return {
        "ok": False, "status": "error",
        "output": "", "result": "",
        "error": error, "logs": logs or [], "risk_level": risk_level,
    }


def _run(args: list[str], timeout: int = 10, risk_level: str = "low") -> dict:
    logs = [f"cmd={args}"]
    try:
        proc = subprocess.run(  # nosec B603 B607
            args, capture_output=True, text=True, timeout=timeout
        )
        out = proc.stdout[:3000]
        err = proc.stderr[:500]
        logs.append(f"rc={proc.returncode}")
        if proc.returncode != 0:
            return _err(f"rc={proc.returncode} stderr={err}", logs=logs, risk_level=risk_level)
        return _ok(out or f"(empty) stderr={err}", logs=logs, risk_level=risk_level)
    except subprocess.TimeoutExpired:
        return _err("timeout_exceeded", logs=logs, risk_level=risk_level)
    except FileNotFoundError:
        return _err("docker_not_found: docker CLI not available in container", logs=logs, risk_level=risk_level)
    except Exception as e:
        return _err(str(e), logs=logs, risk_level=risk_level)


def docker_ps() -> dict:
    try:
        return _run(["docker", "ps", "--format", "{{json .}}"])
    except Exception as e:
        return _err(str(e))


def docker_logs(container: str, tail: int = 50) -> dict:
    try:
        return _run(["docker", "logs", "--tail", str(tail), container])
    except Exception as e:
        return _err(str(e))


def docker_restart(container: str) -> dict:
    try:
        if container not in ALLOWED_CONTAINERS:
            return _err(f"blocked_container: {container} not in allowed list", risk_level="medium")
        result = _run(["docker", "restart", container], risk_level="medium")
        if result["ok"]:
            healthy = docker_healthcheck(container)
            if not healthy:
                logger.warning(f"UNHEALTHY after restart: container={container}")
                result["logs"].append(f"WARNING: {container} UNHEALTHY after restart")
        return result
    except Exception as e:
        return _err(str(e))


def docker_inspect(container: str) -> dict:
    try:
        result = _run(["docker", "inspect", "--format",
                       "{{json .State}} ports={{json .NetworkSettings.Ports}}",
                       container])
        return result
    except Exception as e:
        return _err(str(e))


def docker_compose_build(project_dir: str) -> dict:
    try:
        return _run(["docker", "compose", "build"], timeout=120, risk_level="medium")
    except Exception as e:
        return _err(str(e), risk_level="medium")


def docker_compose_up(project_dir: str) -> dict:
    try:
        return _run(["docker", "compose", "up", "-d"], timeout=60, risk_level="medium")
    except Exception as e:
        return _err(str(e), risk_level="medium")


def docker_compose_down(project_dir: str) -> dict:
    try:
        return _run(["docker", "compose", "down"], timeout=60, risk_level="high")
    except Exception as e:
        return _err(str(e), risk_level="high")


def docker_healthcheck(container: str) -> bool:
    """Vérifie qu'un container est Up et healthy. Retourne bool."""
    try:
        proc = subprocess.run(  # nosec B603 B607
            ["docker", "inspect", "--format",
             "{{.State.Status}} {{.State.Health.Status}}", container],
            capture_output=True, text=True, timeout=5
        )
        if proc.returncode != 0:
            return False
        output = proc.stdout.strip().lower()
        # Accept "running" with healthy or no healthcheck ("running ")
        if "running" not in output:
            return False
        if "unhealthy" in output:
            return False
        return True
    except Exception:
        return False
