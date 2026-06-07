"""
core/self_improvement/codebase_awareness.py — Codebase understanding before modification.

Analyzes the repository to understand context, patterns, dependencies,
and conventions before any modification is proposed.

Design:
  - Reads before acting: maps affected modules and their callers
  - Pattern detection: identifies naming, typing, logging, error handling conventions
  - Dependency mapping: finds imports and reverse-imports for any file
  - Duplication check: detects if an abstraction already exists before creating a new one
  - Boundary detection: identifies which architectural layer a file belongs to
  - All operations are read-only and side-effect free
"""
from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
import structlog

log = structlog.get_logger("self_improvement.codebase_awareness")

# Architectural layers and their directory boundaries
ARCHITECTURE_LAYERS = {
    "kernel": ["kernel/"],
    "core": ["core/"],
    "execution": ["executor/"],
    "planning": ["core/planning/"],
    "api": ["api/"],
    "business": ["business/", "core/business/"],
    "ui": ["static/", "beamax_app/"],
    "test": ["tests/"],
    "config": ["config/"],
    "connector": ["connectors/"],
}


@dataclass
class ModuleContext:
    """Understanding of a module before modification."""
    path: str
    layer: str = ""
    imports: list[str] = field(default_factory=list)
    imported_by: list[str] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    patterns: dict = field(default_factory=dict)  # detected conventions
    line_count: int = 0
    complexity: str = ""  # low, medium, high

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "layer": self.layer,
            "imports": self.imports[:20],
            "imported_by": self.imported_by[:20],
            "classes": self.classes,
            "functions": self.functions[:20],
            "patterns": self.patterns,
            "line_count": self.line_count,
            "complexity": self.complexity,
        }


@dataclass
class ImpactAnalysis:
    """Analysis of what a modification would affect."""
    target_file: str
    direct_dependents: list[str] = field(default_factory=list)
    indirect_dependents: list[str] = field(default_factory=list)
    affected_tests: list[str] = field(default_factory=list)
    affected_layers: list[str] = field(default_factory=list)
    risk_level: str = "low"  # low, medium, high
    cross_boundary: bool = False
    existing_abstractions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "target_file": self.target_file,
            "direct_dependents": self.direct_dependents,
            "indirect_dependents": self.indirect_dependents[:10],
            "affected_tests": self.affected_tests,
            "affected_layers": self.affected_layers,
            "risk_level": self.risk_level,
            "cross_boundary": self.cross_boundary,
            "existing_abstractions": self.existing_abstractions,
            "warnings": self.warnings,
        }


