"""
core/tool_registry.py — Tool DEFINITION Registry
=================================================

ROLE: Holds tool DEFINITIONS (ToolDefinition objects) with metadata:
      descriptions, risk levels, action types, network requirements.
      This is the "what tools exist and what are their properties?" layer.

DISTINCT FROM: tools/tool_registry.py — which holds live tool INSTANCES
      and actually executes them. That is the "run it" layer.

CANONICAL IMPORT for metadata/discovery:
    from core.tool_registry import get_tool_registry
    tools = get_tool_registry().list_tools()  # → List[ToolDefinition]
    ranked = rank_tools_for_task("write Python code")

CANONICAL IMPORT for execution:
    from tools.tool_registry import get_tool_registry as get_executor
    result = get_executor().execute("python_tool", "run", {"code": "..."})

Additional utilities exported:
    rank_tools_for_task(task, top_k) → ranked tool recommendations
    should_create_tool(task) → gap analysis dict
    list_all_tools() → full tool catalog as list of dicts
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class ToolDefinition:
    name: str
    description: str
    action_type: str        # mappe vers ExecutionPolicy action_types
    risk_level: str         # "low" | "medium" | "high"
    expected_input: str     # description du format d'entrée
    expected_output: str    # description du format de sortie
    requires_network: bool = False
    idempotent: bool = True


# ── Registre des tools de base ─────────────────────────────────────────────
_BASE_TOOLS: List[ToolDefinition] = [
    ToolDefinition(
        name="read_file",
        description="Lire le contenu d'un fichier local",
        action_type="read",
        risk_level="low",
        expected_input="file_path: str",
        expected_output="content: str",
        idempotent=True,
    ),
    ToolDefinition(
        name="write_file",
        description="Écrire ou modifier un fichier local",
        action_type="write",
        risk_level="medium",
        expected_input="file_path: str, content: str",
        expected_output="success: bool",
        idempotent=False,
    ),
    ToolDefinition(
        name="list_directory",
        description="Lister le contenu d'un répertoire",
        action_type="read",
        risk_level="low",
        expected_input="directory_path: str",
        expected_output="files: list[str]",
        idempotent=True,
    ),
    ToolDefinition(
        name="run_command_safe",
        description="Exécuter une commande shell sûre (lecture seule, pas de sudo)",
        action_type="execute",
        risk_level="medium",
        expected_input="command: str, timeout_s: int = 10",
        expected_output="stdout: str, returncode: int",
        idempotent=False,
    ),
    ToolDefinition(
        name="search_codebase",
        description="Rechercher un pattern dans le codebase",
        action_type="read",
        risk_level="low",
        expected_input="pattern: str, path: str = '.'",
        expected_output="matches: list[dict]",
        idempotent=True,
    ),
    ToolDefinition(
        name="check_logs",
        description="Lire les dernières lignes des logs du système",
        action_type="read",
        risk_level="low",
        expected_input="service: str, lines: int = 50",
        expected_output="log_lines: list[str]",
        idempotent=True,
    ),
    ToolDefinition(
        name="test_endpoint",
        description="Tester un endpoint HTTP et retourner status + latence",
        action_type="external_api",
        risk_level="medium",
        expected_input="url: str, method: str = 'GET'",
        expected_output="status: int, latency_ms: int, body: str",
        requires_network=True,
        idempotent=True,
    ),
    # ── Browser automation tools ──────────────────────────────────────────
    ToolDefinition(
        name="browser_navigate",
        description="Navigate to a URL using headless Chromium browser",
        action_type="network",
        risk_level="medium",
        expected_input="url: str",
        expected_output="title: str, url: str",
        requires_network=True,
        idempotent=True,
    ),
    ToolDefinition(
        name="browser_get_text",
        description="Extract visible text from a CSS selector on the current page",
        action_type="read",
        risk_level="low",
        expected_input="selector: str = 'body'",
        expected_output="text: str",
        requires_network=False,
        idempotent=True,
    ),
    ToolDefinition(
        name="browser_click",
        description="Click an element on the current browser page",
        action_type="write",
        risk_level="medium",
        expected_input="selector: str",
        expected_output="selector: str",
        requires_network=False,
        idempotent=False,
    ),
    ToolDefinition(
        name="browser_fill",
        description="Fill a form field on the current browser page",
        action_type="write",
        risk_level="medium",
        expected_input="selector: str, value: str",
        expected_output="selector: str",
        requires_network=False,
        idempotent=False,
    ),
    ToolDefinition(
        name="browser_screenshot",
        description="Take a screenshot of the current browser page",
        action_type="read",
        risk_level="low",
        expected_input="path: str = ''",
        expected_output="path: str, size_bytes: int, base64?: str",
        requires_network=False,
        idempotent=True,
    ),
    ToolDefinition(
        name="browser_extract_links",
        description="Extract all links from the current browser page",
        action_type="read",
        risk_level="low",
        expected_input="(none — operates on current page)",
        expected_output="links: list[{text, href}], count: int",
        requires_network=False,
        idempotent=True,
    ),
    ToolDefinition(
        name="browser_search",
        description="Search the web via headless browser (DuckDuckGo/Google/Bing)",
        action_type="network",
        risk_level="medium",
        expected_input="query: str, engine: str = 'duckduckgo'",
        expected_output="results: list[{title, url, snippet}], count: int",
        requires_network=True,
        idempotent=True,
    ),
]

# ── Mapping mission_type → tools recommandés ──────────────────────────────
_MISSION_TOOLS: Dict[str, List[str]] = {
    "coding_task":      ["write_file", "search_codebase", "run_command_safe"],
    "debug_task":       ["check_logs", "run_command_safe", "read_file"],
    "architecture_task":["read_file", "search_codebase"],
    "system_task":      ["test_endpoint", "check_logs", "run_command_safe"],
    "research_task":    ["search_codebase", "read_file", "browser_search", "browser_navigate", "browser_get_text"],
    "evaluation_task":  ["test_endpoint", "check_logs"],
    "planning_task":    [],
    "info_query":       ["browser_search", "browser_navigate", "browser_get_text"],
    "compare_query":    ["search_codebase", "browser_search"],
    "business_task":    ["browser_search", "browser_navigate", "browser_get_text", "browser_extract_links"],
    "self_improvement_task": ["check_logs", "read_file"],
}


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {t.name: t for t in _BASE_TOOLS}

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def list_tools(self) -> List[ToolDefinition]:
        return list(self._tools.values())

    def get_tools_for_mission_type(self, mission_type: str) -> List[ToolDefinition]:
        """Retourne les tools recommandés pour un mission_type."""
        names = _MISSION_TOOLS.get(mission_type, [])
        return [self._tools[n] for n in names if n in self._tools]

    def get_safe_tools(self, mode: str = "SUPERVISED") -> List[ToolDefinition]:
        """Retourne tools compatibles avec le mode d'approbation."""
        if mode == "MANUAL":
            return []
        if mode == "SUPERVISED":
            return [t for t in self._tools.values() if t.risk_level == "low"]
        # AUTO
        return [t for t in self._tools.values() if t.risk_level in ("low", "medium")]

    def validate_all(self) -> Dict[str, List[str]]:
        """Validate all registered tools against the unified tool spec.

        Returns dict with 'valid' list and 'issues' list.
        Each issue is a string describing the problem.
        """
        valid = []
        issues = []
        for name, tool in self._tools.items():
            problems = []
            if not tool.name or not tool.name.strip():
                problems.append(f"{name}: missing name")
            if not tool.description or len(tool.description) < 5:
                problems.append(f"{name}: description too short (<5 chars)")
            if tool.risk_level not in ("low", "medium", "high"):
                problems.append(f"{name}: invalid risk_level '{tool.risk_level}'")
            if tool.action_type not in ("read", "write", "execute", "network", "search", "external_api"):
                problems.append(f"{name}: invalid action_type '{tool.action_type}'")
            if not tool.expected_input:
                problems.append(f"{name}: missing expected_input")
            if not tool.expected_output:
                problems.append(f"{name}: missing expected_output")
            if problems:
                issues.extend(problems)
            else:
                valid.append(name)
        return {"valid": valid, "issues": issues, "total": len(self._tools)}

    def summary(self) -> List[dict]:
        return [
            {"name": t.name, "action_type": t.action_type, "risk": t.risk_level,
             "requires_network": t.requires_network, "idempotent": t.idempotent}
            for t in self._tools.values()
        ]


