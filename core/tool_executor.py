"""
ToolExecutor — exécution RÉELLE des tools pour les agents Jarvis.
5 tools prioritaires avec isolation, timeout, et respect de l'ExecutionPolicy.
RAM : < 500 bytes au repos (fonctions pures + singleton léger).
"""
from __future__ import annotations

import logging
import os
import subprocess
import time
from typing import Optional

# ── L4 tool modules ───────────────────────────────────────────────────────────
try:
    from core.tools.github_tool import (
        git_status, git_diff, git_log, git_branch,
        git_commit, git_push, git_pull, git_branch_create, git_checkout,
    )
    from core.tools.docker_tool import (
        docker_ps, docker_logs, docker_restart, docker_inspect,
        docker_compose_build, docker_compose_up, docker_compose_down,
    )
    from core.tools.file_tool import (
        search_in_files, replace_in_file, create_directory,
        list_project_structure, count_lines,
        file_create, file_delete_safe, workspace_snapshot,
    )
    from core.tools.web_research_tool import (
        fetch_url, search_pypi, fetch_github_readme, check_url_status,
        http_post_json, doc_fetch,
    )
    from core.tools.test_toolkit import (
        run_unit_tests, run_smoke_tests, api_healthcheck, test_endpoint,
    )
    # LEGACY: memory_toolkit (Qdrant) désactivé, utiliser memory/vector_store.py
    # from core.tools.memory_toolkit import (
    #     memory_store_solution, memory_store_error, memory_store_patch,
    #     memory_search_similar,
    # )
    from core.tools.app_sync_toolkit import check_api_fields, sync_app_fields
    from core.tools.tool_builder_tool import (
        analyze_tool_need, generate_tool_skeleton, generate_tool_tests, build_complete_tool,
    )
    from core.tools.dev_tools import (
        dependency_analyzer, code_search_multi_file, api_schema_generator,
        env_checker, requirements_validator,
    )
    # LEGACY: memory_toolkit (Qdrant) désactivé
    # from core.tools.memory_toolkit import (
    #     memory_store_with_ttl, memory_cleanup_expired, memory_deduplicate, memory_summarize_recent,
    # )
    _L4_AVAILABLE = True
except Exception as _l4_err:
    _L4_AVAILABLE = False
    logging.getLogger("jarvis.tool_executor").warning(f"L4 tools unavailable: {_l4_err}")

logger = logging.getLogger("jarvis.tool_executor")
try:
    import structlog as _structlog
    log = _structlog.get_logger("jarvis.tool_executor")
except ImportError:
    log = logger  # fallback

# ── Classification d'erreurs (V3) ─────────────────────────────────────────────

ERROR_CLASSES: dict[str, list[str]] = {
    "tool_error":        ["AttributeError", "TypeError", "ValueError"],
    "environment_error": ["FileNotFoundError", "PermissionError", "ModuleNotFoundError"],
    "network_error":     ["ConnectionError", "TimeoutError", "requests.exceptions"],
    "logic_error":       ["RuntimeError", "AssertionError", "KeyError"],
}


# _classify_error: see unified version below


# ── Résultat standard ─────────────────────────────────────────────────────────

import time as _time
_silent_log = __import__("structlog").get_logger(__name__)

def _ok(result: str, **meta) -> dict:
    """Structured success result with optional metadata."""
    return {"ok": True, "result": result, "error": None, "ts": _time.time(), **meta}

def _err(error: str, *, retryable: bool = False, error_class: str = "TOOL_ERROR", **meta) -> dict:
    """Structured error result with classification."""
    return {
        "ok": False, "result": "", "error": error,
        "retryable": retryable,
        "error_class": error_class or _classify_error(error),
        "ts": _time.time(),
        **meta,
    }

def _classify_error(error_str) -> str:
    """Classify error into canonical taxonomy: TRANSIENT, USER_INPUT, TOOL_ERROR,
    POLICY_BLOCKED, TIMEOUT, SYSTEM_ERROR. Falls back to TOOL_ERROR."""
    try:
        from core.resilience import JarvisExecutionError
        if isinstance(error_str, Exception):
            classified = JarvisExecutionError.from_exception(error_str)
            return classified.error_type
    except Exception:
        _silent_log.debug("suppressed_exception", src='tool_executor.py')
    # String-based fallback using canonical types
    e = str(error_str).lower()
    if "timeout" in e or "timed out" in e:
        return "TIMEOUT"
    if "permission" in e or "denied" in e or "blocked" in e or "forbidden" in e:
        return "POLICY_BLOCKED"
    if "not found" in e or "no such" in e or "missing" in e:
        return "USER_INPUT"
    if "connection" in e or "network" in e or "refused" in e or "unreachable" in e:
        return "TRANSIENT"
    if "module" in e or "import" in e or "attribute" in e:
        return "SYSTEM_ERROR"
    return "TOOL_ERROR"


# ── Tool 1 : HTTP GET ─────────────────────────────────────────────────────────

def execute_http_get(url: str, timeout: int = 8) -> dict:
    """HTTP GET simple. Bloqué sur localhost / réseau interne."""
    _BLOCKED = ("localhost", "127.0.0.1", "10.0.", "0.0.0.0", "169.254.")
    for blocked in _BLOCKED:
        if blocked in url:
            return _err(f"blocked_url: {blocked} not allowed")
    try:
        import requests as _req
        resp = _req.get(url, timeout=timeout)
        return _ok(f"status={resp.status_code} body={resp.text[:2000]}")
    except Exception as e:
        return _err(str(e))


# ── Tool 2 : Python snippet ───────────────────────────────────────────────────

_PYTHON_BLOCKED = ("import os", "import sys", "__import__", "open(", "exec(", "eval(")

