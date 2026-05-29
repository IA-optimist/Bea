"""
dev_tools — Outils de développement pour Jarvis OS v3.
Analyse de dépendances, recherche multi-fichiers, génération de schémas API,
vérification de l'environnement, validation de requirements.txt.
Sécurité : paths sous JARVIS_ROOT ou /tmp, try/except global, timeout=10s.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import time

logger = logging.getLogger("jarvis.dev_tools")

JARVIS_ROOT = os.environ.get("JARVIS_ROOT", "/opt/jarvismax")
_BLOCKED_PATHS = ("/etc", "/root", "/proc", "/sys", "\\Windows\\System32")
_MAX_OUTPUT = 50 * 1024  # 50 KB
_MAX_RESULTS = 100


def _ok(output: str, logs: list = None, risk_level: str = "low", **extra) -> dict:
    base = {
        "status": "ok", "ok": True,
        "output": output[:_MAX_OUTPUT], "result": output[:_MAX_OUTPUT],
        "error": None, "logs": logs or [], "risk_level": risk_level,
    }
    base.update(extra)
    return base


def _err(error: str, logs: list = None, risk_level: str = "low", **extra) -> dict:
    base = {
        "status": "error", "ok": False,
        "output": "", "result": "",
        "error": error, "logs": logs or [], "risk_level": risk_level,
    }
    base.update(extra)
    return base


def _is_safe_path(path: str) -> bool:
    """Vérifie que le path est sous JARVIS_ROOT ou /tmp."""
    abs_path = os.path.abspath(path)
    for blocked in _BLOCKED_PATHS:
        if abs_path.startswith(blocked):
            return False
    safe_roots = [os.path.abspath(JARVIS_ROOT), "/tmp", os.path.abspath(".")]  # nosec B108 — path-prefix allowlist, not a write target.
    return any(abs_path.startswith(root) for root in safe_roots)


def dependency_analyzer(project_path: str = None) -> dict:
    """
    Lit requirements.txt, vérifie via pip show si chaque package est installé.
    project_path doit être sous JARVIS_ROOT ou /tmp.

    Args:
        project_path: Chemin du projet (défaut: JARVIS_ROOT)

    Returns:
        {status, installed: list, missing: list, version_conflicts: list}
    """
    try:
        logs = []
        base_path = project_path or JARVIS_ROOT

        if not _is_safe_path(base_path):
            return _err(f"blocked_path: {base_path}")

        req_path = os.path.join(base_path, "requirements.txt")
        if not os.path.exists(req_path):
            req_path = os.path.join(".", "requirements.txt")
        if not os.path.exists(req_path):
            return _err(f"requirements.txt not found in {base_path}")

        with open(req_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        packages = []
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Extraire le nom du package (ignorer version constraints)
            pkg_name = re.split(r"[>=<!;\[]", line)[0].strip()
            if pkg_name:
                packages.append((pkg_name, line))

        installed = []
        missing = []
        version_conflicts = []

        for pkg_name, req_spec in packages:
            try:
                result = subprocess.run(
                    ["pip", "show", pkg_name],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0:
                    # Extraire la version installée
                    version_line = next(
                        (l for l in result.stdout.splitlines() if l.startswith("Version:")),
                        None
                    )
                    installed_version = version_line.split(":", 1)[1].strip() if version_line else "unknown"
                    installed.append({"package": pkg_name, "version": installed_version, "spec": req_spec})
                else:
                    missing.append(pkg_name)
                    logs.append(f"missing: {pkg_name}")
            except subprocess.TimeoutExpired:
                logs.append(f"timeout checking: {pkg_name}")
                missing.append(pkg_name)
            except Exception as e:
                logs.append(f"error checking {pkg_name}: {e}")

        summary = f"installed={len(installed)} missing={len(missing)} conflicts={len(version_conflicts)}"
        logs.append(summary)
        return _ok(
            summary,
            logs=logs,
            installed=installed,
            missing=missing,
            version_conflicts=version_conflicts,
        )
    except Exception as e:
        return _err(f"dependency_analyzer failed: {e}")


def code_search_multi_file(
    directory: str,
    pattern: str,
    file_extensions: list = None,
) -> dict:
    """
    grep récursif sur plusieurs extensions de fichiers.
    Max 100 résultats, timeout=10s.

    Args:
        directory: Répertoire de recherche (sous JARVIS_ROOT ou /tmp)
        pattern: Pattern regex à rechercher
        file_extensions: Liste d'extensions (ex: [".py", ".txt"]) défaut: [".py"]

    Returns:
        {status, matches: [{file, line, content}], total}
    """
    try:
        if not directory:
            return _err("directory is required")
        if not pattern:
            return _err("pattern is required")

        if not _is_safe_path(directory):
            return _err(f"blocked_path: {directory}")

        if not os.path.isdir(directory):
            return _err(f"directory not found: {directory}")

        file_extensions = file_extensions or [".py"]
        matches = []
        logs = []
        t_start = time.monotonic()

        try:
            compiled = re.compile(pattern)
        except re.error as e:
            return _err(f"invalid_pattern: {e}")

        for root, dirs, files in os.walk(directory):
            # Skip hidden dirs and __pycache__
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]

            if time.monotonic() - t_start > 10:
                logs.append("timeout=10s reached, truncating results")
                break

            for fname in files:
                if not any(fname.endswith(ext) for ext in file_extensions):
                    continue
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                        for lineno, line in enumerate(f, 1):
                            if compiled.search(line):
                                matches.append({
                                    "file": fpath,
                                    "line": lineno,
                                    "content": line.rstrip()[:200],
                                })
                                if len(matches) >= _MAX_RESULTS:
                                    logs.append(f"max_results={_MAX_RESULTS} reached")
                                    break
                    if len(matches) >= _MAX_RESULTS:
                        break
                except (PermissionError, OSError):
                    continue

            if len(matches) >= _MAX_RESULTS:
                break

        summary = f"found={len(matches)} matches for pattern='{pattern}'"
        logs.append(summary)
        return _ok(summary, logs=logs, matches=matches, total=len(matches))
    except Exception as e:
        return _err(f"code_search_multi_file failed: {e}")


def api_schema_generator(module_path: str) -> dict:
    """
    Importe le module Python, inspecte les fonctions avec inspect.
    Génère un schema OpenAPI simplifié.

    Args:
        module_path: Chemin Python du module (ex: core.tools.file_tool)

    Returns:
        {status, schema: dict} avec {endpoint, params, returns} par fonction
    """
    try:
        if not module_path:
            return _err("module_path is required")

        import importlib
        import inspect
        logs = []

        # Sécurité: interdire l'import de modules système sensibles
        _BLOCKED_MODULES = ("os", "sys", "subprocess", "shutil", "socket", "ctypes")
        base_module = module_path.split(".")[0]
        if base_module in _BLOCKED_MODULES:
            return _err(f"blocked_module: {base_module}")

        try:
            mod = importlib.import_module(module_path)
        except ImportError as e:
            return _err(f"import_failed: {e}")
        except Exception as e:
            return _err(f"module_load_failed: {e}")

        schema = {}
        for name, obj in inspect.getmembers(mod, inspect.isfunction):
            if name.startswith("_"):
                continue
            try:
                sig = inspect.signature(obj)
                params = {}
                for pname, param in sig.parameters.items():
                    annotation = (
                        param.annotation.__name__
                        if hasattr(param.annotation, "__name__")
                        else str(param.annotation)
                    )
                    default = (
                        None
                        if param.default is inspect.Parameter.empty
                        else str(param.default)
                    )
                    params[pname] = {
                        "type": annotation if annotation != "<class 'inspect._empty'>" else "any",
                        "default": default,
                        "required": param.default is inspect.Parameter.empty,
                    }

                return_annotation = sig.return_annotation
                returns = (
                    return_annotation.__name__
                    if hasattr(return_annotation, "__name__")
                    else str(return_annotation)
                )

                docstring = (inspect.getdoc(obj) or "")[:200]
                schema[name] = {
                    "endpoint": f"/{name.replace('_', '-')}",
                    "params": params,
                    "returns": returns,
                    "doc": docstring,
                }
                logs.append(f"inspected: {name}")
            except Exception as e:
                logs.append(f"skip {name}: {e}")

        summary = f"module={module_path} functions={len(schema)}"
        return _ok(summary, logs=logs, schema=schema)
    except Exception as e:
        return _err(f"api_schema_generator failed: {e}")


def env_checker() -> dict:
    """
    Vérifie les variables d'environnement critiques et l'accès réseau.

    Returns:
        {status, env_vars: dict, network_checks: dict, issues: list}
    """
    try:
        logs = []
        issues = []
        env_vars = {}
        network_checks = {}

        # Variables d'env critiques
        _CRITICAL_VARS = [
            "JARVIS_ROOT", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
            "DATABASE_URL", "REDIS_URL",
        ]
        _MASKED_VARS = {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DATABASE_URL"}

        for var in _CRITICAL_VARS:
            value = os.environ.get(var)
            if value:
                if var in _MASKED_VARS:
                    env_vars[var] = f"***{value[-4:]}" if len(value) > 4 else "***"
                else:
                    env_vars[var] = value
            else:
                env_vars[var] = None
                issues.append(f"missing_env: {var}")
                logs.append(f"[WARN] {var} not set")

        # Vérifications réseau
        _NETWORK_TARGETS = {
            "qdrant": "http://qdrant:6333/health",
            "redis": None,  # Redis check via socket
        }

        try:
            import requests as _req
            qdrant_url = _NETWORK_TARGETS["qdrant"]
            try:
                resp = _req.get(qdrant_url, timeout=3)
                network_checks["qdrant"] = {
                    "url": qdrant_url,
                    "status": resp.status_code,
                    "ok": resp.status_code == 200,
                }
                if resp.status_code != 200:
                    issues.append("qdrant_unhealthy")
            except Exception as e:
                network_checks["qdrant"] = {"url": qdrant_url, "ok": False, "error": str(e)}
                issues.append("qdrant_unreachable")
                logs.append(f"[WARN] qdrant unreachable: {e}")
        except ImportError:
            network_checks["qdrant"] = {"ok": False, "error": "requests not available"}

        # Check Python version
        import sys as _sys
        env_vars["PYTHON_VERSION"] = _sys.version.split()[0]

        status_str = "ok" if not issues else f"issues={len(issues)}"
        logs.append(f"env_checker done: {status_str}")
        return _ok(
            status_str,
            logs=logs,
            env_vars=env_vars,
            network_checks=network_checks,
            issues=issues,
        )
    except Exception as e:
        return _err(f"env_checker failed: {e}")


def system_health_check() -> dict:
    """
    Vérifie la santé globale de l'environnement Jarvis.

    Checks:
    - Variables env critiques (JARVIS_ROOT, OPENAI_API_KEY masked)
    - Connexion Qdrant : GET http://qdrant:6333/health
    - Connexion Redis : ping via socket TCP redis:6379
    - Connexion Ollama : GET http://ollama:11434/api/tags
    - requirements.txt parseable
    - Python version >= 3.10

    Returns: {
        status: "ok" | "warning" | "error",
        checks: {service: {ok: bool, detail: str}},
        warnings: list[str],
        errors: list[str]
    }
    """
    import sys
    import socket
    try:
        import requests
        checks = {}
        warnings = []
        errors = []

        # Python version
        py_ok = sys.version_info >= (3, 10)
        checks["python"] = {"ok": py_ok, "detail": f"Python {sys.version_info.major}.{sys.version_info.minor}"}
        if not py_ok:
            warnings.append("Python < 3.10 detected")

        # Env vars
        critical_vars = ["JARVIS_ROOT", "OPENAI_API_KEY"]
        for var in critical_vars:
            val = os.environ.get(var, "")
            present = bool(val)
            checks[f"env_{var}"] = {"ok": present, "detail": "SET" if present else "MISSING"}
            if not present:
                warnings.append(f"Env var {var} not set")

        # Qdrant
        try:
            r = requests.get("http://qdrant:6333/health", timeout=3)
            checks["qdrant"] = {"ok": r.status_code == 200, "detail": f"HTTP {r.status_code}"}
        except Exception as e:
            checks["qdrant"] = {"ok": False, "detail": str(e)[:60]}
            errors.append(f"Qdrant unreachable: {e}")

        # Redis (TCP ping)
        try:
            s = socket.create_connection(("redis", 6379), timeout=2)
            s.close()
            checks["redis"] = {"ok": True, "detail": "TCP connection OK"}
        except Exception as e:
            checks["redis"] = {"ok": False, "detail": str(e)[:60]}
            warnings.append(f"Redis unreachable: {e}")

        # Ollama
        try:
            r = requests.get("http://ollama:11434/api/tags", timeout=3)
            checks["ollama"] = {"ok": r.status_code == 200, "detail": f"HTTP {r.status_code}"}
        except Exception as e:
            checks["ollama"] = {"ok": False, "detail": str(e)[:60]}
            warnings.append(f"Ollama unreachable: {e}")

        # requirements.txt
        req_path = os.path.join(os.environ.get("JARVIS_ROOT", "/app"), "requirements.txt")
        try:
            with open(req_path) as f:
                lines = [l.strip() for l in f if l.strip() and not l.startswith("#")]
            checks["requirements"] = {"ok": True, "detail": f"{len(lines)} packages listed"}
        except Exception as e:
            checks["requirements"] = {"ok": False, "detail": str(e)[:60]}
            warnings.append(f"requirements.txt unreadable: {e}")

        # Status global
        if errors:
            status = "error"
        elif warnings:
            status = "warning"
        else:
            status = "ok"

        return {"status": status, "checks": checks, "warnings": warnings, "errors": errors}

    except Exception as e:
        return {"status": "error", "checks": {}, "warnings": [], "errors": [str(e)]}


def requirements_validator(requirements_path: str = "requirements.txt") -> dict:
    """
    Parse requirements.txt, vérifie format valide, doublons et conflits.

    Args:
        requirements_path: Chemin vers requirements.txt

    Returns:
        {status, valid: bool, issues: list, duplicates: list}
    """
    try:
        if not _is_safe_path(requirements_path):
            return _err(f"blocked_path: {requirements_path}")

        if not os.path.exists(requirements_path):
            return _err(f"file not found: {requirements_path}")

        logs = []
        issues = []
        duplicates = []
        packages = {}  # name_lower → [(name, spec, lineno)]

        with open(requirements_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        valid = True
        for lineno, line in enumerate(lines, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            # Vérifier le format de base
            if stripped.startswith("-"):
                # Options comme -r, -e, etc. → skip
                continue

            # Extraire nom + version
            match = re.match(r"^([A-Za-z0-9_\-\.]+)\s*([>=<!~\^\*].*)?$", stripped)
            if not match:
                issues.append(f"line {lineno}: invalid format: '{stripped}'")
                valid = False
                logs.append(f"invalid line {lineno}: {stripped}")
                continue

            pkg_name = match.group(1).lower()
            version_spec = match.group(2) or ""

            if pkg_name in packages:
                packages[pkg_name].append((match.group(1), version_spec, lineno))
            else:
                packages[pkg_name] = [(match.group(1), version_spec, lineno)]

        # Détecter les doublons
        for pkg_name, entries in packages.items():
            if len(entries) > 1:
                dup_info = {
                    "package": pkg_name,
                    "occurrences": [{"name": e[0], "spec": e[1], "line": e[2]} for e in entries],
                }
                duplicates.append(dup_info)
                issues.append(f"duplicate: {pkg_name} (lines {[e[2] for e in entries]})")
                logs.append(f"duplicate: {pkg_name}")

        # Détecter les conflits de version évidents (ex: pkg>=2.0 et pkg<1.5)
        for pkg_name, entries in packages.items():
            if len(entries) >= 2:
                specs = [e[1] for e in entries if e[1]]
                lower_bounds = [
                    float(re.search(r"[\d.]+", s).group()) if re.search(r"[\d.]+", s) else None
                    for s in specs if ">=" in s
                ]
                upper_bounds = [
                    float(re.search(r"[\d.]+", s).group()) if re.search(r"[\d.]+", s) else None
                    for s in specs if "<" in s and ">=" not in s
                ]
                for lb in lower_bounds:
                    for ub in upper_bounds:
                        if lb is not None and ub is not None and lb >= ub:
                            issues.append(f"conflict: {pkg_name}>={lb} vs <{ub}")
                            logs.append(f"conflict: {pkg_name}")
                            valid = False

        summary = f"valid={valid} packages={len(packages)} issues={len(issues)} duplicates={len(duplicates)}"
        logs.append(summary)
        return _ok(
            summary,
            logs=logs,
            valid=valid,
            issues=issues,
            duplicates=duplicates,
            package_count=len(packages),
        )
    except Exception as e:
        return _err(f"requirements_validator failed: {e}")
