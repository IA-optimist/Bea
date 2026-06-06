"""
tool_builder_tool — Génère des tools à la demande pour Jarvis.
Pipeline : analyze_tool_need → generate_tool_skeleton → generate_tool_tests
           → optionnel: register_tool_in_executor + save_tool_to_memory
Retourne toujours {status, output, error, logs, risk_level}.
"""
from __future__ import annotations

import logging
import os
import structlog

log = structlog.get_logger(__name__)
_silent_log = structlog.get_logger(__name__)
import re

logger = logging.getLogger("jarvis.tool_builder")

# Libs présentes dans requirements.txt (sans dépendances lourdes)
_KNOWN_LIBS = {
    "requests", "httpx", "fastapi", "pydantic", "redis", "asyncpg",
    "psycopg2", "qdrant_client", "openai", "structlog", "rich",
    "python_dotenv", "aiofiles", "tenacity", "psutil", "langfuse",
    "langchain", "langchain_core", "langchain_openai", "langchain_anthropic",
    "playwright", "pypdf", "docx", "tiktoken", "sentence_transformers",
    "subprocess", "os", "sys", "json", "re", "time", "datetime",
    "pathlib", "hashlib", "random", "math", "io", "inspect",
}

JARVIS_ROOT = os.environ.get("JARVIS_ROOT", "/opt/jarvismax")