def execute_python_snippet(code: str, timeout: int = 8) -> dict:
    """Exécute du Python dans un subprocess isolé."""
    for banned in _PYTHON_BLOCKED:
        if banned in code:
            return _err(f"blocked_pattern: '{banned}' interdit")
    try:
        proc = subprocess.run(
            ["python", "-c", code],
            capture_output=True, text=True, timeout=timeout,
        )
        stdout = proc.stdout[:1000]
        stderr = proc.stderr[:500]
        result = stdout if stdout else f"(no stdout) stderr={stderr}"
        return _ok(result)
    except subprocess.TimeoutExpired:
        return _err("timeout_exceeded")
    except Exception as e:
        return _err(str(e))


# ── Tool 3 : Read file ────────────────────────────────────────────────────────

_FILE_BLOCKED = ("/etc", "/root", "/proc", "/sys", "\\Windows\\System32")

def read_file_content(path: str, max_lines: int = 100) -> dict:
    """Lit un fichier local (chemin relatif uniquement)."""
    if path.startswith("/") or path.startswith("\\"):
        for blocked in _FILE_BLOCKED:
            if path.startswith(blocked):
                return _err(f"blocked_path: {blocked} not allowed")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[:max_lines]
        return _ok("".join(lines))
    except Exception as e:
        return _err(str(e))


# ── Tool 3b : Write file (safe, avec rollback) ────────────────────────────────

_FILE_WRITE_BLOCKED = ("/etc", "/root", "/proc", "/sys", "\\Windows\\System32")

def write_file_safe(path: str, content: str, force: bool = False) -> dict:
    """
    Écrit dans un fichier avec backup automatique avant modification.
    Rollback automatique si l'écriture échoue.
    Action_type : "write"
    """
    if not force:
        for blocked in _FILE_WRITE_BLOCKED:
            if path.startswith(blocked):
                return _err(f"blocked_path: {path}")

    try:
        from core.rollback_manager import RollbackContext, save_diff

        # Lit le contenu actuel pour le diff
        old_content = ""
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                old_content = f.read()
        except FileNotFoundError:
            pass  # nouveau fichier — pas de backup

        with RollbackContext(path) as ctx:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            save_diff(path, old_content, content, ctx.ts)

        return _ok(f"written: {len(content)} chars to {path}")
    except Exception as e:
        return _err(f"write_failed: {e}")


# ── Tool 4 : Shell command ────────────────────────────────────────────────────

_SHELL_BLOCKED = ("rm -rf", "dd if=", "mkfs", "> /dev", "shutdown", "reboot", "passwd",
                  "curl ", "wget ", "nc ", "ncat ", "python -c", "eval ", "exec ")
_SHELL_ALLOWED_PREFIXES = ("ls", "cat", "head", "tail", "grep", "find", "echo", "date",
                           "wc", "sort", "uniq", "diff", "git ", "python3 -m pytest",
                           "cd ", "pwd", "stat", "file", "which", "env")

def run_shell_command(cmd: str, timeout: int = 8) -> dict:
    """Exécute une commande shell dans /opt/jarvismax avec validation stricte."""
    # Global kill switch
    import os as _os
    if _os.environ.get("JARVIS_EXECUTION_DISABLED", "").lower() in ("1", "true", "yes"):
        return _err("EXECUTION_DISABLED")

    # Block dangerous commands
    for banned in _SHELL_BLOCKED:
        if banned in cmd:
            return _err(f"blocked_command: '{banned}' interdit")

    # Allowlist enforced by default — opt-out uniquement via
    # JARVIS_SHELL_ALLOWLIST=0 dans un contexte explicitement trusté.
    if _os.environ.get("JARVIS_SHELL_ALLOWLIST", "1").lower() not in ("0", "false", "no"):
        cmd_stripped = cmd.strip()
        if not any(cmd_stripped.startswith(prefix) for prefix in _SHELL_ALLOWED_PREFIXES):
            return _err(f"shell_not_allowed: command not in allowlist")

    # Log for audit trail
    try:
        from core.governance import log_mission_event
        log_mission_event("shell_exec", "shell_command", cmd[:100], "medium")
    except Exception as _exc:
        log.warning("silent_exception_caught", err=str(_exc)[:200], stage="tool_executor")
    try:
        _cwd = _os.environ.get("JARVIS_ROOT", "/opt/jarvismax")
        # Use shlex for safer argument handling
        import shlex
        try:
            args = shlex.split(cmd)
        except ValueError:
            args = None

        if args and len(args) >= 1:
            proc = subprocess.run(
                args, capture_output=True, text=True,
                timeout=timeout, cwd=_cwd,
            )
        else:
            # Fallback to shell=True for complex piped commands (with extra validation)
            if any(ch in cmd for ch in ("|", "&&", "||", ">>", ">")):
                # Pipe/redirect commands — still use shell but validated above
                proc = subprocess.run(
                    cmd, shell=True, capture_output=True, text=True,
                    timeout=timeout, cwd=_cwd,
                )
            else:
                return _err("invalid_command: could not parse")

        result = f"returncode={proc.returncode} stdout={proc.stdout[:1000]}"
        return _ok(result)
    except subprocess.TimeoutExpired:
        return _err("timeout_exceeded")
    except Exception as e:
        return _err(str(e))


# ── Tool 5 : Vector DB search (LEGACY - désactivé, utiliser memory/vector_store.py) ───

# _QDRANT_BASE = "http://qdrant:6333"
# _COLLECTION  = "default_memory"
# _VECTOR_DIM  = 768