# Singleton
_registry: Optional[ToolRegistry] = None

def get_tool_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry


# ── Scoring sémantique (ajout qualité décision) ────────────────────────────────

try:
    from core.tool_executor import ToolExecutor as _TE
    _EXECUTOR_TOOLS: dict = _TE._tools
    _EXECUTOR_TIMEOUTS: dict = _TE._TOOL_TIMEOUTS
    _EXECUTOR_REQUIRED_PARAMS: dict = _TE._TOOL_REQUIRED_PARAMS
except Exception as _te_err:
    logger.warning(f"[REGISTRY] ToolExecutor import failed (fail-open): {_te_err}")
    _EXECUTOR_TOOLS = {}
    _EXECUTOR_TIMEOUTS = {}
    _EXECUTOR_REQUIRED_PARAMS = {}

# Descriptions sémantiques pour le scoring
_SEMANTIC_DESCRIPTIONS: Dict[str, str] = {
    "shell_command":            "Execute a shell command on the system",
    "read_file":                "Read the content of a file from disk",
    "write_file":               "Write or overwrite a file on disk safely with rollback",
    "write_file_safe":          "Write or overwrite a file on disk safely with rollback",
    "http_get":                 "Make an HTTP GET request to a URL",
    "python_snippet":           "Execute a Python code snippet",
    "vector_search":            "Search similar items in Qdrant vector database",
    "git_status":               "Get git repository status",
    "git_log":                  "Get recent git commit history",
    "git_diff":                 "Show git diff for a file or repo",
    "git_commit":               "Commit files to git repository",
    "git_push":                 "Push commits to remote git repository",
    "git_pull":                 "Pull latest changes from remote git",
    "git_branch":               "Get current git branch name",
    "git_branch_create":        "Create a new git branch",
    "git_checkout":             "Checkout a git branch",
    "docker_ps":                "List running Docker containers",
    "docker_logs":              "Get logs from a Docker container",
    "docker_restart":           "Restart a Docker container",
    "docker_inspect":           "Inspect a Docker container details",
    "docker_compose_build":     "Build Docker Compose services",
    "docker_compose_up":        "Start Docker Compose services",
    "docker_compose_down":      "Stop Docker Compose services",
    "search_in_files":          "Search for a text pattern in files recursively",
    "replace_in_file":          "Replace text in a file with rollback",
    "file_create":              "Create a new file with content",
    "file_delete_safe":         "Delete a file safely with rollback",
    "create_directory":         "Create a directory",
    "list_project_structure":   "List directory structure like a tree",
    "count_lines":              "Count lines in a file",
    "workspace_snapshot":       "Take a snapshot of the workspace",
    "search_pypi":              "Search PyPI for a Python package",
    "fetch_url":                "Fetch content from a URL and extract text",
    "fetch_github_readme":      "Fetch README from a GitHub repository",
    "http_post_json":           "Make an HTTP POST request with JSON payload",
    "check_url_status":         "Check if a URL is reachable",
    "doc_fetch":                "Fetch documentation from a URL",
    "run_unit_tests":           "Run pytest unit tests and return results",
    "run_smoke_tests":          "Run basic smoke tests against the API",
    "api_healthcheck":          "Check API health endpoints",
    "test_endpoint":            "Test a specific API endpoint",
    "memory_store_solution":    "Store a solution or learning in vector memory",
    "memory_search_similar":    "Search for similar past solutions in memory",
    "memory_store_error":       "Store an error and fix in memory",
    "memory_store_patch":       "Store a code patch in memory",
    "memory_store_with_ttl":    "Store a memory entry with TTL expiry",
    "memory_cleanup_expired":   "Clean up expired memory entries",
    "memory_deduplicate":       "Remove duplicate memory entries",
    "memory_summarize_recent":  "Summarize recent memory entries",
    "check_api_fields":         "Check API field consistency",
    "sync_app_fields":          "Synchronize app fields with API",
    "analyze_tool_need":        "Analyze whether a new tool is needed for a task",
    "generate_tool_skeleton":   "Generate a skeleton for a new tool",
    "generate_tool_tests":      "Generate tests for a tool",
    "build_complete_tool":      "Generate a complete new tool from a description",
    "dependency_analyzer":      "Analyze project dependencies and find missing ones",
    "code_search_multi_file":   "Search code across multiple files and extensions",
    "api_schema_generator":     "Generate API schema from module",
    "env_checker":              "Check environment variables and system connectivity",
    "requirements_validator":   "Validate requirements.txt for issues",
}