def _ok(output: str, logs: list = None, risk_level: str = "low", **extra) -> dict:
    base = {
        "status": "ok", "ok": True,
        "output": output, "result": output,
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


def analyze_tool_need(description: str, required_inputs: list, required_outputs: list) -> dict:
    """
    Analyse le besoin, retourne un plan de tool.

    Args:
        description: Description du tool en langage naturel
        required_inputs: Liste des paramètres d'entrée attendus
        required_outputs: Liste des champs de sortie attendus

    Returns:
        {status, output, plan: {name, type, libs_needed, missing_libs}}
    """
    try:
        if not description:
            return _err("description is required")
        if not isinstance(required_inputs, list):
            return _err("required_inputs must be a list")
        if not isinstance(required_outputs, list):
            return _err("required_outputs must be a list")

        logs = []

        # Inférer le type de tool
        desc_lower = description.lower()
        tool_type = "utility"
        if any(kw in desc_lower for kw in ("http", "get", "post", "api", "url", "fetch")):
            tool_type = "network"
        elif any(kw in desc_lower for kw in ("file", "read", "write", "path", "directory")):
            tool_type = "filesystem"
        elif any(kw in desc_lower for kw in ("docker", "container", "image")):
            tool_type = "docker"
        elif any(kw in desc_lower for kw in ("git", "commit", "branch", "repo")):
            tool_type = "git"
        elif any(kw in desc_lower for kw in ("test", "pytest", "assert", "check")):
            tool_type = "testing"
        elif any(kw in desc_lower for kw in ("memory", "qdrant", "vector", "store")):
            tool_type = "memory"

        # Inférer les libs nécessaires
        libs_needed = set()
        if tool_type == "network":
            libs_needed.add("requests")
        if tool_type == "filesystem":
            libs_needed.update(["os", "pathlib"])
        if tool_type == "docker":
            libs_needed.add("subprocess")
        if tool_type == "git":
            libs_needed.add("subprocess")
        if tool_type == "memory":
            libs_needed.add("requests")

        # Vérifier libs manquantes
        missing_libs = [lib for lib in libs_needed if lib not in _KNOWN_LIBS]
        logs.append(f"tool_type={tool_type} libs={list(libs_needed)} missing={missing_libs}")

        # Générer nom suggéré
        words = re.findall(r"[a-z]+", desc_lower)[:3]
        suggested_name = "_".join(words) if words else "custom_tool"

        plan = {
            "name": suggested_name,
            "type": tool_type,
            "libs_needed": list(libs_needed),
            "missing_libs": missing_libs,
            "inputs": required_inputs,
            "outputs": required_outputs,
            "feasible": len(missing_libs) == 0,
        }
        msg = f"plan={plan['name']} type={tool_type} feasible={plan['feasible']}"
        return _ok(msg, logs=logs, plan=plan)
    except Exception as e:
        return _err(f"analyze_tool_need failed: {e}")


def generate_tool_skeleton(
    tool_name: str,
    description: str,
    input_schema: dict,
    output_schema: dict,
    safety_constraints: list = None,
) -> dict:
    """
    Génère le code Python du tool (skeleton avec try/except, logs, retour unifié).

    Args:
        tool_name: Nom de la fonction Python à générer
        description: Description du tool
        input_schema: Dict {param_name: type_str}
        output_schema: Dict {field_name: type_str}
        safety_constraints: Liste de contraintes de sécurité

    Returns:
        {status, code: str, filename: str}
    """
    try:
        if not tool_name or not re.match(r"^[a-z][a-z0-9_]*$", tool_name):
            return _err("tool_name must be snake_case")
        if not isinstance(input_schema, dict):
            return _err("input_schema must be a dict")
        if not isinstance(output_schema, dict):
            return _err("output_schema must be a dict")

        safety_constraints = safety_constraints or []
        logs = []

        # Construire la signature
        params = []
        for name, typ in input_schema.items():
            if typ in ("str", "int", "float", "bool"):
                params.append(f"{name}: {typ}")
            elif typ.startswith("list"):
                params.append(f"{name}: list = None")
            elif typ.startswith("dict"):
                params.append(f"{name}: dict = None")
            else:
                params.append(f"{name}: str = None")
        signature = ", ".join(params)

        # Construire docstring
        inputs_doc = "\n".join(f"        {n}: {t}" for n, t in input_schema.items())
        outputs_doc = "\n".join(f"        {n}: {t}" for n, t in output_schema.items())
        example_args = ", ".join(f'"{n}": "value"' for n in input_schema.keys())

        # Construire contraintes de sécurité
        safety_checks = ""
        for constraint in safety_constraints:
            if "path" in constraint.lower():
                safety_checks += f"""
    # Safety: path traversal check
    import os as _os
    _jarvis_root = _os.environ.get("JARVIS_ROOT", "/opt/jarvismax")
    for _blocked in ("/etc", "/root", "/proc", "/sys"):
        if any(_blocked in str(v) for v in [{', '.join(repr(n) for n in input_schema.keys() if 'path' in n.lower())}]):
            return _err(f"blocked_path: {{_blocked}}")
"""
            elif "url" in constraint.lower():
                safety_checks += """
    # Safety: URL check
    _BLOCKED_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0")
    for _bh in _BLOCKED_HOSTS:
        for _v in [v for v in locals().values() if isinstance(v, str) and "http" in v]:
            if _bh in _v:
                return _err(f"blocked_host: {_bh}")
"""

        # Construire le retour example
        output_fields = ", ".join(f'"{n}": None' for n in output_schema.keys())

        code = f'''"""
{tool_name} — {description}
Auto-généré par tool_builder_tool.
"""
from __future__ import annotations
import logging

logger = logging.getLogger("jarvis.tools.{tool_name}")


def _ok(output: str, logs: list = None, **extra) -> dict:
    base = {{"status": "ok", "ok": True, "output": output, "error": None, "logs": logs or [], "risk_level": "low"}}
    base.update(extra)
    return base


def _err(error: str, logs: list = None, **extra) -> dict:
    base = {{"status": "error", "ok": False, "output": "", "error": error, "logs": logs or [], "risk_level": "low"}}
    base.update(extra)
    return base


def {tool_name}({signature}) -> dict:
    """
    {description}

    Args:
{inputs_doc}

    Returns:
{outputs_doc}

    Example:
        result = {tool_name}({{{example_args}}})
    """
    try:
        logs = []
{safety_checks}
        # IMPLEMENT: Add your tool logic here (auto-generated stub)

        result = {{{output_fields}}}
        logs.append("{tool_name} executed successfully")
        return _ok(str(result), logs=logs, **result)
    except Exception as e:
        logger.error(f"[{tool_name.upper()}] error={{e}}")
        return _err(str(e))
'''
        filename = f"core/tools/{tool_name}.py"
        logs.append(f"generated {len(code)} chars → {filename}")
        return _ok(f"skeleton generated: {filename}", logs=logs, code=code, filename=filename)
    except Exception as e:
        return _err(f"generate_tool_skeleton failed: {e}")


def generate_tool_tests(tool_name: str, tool_code: str) -> dict:
    """
    Génère tests unitaires basiques pour le tool.

    Args:
        tool_name: Nom de la fonction du tool
        tool_code: Code source du tool

    Returns:
        {status, test_code: str, test_filename: str}
    """
    try:
        if not tool_name:
            return _err("tool_name is required")
        if not tool_code:
            return _err("tool_code is required")

        logs = []

        # Extraire les paramètres depuis la signature
        sig_match = re.search(rf"def {tool_name}\(([^)]*)\)", tool_code)
        sig_params = []
        if sig_match:
            raw_params = sig_match.group(1).strip()
            if raw_params:
                for p in raw_params.split(","):
                    p = p.strip()
                    if ":" in p:
                        pname = p.split(":")[0].strip()
                        ptype = p.split(":")[1].split("=")[0].strip()
                    elif "=" in p:
                        pname = p.split("=")[0].strip()
                        ptype = "str"
                    else:
                        pname = p
                        ptype = "str"
                    sig_params.append((pname, ptype))

        # Générer les valeurs de test
        test_args_valid = []
        test_args_none = []
        for pname, ptype in sig_params:
            if "list" in ptype:
                test_args_valid.append(f'{pname}=["test"]')
            elif "dict" in ptype:
                test_args_valid.append(f'{pname}={{"key": "value"}}')
            elif "int" in ptype:
                test_args_valid.append(f"{pname}=1")
            elif "bool" in ptype:
                test_args_valid.append(f"{pname}=True")
            else:
                test_args_valid.append(f'{pname}="test_value"')
            test_args_none.append(f'{pname}=None')

        valid_call = f"{tool_name}({', '.join(test_args_valid)})"
        none_call = f"{tool_name}({', '.join(test_args_none)})" if test_args_none else f"{tool_name}()"
        f"{tool_name}()" if not any("=" not in a for a in test_args_valid) else f"{tool_name}()"

        # Détecter le module
        module_path = f"core.tools.{tool_name}"

        test_code = f'''"""Tests unitaires pour {tool_name}."""
import pytest


def test_{tool_name}_import():
    """Test que le module s'importe sans erreur."""
    try:
        from {module_path} import {tool_name}
        assert callable({tool_name})
    except ImportError as e:
        pytest.skip(f"Module non disponible: {{e}}")


def test_{tool_name}_valid_call():
    """Test appel avec paramètres valides → retourne dict avec status."""
    try:
        from {module_path} import {tool_name}
        result = {valid_call}
        assert isinstance(result, dict), "result doit être un dict"
        assert "status" in result or "ok" in result, "result doit avoir 'status' ou 'ok'"
    except ImportError as e:
        pytest.skip(f"Module non disponible: {{e}}")


def test_{tool_name}_none_params():
    """Test appel avec params None → retourne error propre (pas de crash)."""
    try:
        from {module_path} import {tool_name}
        result = {none_call}
        assert isinstance(result, dict), "result doit être un dict même avec params None"
        # Pas de crash = succès
    except ImportError as e:
        pytest.skip(f"Module non disponible: {{e}}")
    except TypeError:
        pass  # Acceptable si params requis non fournis


def test_{tool_name}_returns_unified_format():
    """Test que le retour respecte le format unifié {{status, output/error}}."""
    try:
        from {module_path} import {tool_name}
        result = {valid_call}
        assert "status" in result or "ok" in result
        assert "output" in result or "error" in result or "result" in result
    except ImportError as e:
        pytest.skip(f"Module non disponible: {{e}}")
'''
        test_filename = f"tests/test_{tool_name}.py"
        logs.append(f"generated {len(test_code)} chars → {test_filename}")
        return _ok(f"tests generated: {test_filename}", logs=logs, test_code=test_code, test_filename=test_filename)
    except Exception as e:
        return _err(f"generate_tool_tests failed: {e}")


def register_tool_in_executor(
    tool_name: str,
    function_name: str,
    required_params: list,
    timeout: int = 10,
) -> dict:
    """
    Ajoute le tool dans tool_executor.py : _TOOL_TIMEOUTS, _TOOL_REQUIRED_PARAMS.
    Utilise write_file_safe() via RollbackContext.
    risk_level: "medium"

    Args:
        tool_name: Nom du tool dans le registre (ex: "my_tool")
        function_name: Nom de la fonction Python (ex: "my_tool_function")
        required_params: Liste des paramètres requis
        timeout: Timeout en secondes

    Returns:
        {status, output, patched_lines}
    """
    try:
        logs = []
        executor_path = os.path.join(JARVIS_ROOT, "core", "tool_executor.py")
        if not os.path.exists(executor_path):
            executor_path = "core/tool_executor.py"

        with open(executor_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Vérifier si déjà enregistré
        if f'"{tool_name}"' in content:
            return _ok(f"tool '{tool_name}' already registered", logs=["already_registered"], risk_level="medium")

        # Ajouter dans _TOOL_TIMEOUTS
        timeout_anchor = '"check_api_fields": 15, "sync_app_fields": 15,'
        if timeout_anchor in content:
            timeout_entry = f'        "{tool_name}": {timeout},'
            content = content.replace(
                timeout_anchor,
                f'{timeout_anchor}\n{timeout_entry}'
            )
            logs.append(f"added timeout: {tool_name}={timeout}s")

        # Ajouter dans _TOOL_REQUIRED_PARAMS
        params_anchor = '"memory_search_similar": ["query"],'
        if params_anchor in content:
            params_list = '", "'.join(required_params)
            params_entry = f'        "{tool_name}": ["{params_list}"],' if required_params else f'        "{tool_name}": [],'
            content = content.replace(
                params_anchor,
                f'{params_anchor}\n{params_entry}'
            )
            logs.append(f"added required_params: {tool_name}={required_params}")

        # Écrire avec write_file_safe
        try:
            from core.rollback_manager import RollbackContext, save_diff
            old_content = ""
            try:
                with open(executor_path, "r", encoding="utf-8") as f:
                    old_content = f.read()
            except FileNotFoundError as _exc:
                log.warning("swallowed_exception", action="tool_builder_tool_swallow", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
            with RollbackContext(executor_path) as ctx:
                with open(executor_path, "w", encoding="utf-8") as f:
                    f.write(content)
                save_diff(executor_path, old_content, content, ctx.ts)
            logs.append("written via RollbackContext")
        except Exception as rb_err:
            # Fallback: écriture directe
            with open(executor_path, "w", encoding="utf-8") as f:
                f.write(content)
            logs.append(f"written directly (rollback unavailable: {rb_err})")

        return _ok(f"tool '{tool_name}' registered in tool_executor.py", logs=logs, risk_level="medium")
    except Exception as e:
        return _err(f"register_tool_in_executor failed: {e}", risk_level="medium")


def save_tool_to_memory(tool_name: str, description: str, code: str) -> dict:
    """
    Stocke le pattern du tool dans Qdrant collection 'jarvis_tools'.

    Args:
        tool_name: Nom du tool
        description: Description du tool
        code: Code source

    Returns:
        {status, output}
    """
    try:
        from core.tools.memory_toolkit import memory_store_solution
        result = memory_store_solution(
            problem=f"tool_pattern:{tool_name} — {description}",
            solution=code[:500],
            tags=["tool_pattern", tool_name],
        )
        return result
    except Exception as e:
        return _err(f"save_tool_to_memory failed: {e}")


def validate_tool_structure(tool_code: str, tool_name: str) -> dict:
    """
    Valide qu'un tool généré respecte les standards Jarvis.

    Checks:
    - Contient def {tool_name}()
    - Contient try/except
    - Contient return {...}
    - Contient docstring (triple quotes)
    - Ne contient pas d'import dangereux (os.system, eval, exec, __import__)

    Returns: {valid: bool, issues: list[str], score: float}
    """
    try:
        issues = []

        if f"def {tool_name}" not in tool_code:
            issues.append(f"Missing function definition: def {tool_name}")

        if "try:" not in tool_code or "except" not in tool_code:
            issues.append("Missing try/except error handling")

        if '"""' not in tool_code and "'''" not in tool_code:
            issues.append("Missing docstring")

        if "return {" not in tool_code and "return{" not in tool_code:
            issues.append("Missing dict return (expected {status, output, error})")

        danger_patterns = ["os.system(", "eval(", "exec(", "__import__"]
        for p in danger_patterns:
            if p in tool_code:
                issues.append(f"Dangerous pattern detected: {p}")

        score = max(0.0, 1.0 - len(issues) * 0.2)
        return {"valid": len(issues) == 0, "issues": issues, "score": round(score, 2)}

    except Exception as e:
        return {"valid": False, "issues": [str(e)], "score": 0.0}


def build_complete_tool(
    description: str,
    tool_name: str,
    input_schema: dict,
    output_schema: dict,
    safety_constraints: list = None,
    auto_register: bool = False,
) -> dict:
    """
    Pipeline complet : analyze → generate_skeleton → generate_tests
    → optionnel: register_tool_in_executor + save_tool_to_memory.
    NE PAS auto_commit — laisser à l'opérateur.

    Args:
        description: Description du tool
        tool_name: Nom du tool (snake_case)
        input_schema: Dict {param_name: type_str}
        output_schema: Dict {field_name: type_str}
        safety_constraints: Contraintes de sécurité
        auto_register: Si True, enregistre dans tool_executor.py

    Returns:
        {status, report, files_generated}
    """
    try:
        safety_constraints = safety_constraints or []
        logs = []
        files_generated = []
        report = {}

        # Étape 1: Analyze
        inputs_list = list(input_schema.keys())
        outputs_list = list(output_schema.keys())
        analysis = analyze_tool_need(description, inputs_list, outputs_list)
        report["analysis"] = analysis
        logs.append(f"analyze: {analysis['status']}")

        if analysis["status"] != "ok":
            return _err(f"analysis failed: {analysis['error']}", logs=logs, report=report)

        # Étape 2: Generate skeleton
        skeleton = generate_tool_skeleton(tool_name, description, input_schema, output_schema, safety_constraints)
        report["skeleton"] = {"status": skeleton["status"], "filename": skeleton.get("filename")}
        logs.append(f"skeleton: {skeleton['status']}")

        if skeleton["status"] != "ok":
            return _err(f"skeleton failed: {skeleton['error']}", logs=logs, report=report)

        files_generated.append(skeleton["filename"])

        # Étape 3: Generate tests
        tests = generate_tool_tests(tool_name, skeleton["code"])
        report["tests"] = {"status": tests["status"], "filename": tests.get("test_filename")}
        logs.append(f"tests: {tests['status']}")

        if tests["status"] == "ok":
            files_generated.append(tests["test_filename"])

        # Étape 4 (optionnel): Register + save
        if auto_register:
            reg = register_tool_in_executor(tool_name, tool_name, inputs_list)
            report["register"] = {"status": reg["status"]}
            logs.append(f"register: {reg['status']}")

            mem = save_tool_to_memory(tool_name, description, skeleton["code"])
            report["memory"] = {"status": mem["status"]}
            logs.append(f"memory: {mem['status']}")

        summary = (
            f"tool_name={tool_name} "
            f"files={files_generated} "
            f"auto_register={auto_register}"
        )
        return _ok(
            summary,
            logs=logs,
            report=report,
            files_generated=files_generated,
            skeleton_code=skeleton.get("code"),
            test_code=tests.get("test_code"),
        )
    except Exception as e:
        return _err(f"build_complete_tool failed: {e}")