class CodebaseAwareness:
    """
    Read-only codebase analysis for informed modification decisions.

    Must be called BEFORE any code change to understand context.
    """

    def __init__(self, repo_root: str | Path = "."):
        self._root = Path(repo_root)
        self._import_cache: dict[str, list[str]] | None = None

    def analyze_module(self, filepath: str) -> ModuleContext:
        """
        Deep analysis of a single module.

        Returns ModuleContext with layer, imports, dependents, patterns.
        """
        path = Path(filepath)
        ctx = ModuleContext(path=filepath)

        # Determine architectural layer
        ctx.layer = self._classify_layer(filepath)

        # Read and parse
        try:
            full_path = self._root / filepath if not path.is_absolute() else path
            content = full_path.read_text(errors="replace")
            ctx.line_count = content.count("\n") + 1
        except Exception:
            return ctx

        # AST analysis
        try:
            tree = ast.parse(content)
            ctx.imports = self._extract_imports(tree)
            ctx.classes = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
            ctx.functions = [n.name for n in ast.walk(tree)
                          if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                          and not n.name.startswith("_")]
        except SyntaxError:
            ctx.patterns["parse_error"] = True

        # Find who imports this module
        module_name = self._path_to_module(filepath)
        if module_name:
            ctx.imported_by = self._find_importers(module_name)

        # Detect patterns
        ctx.patterns = self._detect_patterns(content)

        # Complexity estimate
        if ctx.line_count < 100:
            ctx.complexity = "low"
        elif ctx.line_count < 400:
            ctx.complexity = "medium"
        else:
            ctx.complexity = "high"

        return ctx

    def analyze_impact(self, filepath: str) -> ImpactAnalysis:
        """
        Analyze the impact of modifying a file.

        Returns which files depend on it, which tests cover it,
        and what risk level the modification carries.
        """
        analysis = ImpactAnalysis(target_file=filepath)

        # Get module context
        ctx = self.analyze_module(filepath)

        # Direct dependents
        analysis.direct_dependents = ctx.imported_by

        # Find tests that import this module
        module_name = self._path_to_module(filepath)
        if module_name:
            analysis.affected_tests = [
                f for f in self._find_importers(module_name)
                if f.startswith("tests/") or "/test_" in f
            ]

        # Affected layers
        target_layer = ctx.layer
        analysis.affected_layers = [target_layer]
        for dep in analysis.direct_dependents:
            dep_layer = self._classify_layer(dep)
            if dep_layer and dep_layer not in analysis.affected_layers:
                analysis.affected_layers.append(dep_layer)
                if dep_layer != target_layer:
                    analysis.cross_boundary = True

        # Risk assessment
        risk_factors = 0
        if len(analysis.direct_dependents) > 10:
            risk_factors += 2
            analysis.warnings.append(f"High fan-out: {len(analysis.direct_dependents)} direct dependents")
        elif len(analysis.direct_dependents) > 3:
            risk_factors += 1
        if analysis.cross_boundary:
            risk_factors += 1
            analysis.warnings.append("Cross-boundary: affects multiple architectural layers")
        if ctx.line_count > 500:
            risk_factors += 1
            analysis.warnings.append(f"Complex file: {ctx.line_count} lines")
        if ctx.layer == "kernel":
            risk_factors += 2
            analysis.warnings.append("Kernel modification: highest stability requirement")
        if ctx.layer == "api":
            risk_factors += 1
            analysis.warnings.append("API modification: may affect external consumers")

        if risk_factors >= 4:
            analysis.risk_level = "high"
        elif risk_factors >= 2:
            analysis.risk_level = "medium"
        else:
            analysis.risk_level = "low"

        return analysis

    def find_existing_abstractions(self, concept: str) -> list[str]:
        """
        Search for existing abstractions matching a concept.

        Prevents creating duplicate abstractions.
        """
        results: list[str] = []
        concept_lower = concept.lower()
        keywords = set(concept_lower.split())

        for py_file in self._iter_python_files():
            filename = py_file.stem.lower()
            # Check filename match
            if any(kw in filename for kw in keywords if len(kw) > 3):
                results.append(str(py_file.relative_to(self._root)))

        return results[:20]

    def check_consistency(self, filepath: str, proposed_content: str) -> list[str]:
        """
        Check if proposed content is consistent with repo conventions.

        Returns list of consistency warnings.
        """
        warnings: list[str] = []

        # Get patterns from neighboring files
        parent = Path(filepath).parent
        sibling_patterns: list[dict] = []
        for sibling in self._iter_python_files():
            if str(sibling.parent) == str(self._root / parent) and str(sibling) != filepath:
                try:
                    content = sibling.read_text(errors="replace")
                    sibling_patterns.append(self._detect_patterns(content))
                except Exception as _exc:
                    log.warning("swallowed_exception", action="codebase_awareness_1", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

        if not sibling_patterns:
            return warnings

        proposed_patterns = self._detect_patterns(proposed_content)

        # Check logging convention
        sibling_log_styles = set()
        for sp in sibling_patterns:
            if sp.get("log_style"):
                sibling_log_styles.add(sp["log_style"])

        if sibling_log_styles and proposed_patterns.get("log_style"):
            if proposed_patterns["log_style"] not in sibling_log_styles:
                warnings.append(
                    f"Logging style mismatch: you use '{proposed_patterns['log_style']}' "
                    f"but siblings use {sibling_log_styles}"
                )

        # Check typing convention
        sibling_uses_annotations = any(sp.get("type_annotations") for sp in sibling_patterns)
        if sibling_uses_annotations and not proposed_patterns.get("type_annotations"):
            warnings.append("Missing type annotations: siblings use them")

        # Check docstring convention
        sibling_has_docstrings = any(sp.get("has_docstrings") for sp in sibling_patterns)
        if sibling_has_docstrings and not proposed_patterns.get("has_docstrings"):
            warnings.append("Missing docstrings: siblings have them")

        # Check error handling
        sibling_has_failopen = any(sp.get("fail_open") for sp in sibling_patterns)
        if sibling_has_failopen and not proposed_patterns.get("fail_open"):
            warnings.append("Missing fail-open pattern: siblings use try/except pass")

        return warnings

    # ── Private helpers ────────────────────────────────────────

    def _classify_layer(self, filepath: str) -> str:
        """Determine which architectural layer a file belongs to.

        Checks most specific prefixes first (longest match wins).
        """
        best_layer = "other"
        best_len = 0
        for layer, prefixes in ARCHITECTURE_LAYERS.items():
            for prefix in prefixes:
                if filepath.startswith(prefix) and len(prefix) > best_len:
                    best_layer = layer
                    best_len = len(prefix)
        return best_layer

    def _path_to_module(self, filepath: str) -> str:
        """Convert file path to Python module name."""
        if filepath.endswith(".py"):
            return filepath[:-3].replace("/", ".").replace("\\", ".")
        return ""

    def _extract_imports(self, tree: ast.AST) -> list[str]:
        """Extract import module names from AST."""
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)
        return imports

    def _find_importers(self, module_name: str) -> list[str]:
        """Find all files that import a given module."""
        if self._import_cache is None:
            self._build_import_cache()

        results = []
        for filepath, imports in (self._import_cache or {}).items():
            if module_name in imports or any(module_name.startswith(i) or i.startswith(module_name) for i in imports):
                results.append(filepath)
        return results

    def _build_import_cache(self) -> None:
        """Build reverse import index for the entire repo."""
        self._import_cache = {}
        for py_file in self._iter_python_files():
            rel = str(py_file.relative_to(self._root))
            try:
                content = py_file.read_text(errors="replace")
                tree = ast.parse(content)
                imports = self._extract_imports(tree)
                self._import_cache[rel] = imports
            except Exception as _exc:
                log.warning("swallowed_exception", action="codebase_awareness_2", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    def _iter_python_files(self):
        """Iterate all Python files in repo, excluding venv/cache."""
        skip = {".git", "__pycache__", "venv", ".venv", "node_modules", ".tox"}
        for root, dirs, files in os.walk(self._root):
            dirs[:] = [d for d in dirs if d not in skip]
            for f in files:
                if f.endswith(".py"):
                    yield Path(root) / f

    def _detect_patterns(self, content: str) -> dict:
        """Detect coding patterns in content."""
        patterns = {}

        # Logging style
        if "structlog" in content:
            patterns["log_style"] = "structlog"
        elif "logging.getLogger" in content:
            patterns["log_style"] = "stdlib"

        # Type annotations
        patterns["type_annotations"] = bool(re.search(r"def \w+\([^)]*:\s*\w+", content))

        # Docstrings
        patterns["has_docstrings"] = bool(re.search(r'"""[^"]+"""', content))

        # Fail-open pattern
        patterns["fail_open"] = "except Exception" in content and "pass" in content

        # Dataclass usage
        patterns["uses_dataclass"] = "@dataclass" in content

        # Singleton pattern
        patterns["has_singleton"] = bool(re.search(r"^_\w+:\s*\w+\s*\|\s*None\s*=\s*None", content, re.MULTILINE))

        return patterns


@dataclass
class ChangeClassification:
    """Classification of a proposed modification."""
    risk_level: str       # safe, moderate, high
    category: str         # fix, refactor, feature, optimization
    scope: str            # local, module, cross-module
    reversible: bool
    justification: str = ""
    affected_files: list[str] = field(default_factory=list)
    pre_conditions: list[str] = field(default_factory=list)  # what must be true before applying
    post_conditions: list[str] = field(default_factory=list)  # what must be true after applying

    def to_dict(self) -> dict:
        return {
            "risk_level": self.risk_level,
            "category": self.category,
            "scope": self.scope,
            "reversible": self.reversible,
            "justification": self.justification,
            "affected_files": self.affected_files,
            "pre_conditions": self.pre_conditions,
            "post_conditions": self.post_conditions,
        }


def classify_change(
    target_files: list[str],
    lines_changed: int,
    description: str,
    repo_root: str = ".",
) -> ChangeClassification:
    """
    Classify a proposed code change by risk and scope.

    Uses codebase analysis to determine risk level.
    """
    awareness = CodebaseAwareness(repo_root)

    # Scope
    if len(target_files) == 1:
        scope = "local"
    elif len(target_files) <= 3:
        scope = "module"
    else:
        scope = "cross-module"

    # Category detection from description
    desc_lower = description.lower()
    if any(w in desc_lower for w in ["fix", "bug", "crash", "error", "broken"]):
        category = "fix"
    elif any(w in desc_lower for w in ["refactor", "rename", "move", "reorganize"]):
        category = "refactor"
    elif any(w in desc_lower for w in ["optimize", "speed", "performance", "cache"]):
        category = "optimization"
    else:
        category = "feature"

    # Risk analysis
    risk_factors = 0
    warnings = []
    affected = []
    for f in target_files:
        impact = awareness.analyze_impact(f)
        affected.extend(impact.direct_dependents)
        warnings.extend(impact.warnings)
        if impact.risk_level == "high":
            risk_factors += 2
        elif impact.risk_level == "medium":
            risk_factors += 1

    if lines_changed > 200:
        risk_factors += 1
    if scope == "cross-module":
        risk_factors += 1

    if risk_factors >= 3:
        risk_level = "high"
    elif risk_factors >= 1:
        risk_level = "moderate"
    else:
        risk_level = "safe"

    # Reversibility
    reversible = lines_changed < 100 and len(target_files) <= 3

    return ChangeClassification(
        risk_level=risk_level,
        category=category,
        scope=scope,
        reversible=reversible,
        justification=description,
        affected_files=list(set(affected))[:20],
        pre_conditions=[f"Tests pass for: {', '.join(target_files[:5])}"],
        post_conditions=["All existing tests still pass", "No new import errors"],
    )


@dataclass
class ChangeReport:
    """Structured report of a completed modification."""
    change_id: str = ""
    description: str = ""
    files_modified: list[str] = field(default_factory=list)
    lines_added: int = 0
    lines_removed: int = 0
    classification: dict = field(default_factory=dict)
    impact: dict = field(default_factory=dict)
    consistency_warnings: list[str] = field(default_factory=list)
    tests_affected: list[str] = field(default_factory=list)
    tests_passed: bool = False
    follow_up: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "change_id": self.change_id,
            "what": self.description,
            "why": self.classification.get("justification", ""),
            "files": self.files_modified,
            "scope": f"+{self.lines_added}/-{self.lines_removed}",
            "risk": self.classification.get("risk_level", "unknown"),
            "impact": self.impact,
            "consistency_warnings": self.consistency_warnings,
            "tests_affected": self.tests_affected,
            "tests_passed": self.tests_passed,
            "follow_up": self.follow_up,
        }