# Coût estimé (1=minimal, 5=coûteux)
_TOOL_COSTS: Dict[str, int] = {
    "shell_command": 3, "read_file": 1, "write_file": 2, "write_file_safe": 2,
    "http_get": 2, "python_snippet": 3, "vector_search": 2,
    "git_status": 1, "git_log": 1, "git_diff": 1, "git_branch": 1,
    "git_commit": 4, "git_push": 5, "git_pull": 3,
    "git_branch_create": 2, "git_checkout": 2,
    "docker_ps": 1, "docker_logs": 2, "docker_restart": 4, "docker_inspect": 1,
    "docker_compose_build": 5, "docker_compose_up": 4, "docker_compose_down": 5,
    "search_in_files": 2, "replace_in_file": 3, "file_create": 2, "file_delete_safe": 3,
    "create_directory": 1, "list_project_structure": 1, "count_lines": 1, "workspace_snapshot": 3,
    "fetch_url": 2, "search_pypi": 2, "fetch_github_readme": 2,
    "http_post_json": 3, "check_url_status": 1, "doc_fetch": 2,
    "run_unit_tests": 4, "run_smoke_tests": 3, "api_healthcheck": 2, "test_endpoint": 2,
    "memory_store_solution": 2, "memory_search_similar": 2,
    "memory_store_error": 2, "memory_store_patch": 2,
    "memory_store_with_ttl": 2, "memory_cleanup_expired": 3,
    "memory_deduplicate": 3, "memory_summarize_recent": 2,
    "check_api_fields": 2, "sync_app_fields": 2,
    "analyze_tool_need": 2, "generate_tool_skeleton": 3, "generate_tool_tests": 3,
    "build_complete_tool": 5,
    "dependency_analyzer": 3, "code_search_multi_file": 2,
    "api_schema_generator": 3, "env_checker": 1, "requirements_validator": 1,
}