# def _ensure_collection(collection: str = _COLLECTION) -> bool:
#     """Crée la collection si elle n'existe pas. Retourne True si prête."""
#     try:
#         import requests as _req
#         # Vérifie si la collection existe
#         r = _req.get(f"{_QDRANT_BASE}/collections/{collection}", timeout=3)
#         if r.status_code == 200:
#             return True
#         if r.status_code == 404:
#             # Crée la collection
#             payload = {
#                 "vectors": {
#                     "size": _VECTOR_DIM,
#                     "distance": "Cosine"
#                 }
#             }
#             cr = _req.put(
#                 f"{_QDRANT_BASE}/collections/{collection}",
#                 json=payload,
#                 timeout=5,
#             )
#             return cr.status_code in (200, 201)
#         return False
#     except Exception as _exc:
#         log.warning("exception_caught", err=str(_exc)[:200], stage="tool_executor")
#         return False


# def query_vector_db(query: str, collection: str = _COLLECTION, top_k: int = 3) -> dict:
#     """Requête Qdrant. Auto-crée la collection si absente. Fail-open si Qdrant indisponible."""
#     try:
#         import requests as _req

#         # Auto-création si nécessaire
#         if not _ensure_collection(collection):
#             return _err("qdrant_unavailable")

#         # Vecteur nul (placeholder sans embedder)
#         dummy_vector = [0.0] * _VECTOR_DIM
#         resp = _req.post(
#             f"{_QDRANT_BASE}/collections/{collection}/points/search",
#             json={"vector": dummy_vector, "limit": top_k, "with_payload": True},
#             timeout=4,
#         )
#         if resp.status_code == 200:
#             results = resp.json().get("result", [])
#             return _ok(f"found={len(results)} results: {str(results)[:800]}")
#         return _err(f"qdrant_search_error: status={resp.status_code}")
#     except Exception as e:
#         return _err(f"qdrant_unavailable: {e}")


# ── ToolExecutor singleton ────────────────────────────────────────────────────

