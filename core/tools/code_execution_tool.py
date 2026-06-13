"""code_execution_tool — exécute du code Python dans le sandbox durci.

Remplace l'ancienne `execute_python_snippet` (subprocess host + denylist
bypassable). Fait tourner le code dans `executor.desktop_env` :

- `DockerSandbox` : `network_mode=none`, `read_only`, `cap_drop=["ALL"]`,
  `no-new-privileges`, mem/pids limités, workspace cloné en copy-on-write ;
- `LocalFallbackSandbox` si Docker indisponible (opt-in `BEA_ALLOW_LOCAL_SANDBOX=1`).

Câblé dans `core/tool_executor` via le bloc _EXEC_CODE_AVAILABLE.
"""
from __future__ import annotations

import logging
import os
import threading
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 30
_MAX_TIMEOUT = 120
_MAX_OUTPUT = 10_000


def _ok(output: str, risk_level: str = "medium") -> dict:
    return {
        "ok": True, "status": "ok",
        "output": output, "result": output,
        "error": None, "logs": [], "risk_level": risk_level,
    }


def _err(error: str, risk_level: str = "medium") -> dict:
    return {
        "ok": False, "status": "error",
        "output": "", "result": "",
        "error": error, "logs": [], "risk_level": risk_level,
    }


def _get_sandbox(workspace_path: str):
    """Sandbox durci : Docker si disponible, sinon fallback local (opt-in)."""
    from executor.desktop_env.sandbox import DockerSandbox, LocalFallbackSandbox
    docker_sb = DockerSandbox(workspace_path)
    if docker_sb.is_available():
        return docker_sb
    return LocalFallbackSandbox(workspace_path)


def execute_code(
    code: str,
    timeout: int = _DEFAULT_TIMEOUT,
    workspace_path: str | None = None,
) -> dict:
    """Exécute `code` Python dans le sandbox isolé ; renvoie stdout ou l'erreur.

    Le code tourne dans un conteneur durci (réseau coupé, FS lecture seule hors
    /tmp, capacités retirées). `timeout` est borné à [1, 120] s. Renvoie le dict
    d'outil standard (`ok/status/output/result/error/logs/risk_level`).
    """
    if not isinstance(code, str) or not code.strip():
        return _err("empty_code")
    try:
        timeout = min(max(int(timeout), 1), _MAX_TIMEOUT)
    except (TypeError, ValueError):
        timeout = _DEFAULT_TIMEOUT

    workspace_path = workspace_path or os.getcwd()
    script_name = f".bea_exec_{uuid.uuid4().hex[:8]}.py"
    script_path = Path(workspace_path) / script_name

    sandbox = None
    holder: dict = {}
    try:
        script_path.write_text(code, encoding="utf-8")
        sandbox = _get_sandbox(workspace_path)
        sandbox.start()

        def _run() -> None:
            holder["res"] = sandbox.execute(f"python {script_name}")

        worker = threading.Thread(target=_run, daemon=True)
        worker.start()
        worker.join(timeout=timeout)
        if worker.is_alive():
            return _err(f"timeout_exceeded ({timeout}s)")

        exit_code, output = holder.get("res", (-1, "no_output"))
        output = (output or "")[:_MAX_OUTPUT]
        if exit_code == 0:
            return _ok(output)
        return _err(f"exit_code={exit_code}: {output}")
    except Exception as e:  # fail-closed : toute panne sandbox/IO -> erreur outil
        return _err(str(e)[:300])
    finally:
        try:
            if script_path.exists():
                script_path.unlink()
        except OSError:
            logger.debug("exec_script_cleanup_failed", exc_info=True)
        if sandbox is not None:
            try:
                sandbox.stop()
            except Exception:
                logger.debug("sandbox_stop_failed", exc_info=True)