def _keyword_overlap(task: str, description: str) -> float:
    """Score de chevauchement de mots-clés entre tâche et description du tool."""
    task_words = set(task.lower().split())
    desc_words = set(description.lower().split())
    if not desc_words:
        return 0.0
    overlap = len(task_words & desc_words)
    return min(1.0, overlap / max(len(desc_words), 1) * 2)


def score_tool_relevance(task: str, tool_name: str, success_history: dict = None) -> float:
    """
    Score de pertinence d'un tool pour une tâche donnée (0.0-1.0).

    Critères:
    - Similarité sémantique (keyword overlap) : base 0.0-1.0
    - Historique de succès : bonus 0.0-0.2
    - Coût estimé : malus 0.0-0.15
    - Nombre de paramètres requis : malus 0.0-0.1
    - Temps moyen d'exécution (timeout) : malus 0.0-0.1 (tools lents pénalisés)
    """
    if success_history is None:
        success_history = {}
    try:
        description = _SEMANTIC_DESCRIPTIONS.get(tool_name, tool_name.replace("_", " "))
        semantic_score = _keyword_overlap(task, description)

        history_bonus = 0.0
        if tool_name in success_history:
            history_bonus = min(float(success_history[tool_name]), 1.0) * 0.2

        cost = _TOOL_COSTS.get(tool_name, 3)
        cost_malus = (cost - 1) / 4 * 0.15

        required_params = _EXECUTOR_REQUIRED_PARAMS.get(tool_name, [])
        param_malus = min(len(required_params) * 0.02, 0.1)

        # Malus basé sur le temps moyen d'exécution (timeout) — tools lents pénalisés
        timeout = _EXECUTOR_TIMEOUTS.get(tool_name, 10)
        timeout_malus = min((timeout - 5) / 120, 0.1) if timeout > 5 else 0.0

        score = semantic_score + history_bonus - cost_malus - param_malus - timeout_malus
        return max(0.0, min(1.0, score))
    except Exception as e:
        logger.debug(f"[REGISTRY] score_tool_relevance error: {e}")
        return 0.0