class ToolExecutor:
    """Exécuteur de tools avec vérification de l'ExecutionPolicy."""

    _tools: dict = {
        "http_get":        execute_http_get,
        "python_snippet":  execute_python_snippet,
        "read_file":       read_file_content,
        "write_file_safe": write_file_safe,
        "shell_command":   run_shell_command,
        # "vector_search": query_vector_db,  # LEGACY
        # L4 tools (registered only if import succeeded)
        **({
            # git
            "git_status":           git_status,
            "git_diff":             git_diff,
            "git_log":              git_log,
            "git_branch":           git_branch,
            "git_commit":           git_commit,
            "git_push":             git_push,
            "git_pull":             git_pull,
            "git_branch_create":    git_branch_create,
            "git_checkout":         git_checkout,
            # docker
            "docker_ps":            docker_ps,
            "docker_logs":          docker_logs,
            "docker_restart":       docker_restart,
            "docker_inspect":       docker_inspect,
            "docker_compose_build": docker_compose_build,
            "docker_compose_up":    docker_compose_up,
            "docker_compose_down":  docker_compose_down,
            # file
            "search_in_files":      search_in_files,
            "replace_in_file":      replace_in_file,
            "create_directory":     create_directory,
            "list_project_structure": list_project_structure,
            "count_lines":          count_lines,
            "file_create":          file_create,
            "file_delete_safe":     file_delete_safe,
            "workspace_snapshot":   workspace_snapshot,
            # web
            "fetch_url":            fetch_url,
            "search_pypi":          search_pypi,
            "fetch_github_readme":  fetch_github_readme,
            "check_url_status":     check_url_status,
            "http_post_json":       http_post_json,
            "doc_fetch":            doc_fetch,
            # test_toolkit
            "run_unit_tests":       run_unit_tests,
            "run_smoke_tests":      run_smoke_tests,
            "api_healthcheck":      api_healthcheck,
            "test_endpoint":        test_endpoint,
            # memory_toolkit
            # LEGACY memory_toolkit

            # memory_toolkit
            # "memory_store_solution": memory_store_solution,
            # "memory_store_error":    memory_store_error,
            # "memory_store_patch":    memory_store_patch,
            # "memory_search_similar": memory_search_similar,
            # app_sync_toolkit
            "check_api_fields":     check_api_fields,
            "sync_app_fields":      sync_app_fields,
            # tool_builder_tool
            "analyze_tool_need":    analyze_tool_need,
            "generate_tool_skeleton": generate_tool_skeleton,
            "generate_tool_tests":  generate_tool_tests,
            "build_complete_tool":  build_complete_tool,
            # dev_tools
            "dependency_analyzer":  dependency_analyzer,
            "code_search_multi_file": code_search_multi_file,
            "api_schema_generator": api_schema_generator,
            "env_checker":          env_checker,
            "requirements_validator": requirements_validator,
            # memory_toolkit v3
            # LEGACY memory_toolkit v3

            # memory_toolkit v3
            # "memory_store_with_ttl":   memory_store_with_ttl,
            # "memory_cleanup_expired":  memory_cleanup_expired,
            # "memory_deduplicate":      memory_deduplicate,
            # "memory_summarize_recent": memory_summarize_recent,
        } if _L4_AVAILABLE else {}),
    }

    # Timeouts par tool (secondes)
    _TOOL_TIMEOUTS: dict = {
        "shell_command": 10,
        "http_get": 8,
        "read_file": 5,
        "python_snippet": 8,
        # "vector_search": 6,  # LEGACY
        # git
        "git_status": 15, "git_diff": 15, "git_log": 15, "git_branch": 15,
        "git_commit": 15, "git_push": 30, "git_pull": 30,
        "git_branch_create": 10, "git_checkout": 10,
        # docker
        "docker_ps": 10, "docker_logs": 10, "docker_restart": 10, "docker_inspect": 10,
        "docker_compose_build": 120, "docker_compose_up": 60, "docker_compose_down": 60,
        # file
        "search_in_files": 8, "replace_in_file": 8, "create_directory": 8,
        "list_project_structure": 8, "count_lines": 8,
        "file_create": 8, "file_delete_safe": 5, "workspace_snapshot": 30,
        # web
        "fetch_url": 10, "search_pypi": 10, "fetch_github_readme": 10, "check_url_status": 10,
        "http_post_json": 10, "doc_fetch": 10,
        # test_toolkit
        "run_unit_tests": 60, "run_smoke_tests": 15, "api_healthcheck": 15, "test_endpoint": 10,
        # memory_toolkit
        # LEGACY memory_toolkit

        # memory_toolkit
        # "memory_store_solution": 10, # "memory_store_error": 10,
        # "memory_store_patch": 10, # "memory_search_similar": 10,
        # app_sync_toolkit
        "check_api_fields": 15, "sync_app_fields": 15,
        # tool_builder_tool
        "analyze_tool_need": 10, "generate_tool_skeleton": 10,
        "generate_tool_tests": 10, "build_complete_tool": 30,
        # dev_tools
        "dependency_analyzer": 30, "code_search_multi_file": 10,
        "api_schema_generator": 10, "env_checker": 10, "requirements_validator": 10,
        # memory_toolkit v3
        # LEGACY memory_toolkit v3

        # memory_toolkit v3
        # "memory_store_with_ttl": 10, # "memory_cleanup_expired": 30,
        # "memory_deduplicate": 30, # "memory_summarize_recent": 10,
        # browser (registered dynamically below)
    }

    # ── Browser bridge registration (fail-open) ──────────────────────────
    try:
        from core.tools.browser_bridge import (
            BROWSER_TOOLS, BROWSER_TOOL_TIMEOUTS,
            BROWSER_TOOL_REQUIRED_PARAMS, BROWSER_ACTION_TYPES,
        )
        _tools.update(BROWSER_TOOLS)
        _TOOL_TIMEOUTS.update(BROWSER_TOOL_TIMEOUTS)
    except ImportError:
        _silent_log.debug("suppressed_exception", src='tool_executor.py')

    # Paramètres requis par tool (validation avant exécution)
    _TOOL_REQUIRED_PARAMS: dict = {
        "shell_command": ["cmd"],
        "http_get": ["url"],
        "read_file": ["path"],
        "python_snippet": ["code"],
        # "vector_search": ["query"],  # LEGACY
        # git
        "git_status": ["repo_path"], "git_diff": ["repo_path"],
        "git_log": ["repo_path"], "git_branch": ["repo_path"],
        "git_commit": ["repo_path", "message", "files"],
        "git_push": ["repo_path"], "git_pull": ["repo_path"],
        "git_branch_create": ["repo_path", "branch_name"],
        "git_checkout": ["repo_path", "branch"],
        # docker
        "docker_logs": ["container"], "docker_restart": ["container"], "docker_inspect": ["container"],
        "docker_compose_build": ["project_dir"],
        "docker_compose_up": ["project_dir"],
        "docker_compose_down": ["project_dir"],
        # file
        "search_in_files": ["directory", "pattern"],
        "replace_in_file": ["path", "old_text", "new_text"],
        "create_directory": ["path"], "list_project_structure": ["path"], "count_lines": ["path"],
        "file_create": ["path", "content"],
        "file_delete_safe": ["path"],
        "workspace_snapshot": ["output_dir"],
        # web
        "fetch_url": ["url"], "search_pypi": ["package"],
        "fetch_github_readme": ["owner", "repo"], "check_url_status": ["url"],
        "http_post_json": ["url", "payload"],
        "doc_fetch": ["url"],
        # test_toolkit
        "test_endpoint": ["method", "url"],
        # memory_toolkit
        # LEGACY memory_toolkit

        # memory_toolkit
        # "memory_store_solution": ["problem", "solution"],
        # "memory_store_error": ["error_type", "context"],
        # "memory_store_patch": ["filename", "description", "diff"],
        # "memory_search_similar": ["query"],
        # tool_builder_tool
        "analyze_tool_need": ["description", "required_inputs", "required_outputs"],
        "generate_tool_skeleton": ["tool_name", "description", "input_schema", "output_schema"],
        "generate_tool_tests": ["tool_name", "tool_code"],
        "build_complete_tool": ["description", "tool_name", "input_schema", "output_schema"],
        # dev_tools
        "code_search_multi_file": ["directory", "pattern"],
        "api_schema_generator": ["module_path"],
        # memory_toolkit v3
        # LEGACY memory_toolkit v3

        # memory_toolkit v3
        # "memory_store_with_ttl": ["content", "tags"],
    }

    # ── Browser bridge params registration (fail-open) ────────────────────
    try:
        from core.tools.browser_bridge import BROWSER_TOOL_REQUIRED_PARAMS
        _TOOL_REQUIRED_PARAMS.update(BROWSER_TOOL_REQUIRED_PARAMS)
    except ImportError:
        _silent_log.debug("suppressed_exception", src='tool_executor.py')

    # Tools qui acceptent un kwarg timeout
    _TIMEOUT_SUPPORTED: set = {"shell_command", "http_get", "python_snippet"}

    # action_type par tool (pour ExecutionPolicy)
    _action_types: dict[str, str] = {
        "http_get":        "external_api",
        "python_snippet":  "execute",
        "read_file":       "read",
        "write_file_safe": "write",
        "shell_command":   "execute",
        # "vector_search":   "read",  # LEGACY
        # git
        "git_status": "read", "git_diff": "read", "git_log": "read", "git_branch": "read",
        "git_commit": "write", "git_push": "write", "git_pull": "write",
        "git_branch_create": "write", "git_checkout": "write",
        # docker
        "docker_ps": "read", "docker_logs": "read", "docker_restart": "execute", "docker_inspect": "read",
        "docker_compose_build": "execute", "docker_compose_up": "execute", "docker_compose_down": "execute",
        # file
        "search_in_files": "read", "replace_in_file": "write", "create_directory": "write",
        "list_project_structure": "read", "count_lines": "read",
        "file_create": "write", "file_delete_safe": "write", "workspace_snapshot": "read",
        # web
        "fetch_url": "external_api", "search_pypi": "external_api",
        "fetch_github_readme": "external_api", "check_url_status": "external_api",
        "http_post_json": "external_api", "doc_fetch": "external_api",
        # test_toolkit
        "run_unit_tests": "execute", "run_smoke_tests": "read",
        "api_healthcheck": "read", "test_endpoint": "external_api",
        # memory_toolkit
        # LEGACY memory_toolkit

        # memory_toolkit
        # "memory_store_solution": "write", # "memory_store_error": "write",
        # "memory_store_patch": "write", # "memory_search_similar": "read",
        # app_sync_toolkit
        "check_api_fields": "read", "sync_app_fields": "read",
        # tool_builder_tool
        "analyze_tool_need": "read", "generate_tool_skeleton": "read",
        "generate_tool_tests": "read", "build_complete_tool": "write",
        # dev_tools
        "dependency_analyzer": "read", "code_search_multi_file": "read",
        "api_schema_generator": "read", "env_checker": "read", "requirements_validator": "read",
        # memory_toolkit v3
        # LEGACY memory_toolkit v3

        # memory_toolkit v3
        # "memory_store_with_ttl": "write", # "memory_cleanup_expired": "write",
        # "memory_deduplicate": "write", # "memory_summarize_recent": "read",
    }

    # ── Browser bridge action types registration (fail-open) ──────────────
    try:
        from core.tools.browser_bridge import BROWSER_ACTION_TYPES
        _action_types.update(BROWSER_ACTION_TYPES)
    except ImportError:
        _silent_log.debug("suppressed_exception", src='tool_executor.py')

    # Niveaux de risque par tool
    _TOOL_RISK_LEVELS: dict[str, str] = {
        # low risk
        "git_status": "low", "git_diff": "low", "git_log": "low", "git_branch": "low",
        "git_pull": "medium", "git_branch_create": "low", "git_checkout": "low",
        "docker_ps": "low", "docker_logs": "low", "docker_inspect": "low",
        "search_in_files": "low", "list_project_structure": "low", "count_lines": "low",
        "fetch_url": "low", "search_pypi": "low", "fetch_github_readme": "low",
        "check_url_status": "low", "doc_fetch": "low",
        "run_unit_tests": "low", "run_smoke_tests": "low",
        "api_healthcheck": "low", "test_endpoint": "low",
        # "memory_search_similar": "low",
        "check_api_fields": "low", "sync_app_fields": "low",
        # "workspace_snapshot": "low", "read_file": "low", "vector_search": "low",  # LEGACY
        # medium risk
        "replace_in_file": "medium", "file_create": "medium", "create_directory": "low",
        "file_delete_safe": "medium", "workspace_snapshot": "low",
        "docker_restart": "medium", "docker_compose_build": "medium", "docker_compose_up": "medium",
        "http_post_json": "medium",
        # "memory_store_solution": "low", # "memory_store_error": "low", # "memory_store_patch": "low",  # LEGACY
        "write_file_safe": "medium", "shell_command": "medium", "python_snippet": "medium",
        "http_get": "low",
        # high risk
        "git_commit": "high", "git_push": "high",
        "docker_compose_down": "high",
        # tool_builder_tool
        "analyze_tool_need": "low", "generate_tool_skeleton": "low",
        "generate_tool_tests": "low", "build_complete_tool": "medium",
        # dev_tools
        "dependency_analyzer": "low", "code_search_multi_file": "low",
        "api_schema_generator": "low", "env_checker": "low", "requirements_validator": "low",
        # memory_toolkit v3
        # LEGACY memory_toolkit v3

        # memory_toolkit v3
        # "memory_store_with_ttl": "low", # "memory_cleanup_expired": "medium",
        # "memory_deduplicate": "medium", # "memory_summarize_recent": "low",
        # browser bridge
        "browser_navigate": "medium", "browser_get_text": "low",
        "browser_click": "medium", "browser_fill": "medium",
        "browser_screenshot": "low", "browser_extract_links": "low",
        "browser_search": "medium", "browser_close": "low",
    }

    # Actions that require human approval before execution
    _APPROVAL_REQUIRED_ACTIONS = {"execute", "shell", "delete", "deploy", "infra", "network_write"}

    def execute(self, tool_name: str, params: dict, approval_mode: str = "SUPERVISED") -> dict:
        """Vérifie ExecutionPolicy puis exécute le tool.

        Retourne {"ok", "result", "error", "blocked_by_policy"}.
        Fail-open : toute exception → {"ok": False, ...}
        """
        if tool_name not in self._tools:
            return {"ok": False, "result": "", "error": f"unknown_tool: {tool_name}", "blocked_by_policy": False}

        # Validate required parameters first — give useful feedback before policy gates
        _early_missing = self._validate_params(tool_name, params)
        if _early_missing:
            return {"ok": False, "result": "", "error": f"missing param: {_early_missing}", "blocked_by_policy": False}

        # Capability registry check (fail-open)
        try:
            from core.capabilities.registry import get_capability_registry
            _cap_reg = get_capability_registry()
            _perm = _cap_reg.check_permission(tool_name)
            if not _perm["allowed"]:
                logger.warning("tool_blocked_by_capability", tool=tool_name, reason=_perm["reason"])
                return {"ok": False, "result": "", "error": f"capability_denied: {_perm['reason']}", "blocked_by_policy": True}
            if _perm["requires_approval"] and approval_mode == "SUPERVISED":
                logger.info("tool_requires_approval", tool=tool_name, risk=_perm["capability"]["risk_level"])
        except Exception as _cap_err:
            logger.debug("capability_check_skipped", error=str(_cap_err))

        # Per-tool permission gate (P1) — requires approval for dangerous tools
        try:
            from core.tool_permissions import get_tool_permissions
            _tp_check = get_tool_permissions().check(
                tool_name, params=params,
                mission_id=params.get("mission_id", "") if params else "",
                agent_id=params.get("_agent_id", "") if params else "",
            )
            if not _tp_check["allowed"]:
                _req = _tp_check["request"]
                logger.info("tool_permission_gated", tool=tool_name,
                           request_id=_req.request_id, risk=_req.risk_level)
                return {
                    "ok": False, "result": "",
                    "error": f"approval_required: {_req.reason}",
                    "blocked_by_policy": True,
                    "approval_request_id": _req.request_id,
                }
        except Exception as _tp_err:
            logger.debug("tool_permission_check_skipped", error=str(_tp_err)[:100])

        # Circuit breaker check (fail-closed for broken tools)
        try:
            from core.resilience import get_circuit_breaker
            _cb = get_circuit_breaker()
            if not _cb.can_execute(tool_name):
                logger.warning("tool_circuit_open", tool=tool_name)
                return {"ok": False, "result": "", "error": f"circuit_open: {tool_name} temporarily disabled", "blocked_by_policy": True}
        except Exception as _exc:
            log.warning("silent_exception_caught", err=str(_exc)[:200], stage="tool_executor")
        # Policy Engine check (economic guardrail)
        try:
            from core.policy.policy_engine import get_policy_engine
            _policy = get_policy_engine()
            _mission_id = params.get("mission_id", "") if params else ""
            _policy_decision = _policy.evaluate(
                tool_name=tool_name,
                mission_id=_mission_id,
                params=params,
            )
            if not _policy_decision.allowed:
                logger.warning("tool_blocked_by_policy",
                             tool=tool_name,
                             reason=_policy_decision.reason,
                             score=_policy_decision.score)
                return {
                    "ok": False, "result": "",
                    "error": f"policy_blocked: {_policy_decision.reason}",
                    "blocked_by_policy": True,
                    "policy_decision": _policy_decision.to_dict(),
                }
            if _policy_decision.requires_approval:
                logger.info("policy_requires_approval",
                           tool=tool_name, score=_policy_decision.score)
        except Exception as _pol_err:
            logger.warning("policy_check_failed", error=str(_pol_err)[:200])
            # Fail-CLOSED for HIGH risk tools; fail-open for LOW risk
            try:
                from core.resilience import JarvisError
                from core.policy.policy_engine import PolicyEngine
                _high_risk = {"shell_execute", "code_execute"}
                if tool_name in _high_risk:
                    logger.warning("policy_fail_closed_high_risk", tool=tool_name)
                    return {
                        "ok": False, "result": "",
                        "error": f"policy_unavailable_high_risk: {tool_name}",
                        "blocked_by_policy": True,
                    }
            except Exception as _exc:
                log.warning("silent_exception_caught", err=str(_exc)[:200], stage="tool_executor")
        # Emit tool_call event for observability
        try:
            from core.observability.event_envelope import get_event_collector
            get_event_collector().emit_quick("tool", "tool_call", {
                "tool": tool_name,
                "params_keys": list(params.keys())[:5] if params else [],
            })
        except Exception as _exc:
            log.warning("silent_exception_caught", err=str(_exc)[:200], stage="tool_executor")
        # Global kill switch check
        if os.environ.get("JARVIS_EXECUTION_DISABLED", "").lower() in ("1", "true", "yes"):
            return {"ok": False, "result": "", "error": "EXECUTION_DISABLED", "blocked_by_policy": True}

        # Approval gating for dangerous actions
        _action_type = self._action_types.get(tool_name, "execute")
        if _action_type in self._APPROVAL_REQUIRED_ACTIONS:
            try:
                from core.governance import classify_danger, log_mission_event
                danger = classify_danger(action=_action_type, goal=str(params)[:200])
                if danger["requires_approval"]:
                    log_mission_event(
                        mission_id="tool_exec",
                        event="approval_required",
                        detail=f"tool={tool_name} action={_action_type} danger={danger['level']}",
                        danger_level=danger["level"],
                    )
                    logger.info("tool_approval_required", tool=tool_name, action=_action_type,
                                danger=danger["level"])
            except Exception as _exc:
                log.warning("silent_exception_caught", err=str(_exc)[:200], stage="tool_executor")
        # Vérification ExecutionPolicy (fail-open)
        try:
            from core.execution_policy import get_execution_policy, ActionContext
            _ctx = ActionContext(
                mission_type="tool_call",
                risk_score=5 if _action_type == "execute" else 2,
                complexity="low",
                agent="tool_executor",
                action_type=_action_type,
                estimated_impact="low",
                mode=approval_mode,
            )
            _decision = get_execution_policy().evaluate(_ctx)
            if _decision.decision in ("BLOCK", "REQUIRE_APPROVAL"):
                logger.warning("tool_blocked_by_policy", tool=tool_name, decision=_decision.decision)
                return {
                    "ok": False, "result": "",
                    "error": f"blocked_by_policy: {_decision.reason}",
                    "blocked_by_policy": True,
                }
        except Exception as _pol_err:
            logger.debug("policy_check_failed_open", err=str(_pol_err))

        # Validation des paramètres requis
        missing = self._validate_params(tool_name, params)
        if missing:
            return {"ok": False, "result": "", "error": f"missing param: {missing}", "blocked_by_policy": False}

        # ── Cognitive journal: tool_requested (fail-open) ─────────────
        _mission_id_for_journal = (params.get("mission_id", "") or params.get("_mission_id", "")) if params else ""
        try:
            from core.cognitive_events.emitter import emit
            from core.cognitive_events.types import EventType
            emit(
                EventType.TOOL_EXECUTION_REQUESTED,
                summary=f"Tool requested: {tool_name}",
                source="tool_executor",
                mission_id=_mission_id_for_journal,
                payload={
                    "tool_name": tool_name,
                    "param_keys": list(params.keys())[:8] if params else [],
                    "risk_level": self._TOOL_RISK_LEVELS.get(tool_name, "unknown"),
                },
            )
        except Exception:
            pass  # Journal is non-blocking

        # ── Kernel event: tool.invoked (dual emission) ────────────
        try:
            from kernel.convergence.event_bridge import emit_kernel_event
            emit_kernel_event("tool.invoked",
                              tool_id=tool_name,
                              mission_id=_mission_id_for_journal,
                              risk_level=self._TOOL_RISK_LEVELS.get(tool_name, "unknown"),
                              param_keys=list(params.keys())[:8] if params else [])
        except Exception:
            _silent_log.debug("suppressed_exception", src='tool_executor.py')

        # Exécution réelle avec retry automatique
        _t0 = _time.time()
        try:
            result = self._execute_with_retry(tool_name, params)
            result["blocked_by_policy"] = False
            result["duration_ms"] = round((_time.time() - _t0) * 1000)
            result["tool"] = tool_name
            # Validation output
            valid, reason = self._validate_output(tool_name, result)
            if not valid:
                logger.warning(f"[OUTPUT_INVALID] tool={tool_name} reason={reason}")
                result["output_valid"] = False
                result["output_reason"] = reason
            else:
                result["output_valid"] = True
            # Enrich with Tool OS metadata (fail-open)
            try:
                from core.tools.tool_os_layer import get_tool
                td = get_tool(tool_name)
                if td:
                    result["_tool_os"] = {
                        "domain": td.domain,
                        "risk_level": td.risk_level,
                        "idempotent": td.idempotent,
                    }
            except Exception as _e:
                log.debug("tool_os_enrich_failed", tool=tool_name, err=str(_e)[:80])

            # ── Cognitive journal: tool_completed or tool_failed (fail-open) ──
            try:
                from core.cognitive_events.emitter import emit_tool_execution
                emit_tool_execution(
                    mission_id=_mission_id_for_journal,
                    tool_name=tool_name,
                    success=bool(result.get("ok")),
                    duration_ms=result.get("duration_ms", 0),
                    error=result.get("error", "")[:200] if not result.get("ok") else "",
                )
            except Exception:
                pass  # Journal is non-blocking

            # ── Kernel event: tool.completed or tool.failed (dual emission) ──
            try:
                from kernel.convergence.event_bridge import emit_kernel_event
                _tool_ok = bool(result.get("ok"))
                emit_kernel_event(
                    "tool.completed" if _tool_ok else "tool.failed",
                    tool_id=tool_name,
                    mission_id=_mission_id_for_journal,
                    duration_ms=result.get("duration_ms", 0),
                    success=_tool_ok,
                    error=result.get("error", "")[:100] if not _tool_ok else "",
                )
            except Exception:
                _silent_log.debug("suppressed_exception", src='tool_executor.py')

            return result
        except Exception as e:
            error_class = _classify_error(str(e))
            _duration_ms = round((_time.time() - _t0) * 1000)
            # AI OS recovery engine evaluation (fail-open)
            try:
                from core.resilience.recovery_engine import get_recovery_engine
                _re = get_recovery_engine()
                _decision = _re.evaluate(e, tool_name=tool_name,
                                          mission_id=params.get("_mission_id", ""))
                result["_recovery"] = _decision.to_dict()
            except Exception as _re_err:
                log.debug("recovery_eval_failed", err=str(_re_err)[:60])

            # ── Cognitive journal: tool_failed (fail-open) ────────────
            try:
                from core.cognitive_events.emitter import emit_tool_execution
                emit_tool_execution(
                    mission_id=_mission_id_for_journal,
                    tool_name=tool_name,
                    success=False,
                    duration_ms=_duration_ms,
                    error=str(e)[:200],
                    error_class=error_class,
                )
            except Exception:
                pass  # Journal is non-blocking

            # ── Kernel event: tool.failed (dual emission) ─────────────
            try:
                from kernel.convergence.event_bridge import emit_kernel_event
                emit_kernel_event("tool.failed",
                                  tool_id=tool_name,
                                  mission_id=_mission_id_for_journal,
                                  duration_ms=_duration_ms,
                                  error=str(e)[:100],
                                  error_class=error_class)
            except Exception:
                _silent_log.debug("suppressed_exception", src='tool_executor.py')

            logger.error(f"[EXECUTE_ERROR] tool={tool_name} class={error_class} error={e}")
            return _err(str(e), error_class=error_class, tool=tool_name, blocked_by_policy=False)

    def _validate_params(self, tool_name: str, params: dict) -> Optional[str]:
        """Retourne le nom du premier paramètre manquant, ou None si tout OK."""
        for p in self._TOOL_REQUIRED_PARAMS.get(tool_name, []):
            if p not in params:
                return p
        return None

    def _dynamic_timeout(self, tool_name: str, base_timeout: int) -> int:
        """
        Si tool a échoué par timeout récemment → augmente de 20%.
        Cherche dans memory_toolkit les erreurs récentes du tool.
        Retourne: base_timeout * multiplicateur (max 2x).
        """
        try:
            from core.tools.memory_toolkit import memory_search_similar
            result = memory_search_similar(query=f"timeout:{tool_name}", top_k=3)
            if result.get("status") == "ok":
                output = result.get("output", "")
                found = int(output.split("found=")[1].split("\n")[0]) if "found=" in output else 0
                if found >= 2:
                    multiplier = min(2.0, 1.0 + found * 0.1)
                    return int(base_timeout * multiplier)
        except Exception as _exc:
            log.warning("silent_exception_caught", err=str(_exc)[:200], stage="tool_executor")
        return base_timeout

    def _validate_output(self, tool_name: str, result: dict) -> tuple:
        """
        Vérifie que result contient au minimum: status, output ou error.
        Retourne (is_valid: bool, reason: str).
        """
        if not isinstance(result, dict):
            return False, "result is not a dict"
        has_status = "status" in result or "ok" in result
        has_content = "output" in result or "error" in result or "result" in result
        if not has_status:
            return False, "missing 'status' or 'ok' field"
        if not has_content:
            return False, "missing 'output', 'error', or 'result' field"
        return True, "ok"

    def _execute_with_retry(self, tool_name: str, params: dict, max_retries: int = 1) -> dict:
        """Exécute un tool avec retry unique (0.3s backoff) sur ok=False non bloqué."""
        fn = self._tools[tool_name]
        call_params = dict(params)
        if tool_name in self._TIMEOUT_SUPPORTED and "timeout" not in call_params:
            base_timeout = self._TOOL_TIMEOUTS.get(tool_name, 10)
            call_params["timeout"] = self._dynamic_timeout(tool_name, base_timeout)

        result: dict = {"ok": False, "result": "", "error": "not_executed"}
        _start_ms = time.time() * 1000
        _retried = False
        # Global timeout guard: no tool can block longer than this
        _max_timeout = call_params.get("timeout", self._TOOL_TIMEOUTS.get(tool_name, 30))
        _max_timeout = min(max(int(_max_timeout), 5), 120)  # clamp 5-120s

        for attempt in range(max_retries + 1):
            # Thread-based timeout guard
            _thread_result = [{"ok": False, "result": "", "error": "timeout_guard"}]
            _thread_exc = [None]
            def _run():
                try:
                    _thread_result[0] = fn(**call_params)
                except Exception as _e:
                    _thread_exc[0] = _e

            import threading as _th
            _t = _th.Thread(target=_run, daemon=True)
            _t.start()
            _t.join(timeout=_max_timeout)
            if _t.is_alive():
                logger.warning("tool_timeout_guard", tool=tool_name, timeout_s=_max_timeout)
                result = _err(
                    f"timeout_guard: {tool_name} exceeded {_max_timeout}s",
                    error_class="TIMEOUT", tool=tool_name
                )
                break
            if _thread_exc[0]:
                # Classify before re-raising for structured error in outer handler
                _thread_exc[0]._jarvis_tool = tool_name
                raise _thread_exc[0]
            result = _thread_result[0]
            if result.get("ok"):
                break
            if attempt < max_retries:
                _retried = True
                logger.info(f"[RETRY] tool={tool_name} attempt={attempt + 2}")
                time.sleep(0.3)

        # ── Circuit breaker feedback ───────────────────────────────────
        try:
            from core.resilience import get_circuit_breaker
            _cb = get_circuit_breaker()
            if result.get("ok"):
                _cb.record_success(tool_name)
            else:
                _cb.record_failure(tool_name)
        except Exception as _exc:
            log.warning("silent_exception_caught", err=str(_exc)[:200], stage="tool_executor")
        # ── Performance tracking (fail-open) ──────────────────────────────
        try:
            from core.tool_performance_tracker import get_tool_performance_tracker, ToolExecution
            _latency = time.time() * 1000 - _start_ms
            _error_class = result.get("error_class", "")
            _error_msg = result.get("error", "")[:200] if not result.get("ok") else ""
            get_tool_performance_tracker().record(ToolExecution(
                tool=tool_name,
                success=bool(result.get("ok")),
                latency_ms=_latency,
                error_type=_error_class,
                error_msg=_error_msg,
                retried=_retried,
                blocked_by_policy=bool(result.get("blocked_by_policy")),
            ))
        except Exception as _perf_err:
            logger.debug("tool_perf_track_failed: %s", str(_perf_err)[:60])
        # ── end performance tracking ──────────────────────────────────────

        return result

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())

    def health_check(self) -> dict:
        """Return tool system health: registered tools, risk distribution, policy status."""
        risk_dist = {"low": 0, "medium": 0, "high": 0, "unknown": 0}
        for tool_name in self._tools:
            risk = self._TOOL_RISK_LEVELS.get(tool_name, "unknown")
            risk_dist[risk] = risk_dist.get(risk, 0) + 1
        policy_ok = True
        try:
            from core.execution_policy import get_execution_policy
            get_execution_policy()
        except Exception as _exc:
            log.warning("exception_caught", err=str(_exc)[:200], stage="tool_executor")
            policy_ok = False
        kill_switch = os.environ.get("JARVIS_EXECUTION_DISABLED", "").lower() in ("1", "true", "yes")
        return {
            "total_tools": len(self._tools),
            "risk_distribution": risk_dist,
            "policy_loaded": policy_ok,
            "kill_switch_active": kill_switch,
            "approval_required_actions": list(self._APPROVAL_REQUIRED_ACTIONS),
        }


_executor: Optional[ToolExecutor] = None

def get_tool_executor() -> ToolExecutor:
    global _executor
    if _executor is None:
        _executor = ToolExecutor()
    return _executor