def rank_tools_for_task(task: str, top_k: int = 5, success_history: dict = None) -> List[dict]:
    """
    Retourne les top_k tools les plus pertinents pour une tâche.
    Chaque entrée: {name, score, description, cost, required_params}
    """
    if success_history is None:
        success_history = {}
    try:
        # Utiliser les tools de l'executor si disponibles, sinon les descriptions connues
        tool_names = list(_EXECUTOR_TOOLS.keys()) if _EXECUTOR_TOOLS else list(_SEMANTIC_DESCRIPTIONS.keys())
        results = []
        for tool_name in tool_names:
            score = score_tool_relevance(task, tool_name, success_history)
            results.append({
                "name": tool_name,
                "score": round(score, 3),
                "description": _SEMANTIC_DESCRIPTIONS.get(tool_name, ""),
                "cost": _TOOL_COSTS.get(tool_name, 3),
                "required_params": _EXECUTOR_REQUIRED_PARAMS.get(tool_name, []),
            })
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]
    except Exception as e:
        logger.debug(f"[REGISTRY] rank_tools_for_task error: {e}")
        return []


def should_create_tool(task: str, success_history: dict = None, recent_failures: list = None) -> dict:
    """
    Détermine si Jarvis doit créer un nouveau tool plutôt qu'utiliser les existants.

    Conditions:
    1. Aucun tool existant avec score > 0.65
    2. La tâche a échoué 2+ fois
    3. Le besoin est identifiable (mots-clés de création/transformation)

    Returns: {should_create, reason, best_existing_score, best_existing_tool, suggested_tool_name}
    """
    if success_history is None:
        success_history = {}
    if recent_failures is None:
        recent_failures = []
    try:
        ranked = rank_tools_for_task(task, top_k=3, success_history=success_history)
        best_score = ranked[0]["score"] if ranked else 0.0

        no_good_tool = best_score < 0.65
        task_prefix = task[:30]
        repeated_failures = len([f for f in recent_failures if task_prefix in str(f)]) >= 2

        creation_keywords = [
            "parse", "connect", "transform", "convert", "extract",
            "generate", "scrape", "validate", "custom", "specific",
        ]
        identifiable_need = any(kw in task.lower() for kw in creation_keywords)

        should_create = no_good_tool and (repeated_failures or identifiable_need)

        if should_create:
            stopwords = {"with", "from", "that", "this", "into", "the", "and", "for", "not"}
            words = [w for w in task.lower().split() if len(w) > 3 and w not in stopwords]
            suggested_name = "_".join(words[:3]) + "_tool" if words else "custom_tool"
        else:
            suggested_name = ""

        return {
            "should_create": should_create,
            "best_existing_score": round(best_score, 3),
            "best_existing_tool": ranked[0]["name"] if ranked else None,
            "reason": (
                f"No tool scores > 0.65 (best: {best_score:.2f}), "
                + ("repeated failures, " if repeated_failures else "")
                + "identifiable need"
                if should_create else
                f"Tool '{ranked[0]['name'] if ranked else 'none'}' sufficient (score: {best_score:.2f})"
            ),
            "suggested_tool_name": suggested_name,
        }
    except Exception as e:
        return {
            "should_create": False,
            "reason": f"error: {e}",
            "best_existing_score": 0.0,
            "best_existing_tool": None,
            "suggested_tool_name": "",
        }


def list_all_tools() -> List[dict]:
    """Liste tous les tools avec leurs métadonnées."""
    try:
        tool_names = list(_EXECUTOR_TOOLS.keys()) if _EXECUTOR_TOOLS else list(_SEMANTIC_DESCRIPTIONS.keys())
        return [
            {
                "name": name,
                "description": _SEMANTIC_DESCRIPTIONS.get(name, ""),
                "cost": _TOOL_COSTS.get(name, 3),
                "timeout": _EXECUTOR_TIMEOUTS.get(name, 10),
                "required_params": _EXECUTOR_REQUIRED_PARAMS.get(name, []),
            }
            for name in tool_names
        ]
    except Exception as e:
        logger.debug(f"[REGISTRY] list_all_tools error: {e}")
        return []
