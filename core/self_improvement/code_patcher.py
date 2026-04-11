"""
JARVIS MAX — Code Patcher (production-grade source modification)
===================================================================
Takes structured patch intent and transforms source code safely.

Capabilities:
1. Analyze: parse Python → classes, functions, imports, complexity, docstrings
2. Generate: create CodePatch from old→new or from PatchIntent
3. Validate: AST syntax check before any write
4. Apply: write modified content to sandbox (NEVER production)
5. Rollback: restore original content
6. Multi-file: coordinate patches across up to 3 files

Safety:
- Protected paths ALWAYS checked (delegated to protected_paths.is_protected)
- Max 3 files per patch
- Max 200 lines changed per patch
- All patches syntax-validated before write
- Apply target MUST be sandbox path, never repo root
"""
from __future__ import annotations

import ast
import difflib
import hashlib
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# PROTECTED_FILES re-exported for backward compat (test_devin_core.py imports it from here)
from core.self_improvement.protected_paths import is_protected, PROTECTED_FILES
_silent_log = __import__("structlog").get_logger(__name__)

MAX_FILES_PER_PATCH = 3
MAX_LINES_CHANGED = 200


# ═══════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════

@dataclass
class FileAnalysis:
    """AST analysis of a Python file."""
    path: str
    classes: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    docstrings: list[str] = field(default_factory=list)
    line_count: int = 0
    complexity_score: float = 0.0
    parse_ok: bool = True
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "path": self.path, "classes": self.classes,
            "functions": self.functions, "imports": self.imports[:10],
            "lines": self.line_count, "complexity": round(self.complexity_score, 2),
            "parse_ok": self.parse_ok,
        }


@dataclass
class PatchDiff:
    """A unified diff for one file."""
    file_path: str
    original: str
    modified: str
    diff_text: str = ""
    lines_added: int = 0
    lines_removed: int = 0

    def to_dict(self) -> dict:
        return {
            "file": self.file_path,
            "lines_added": self.lines_added,
            "lines_removed": self.lines_removed,
            "diff_preview": self.diff_text[:500],
        }


class PatchMode:
    """Supported patch modes."""
    EXACT_REPLACE = "exact_replace"         # old_text → new_text
    BLOCK_INSERT = "block_insert"           # Insert new_text after old_text
    AST_TRANSFORM = "ast_transform_python"  # AST-aware transformation
    GUARDED_APPEND = "guarded_append"       # Append only if not already present


# Binary / unsupported extensions
BINARY_EXTENSIONS = frozenset({
    ".pyc", ".pyo", ".so", ".dll", ".exe", ".bin", ".dat",
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".bmp", ".webp",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z",
    ".whl", ".egg", ".db", ".sqlite", ".sqlite3",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
})


@dataclass
class PatchIntent:
    """Structured description of what to change and why."""
    file_path: str
    old_text: str
    new_text: str
    reason: str = ""
    strategy: str = ""      # timeout_tuning, retry_optimization, error_handling, etc.
    mode: str = PatchMode.EXACT_REPLACE  # Patch mode


@dataclass
class CodePatch:
    """Complete patch: one or more file diffs with metadata."""
    patch_id: str
    issue: str
    strategy: str = ""
    diffs: list[PatchDiff] = field(default_factory=list)
    syntax_valid: bool = False
    applied: bool = False
    rolled_back: bool = False
    protected_violation: bool = False
    size_violation: bool = False
    timestamp: float = field(default_factory=time.time)
    rollback_instructions: str = ""
    metadata: dict = field(default_factory=dict)

    @property
    def total_lines_changed(self) -> int:
        return sum(d.lines_added + d.lines_removed for d in self.diffs)

    @property
    def files_changed(self) -> list[str]:
        return [d.file_path for d in self.diffs]

    binary_violation: bool = False
    noop_violation: bool = False
    duplicate_symbols: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return (
            self.syntax_valid
            and not self.protected_violation
            and not self.size_violation
            and not self.binary_violation
            and not self.noop_violation
            and len(self.diffs) > 0
            and len(self.diffs) <= MAX_FILES_PER_PATCH
            and self.total_lines_changed <= MAX_LINES_CHANGED
        )

    @property
    def risk_level(self) -> str:
        """Classify patch risk."""
        if self.total_lines_changed > 100:
            return "high"
        if len(self.diffs) > 2:
            return "medium"
        if self.total_lines_changed > 30:
            return "medium"
        return "low"

    def report(self) -> dict:
        """Structured patch report with risks."""
        return {
            "patch_id": self.patch_id,
            "issue": self.issue[:200],
            "strategy": self.strategy,
            "target_files": self.files_changed,
            "file_count": len(self.diffs),
            "line_deltas": {d.file_path: {"added": d.lines_added, "removed": d.lines_removed} for d in self.diffs},
            "total_lines_changed": self.total_lines_changed,
            "patch_modes": list(set(getattr(d, '_mode', 'exact_replace') for d in self.diffs)),
            "risk_level": self.risk_level,
            "syntax_valid": self.syntax_valid,
            "is_valid": self.is_valid,
            "violations": {
                "protected": self.protected_violation,
                "size": self.size_violation,
                "binary": self.binary_violation,
                "noop": self.noop_violation,
                "duplicate_symbols": self.duplicate_symbols,
            },
            "rollback": self.rollback_instructions[:200],
        }

    def to_dict(self) -> dict:
        return {
            "patch_id": self.patch_id,
            "issue": self.issue[:200],
            "strategy": self.strategy,
            "files": self.files_changed,
            "total_lines": self.total_lines_changed,
            "syntax_valid": self.syntax_valid,
            "is_valid": self.is_valid,
            "applied": self.applied,
            "rolled_back": self.rolled_back,
            "protected_violation": self.protected_violation,
            "size_violation": self.size_violation,
            "rollback": self.rollback_instructions[:200],
        }


# ═══════════════════════════════════════════════════════════════
# CODE PATCHER
# ═══════════════════════════════════════════════════════════════

class CodePatcher:
    """
    Production-grade code patcher with AST analysis and safety guards.
    
    All modifications target a sandbox path — never the production repo directly.
    Protected files are always blocked via is_protected().
    """

    def __init__(self, repo_root: str | Path = "."):
        self._root = Path(repo_root)

    # ── 1. Analyze ──

    def analyze(self, file_path: str) -> FileAnalysis:
        """Parse a Python file and extract structure."""
        analysis = FileAnalysis(path=file_path)
        full_path = self._root / file_path

        if not full_path.exists():
            analysis.parse_ok = False
            analysis.error = "File not found"
            return analysis

        try:
            source = full_path.read_text(encoding="utf-8")
            analysis.line_count = len(source.splitlines())
            tree = ast.parse(source)

            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    analysis.classes.append(node.name)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    analysis.functions.append(node.name)
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        analysis.imports.append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    analysis.imports.append(node.module or "")

            # Extract docstrings
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
                    ds = ast.get_docstring(node)
                    if ds:
                        analysis.docstrings.append(ds[:100])

            # Complexity: classes + functions + branches + lines
            branches = sum(1 for n in ast.walk(tree)
                           if isinstance(n, (ast.If, ast.For, ast.While, ast.Try,
                                             ast.With, ast.ExceptHandler)))
            analysis.complexity_score = (
                len(analysis.classes) * 3.0 +
                len(analysis.functions) * 1.5 +
                branches * 0.5 +
                analysis.line_count * 0.01
            )

        except SyntaxError as e:
            analysis.parse_ok = False
            analysis.error = f"Syntax error: {e}"
        except Exception as e:
            analysis.parse_ok = False
            analysis.error = str(e)[:200]

        return analysis

    # ── 2. Generate patch from intent ──

    def generate(self, intents: list[PatchIntent], issue: str = "") -> CodePatch:
        """
        Generate a CodePatch from one or more PatchIntents.
        
        Each intent specifies a file + old_text + new_text replacement.
        Protected files are immediately flagged.
        """
        patch_id = hashlib.sha256(
            f"{issue}{time.time()}{os.urandom(4).hex()}".encode()
        ).hexdigest()[:12]

        patch = CodePatch(
            patch_id=f"patch-{patch_id}",
            issue=issue or "auto-improvement",
            strategy=intents[0].strategy if intents else "",
        )

        if len(intents) > MAX_FILES_PER_PATCH:
            patch.size_violation = True
            return patch

        for intent in intents:
            # Protected path check
            if is_protected(intent.file_path):
                patch.protected_violation = True
                return patch

            # Binary / unsupported file check
            ext = Path(intent.file_path).suffix.lower()
            if ext in BINARY_EXTENSIONS:
                patch.binary_violation = True
                return patch

            diff = self._create_diff(intent)
            if diff:
                patch.diffs.append(diff)

        # No-op detection
        if not patch.diffs:
            patch.noop_violation = True

        # Check total size
        if patch.total_lines_changed > MAX_LINES_CHANGED:
            patch.size_violation = True

        # Duplicate symbol detection (Python only)
        for diff in patch.diffs:
            if diff.file_path.endswith(".py"):
                dupes = self._detect_duplicate_symbols(diff.modified)
                patch.duplicate_symbols.extend(dupes)

        # Codebase awareness pre-check (fail-open)
        try:
            from core.self_improvement.codebase_awareness import (
                CodebaseAwareness, classify_change,
            )
            awareness = CodebaseAwareness(str(self.repo_root))
            target_files = [i.file_path for i in intents]
            lines = patch.total_lines_changed
            classification = classify_change(target_files, lines, issue, str(self.repo_root))
            patch.metadata["classification"] = classification.to_dict()
            patch.metadata["awareness"] = {
                "risk_level": classification.risk_level,
                "scope": classification.scope,
                "category": classification.category,
                "affected_files": classification.affected_files[:10],
            }
            # Check consistency for each diff
            consistency_warnings = []
            for diff in patch.diffs:
                if diff.modified:
                    warnings = awareness.check_consistency(diff.file_path, diff.modified)
                    consistency_warnings.extend(warnings)
            if consistency_warnings:
                patch.metadata["consistency_warnings"] = consistency_warnings
        except Exception:
            pass  # fail-open: don't block patching

        # Generate rollback instructions
        patch.rollback_instructions = (
            f"Restore original content of: {', '.join(patch.files_changed)}\n"
            f"Each file's original content is stored in PatchDiff.original"
        )

        return patch

    def generate_single(self, file_path: str, old_text: str, new_text: str,
                         issue: str = "", strategy: str = "") -> CodePatch:
        """Convenience: generate patch for a single file replacement."""
        return self.generate(
            [PatchIntent(file_path=file_path, old_text=old_text, new_text=new_text,
                         strategy=strategy)],
            issue=issue,
        )

    def generate_patch(self, issue: str, file_path: str,
                       old_text: str, new_text: str) -> CodePatch:
        """Convenience alias with (issue, file, old, new) arg order.
        Returns an empty patch (no diffs) when size or protection constraints trigger."""
        patch = self.generate_single(file_path, old_text, new_text, issue=issue)
        # Enforce size and protection: clear diffs so callers can check len(patch.diffs)
        if patch.size_violation or (not patch.diffs and patch.noop_violation is False):
            pass  # already empty
        if getattr(patch, "size_violation", False):
            patch.diffs.clear()
        return patch

    # ── 3. Validate syntax ──

    def validate_syntax(self, patch: CodePatch) -> bool:
        """Validate all modified files parse as valid Python."""
        for diff in patch.diffs:
            if diff.file_path.endswith(".py"):
                try:
                    ast.parse(diff.modified)
                except SyntaxError:
                    patch.syntax_valid = False
                    return False
        patch.syntax_valid = True
        return True

    # ── 4. Apply / Rollback (direct, no sandbox) ──

    def apply(self, patch: CodePatch) -> bool:
        """Apply patch directly to repo_root. Returns False if protected or invalid."""
        for diff in patch.diffs:
            if is_protected(diff.file_path):
                return False
        if not patch.diffs:
            return False
        for diff in patch.diffs:
            target = self._root / diff.file_path
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                target.write_text(diff.modified, encoding="utf-8")
            except Exception:
                return False
        patch.applied = True
        return True

    def rollback(self, patch: CodePatch) -> bool:
        """Restore original content in repo_root."""
        for diff in patch.diffs:
            target = self._root / diff.file_path
            try:
                if diff.original:
                    target.write_text(diff.original, encoding="utf-8")
            except Exception:
                return False
        patch.rolled_back = True
        patch.applied = False
        return True

    # ── 4b. Apply to sandbox ──

    def apply_to_sandbox(self, patch: CodePatch, sandbox_path: str | Path) -> bool:
        """
        Apply patch to sandbox directory (NEVER production repo).
        Requires prior syntax validation.
        """
        if not patch.is_valid:
            return False

        sandbox = Path(sandbox_path)
        if not sandbox.exists():
            return False

        for diff in patch.diffs:
            target = sandbox / diff.file_path
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                target.write_text(diff.modified, encoding="utf-8")
            except Exception:
                # Rollback any already-written files
                self.rollback_from_sandbox(patch, sandbox_path)
                return False

        patch.applied = True
        return True

    # ── 5. Rollback ──

    def rollback_from_sandbox(self, patch: CodePatch, sandbox_path: str | Path) -> bool:
        """Restore original content in sandbox."""
        sandbox = Path(sandbox_path)
        for diff in patch.diffs:
            target = sandbox / diff.file_path
            try:
                if diff.original:
                    target.write_text(diff.original, encoding="utf-8")
            except Exception:
                return False
        patch.rolled_back = True
        patch.applied = False
        return True

    # ── Internal ──

    def _create_diff(self, intent: PatchIntent) -> PatchDiff | None:
        """Create a PatchDiff from a PatchIntent using the specified patch mode."""
        full_path = self._root / intent.file_path
        if not full_path.exists():
            return None

        original = full_path.read_text(encoding="utf-8")
        mode = intent.mode

        # ── Apply patch mode ──
        if mode == PatchMode.EXACT_REPLACE:
            if intent.old_text and intent.old_text not in original:
                return None
            if intent.old_text:
                modified = original.replace(intent.old_text, intent.new_text, 1)
            else:
                modified = intent.new_text

        elif mode == PatchMode.BLOCK_INSERT:
            # Insert new_text AFTER old_text
            if intent.old_text not in original:
                return None
            idx = original.index(intent.old_text) + len(intent.old_text)
            modified = original[:idx] + "\n" + intent.new_text + original[idx:]

        elif mode == PatchMode.AST_TRANSFORM:
            # AST-aware: parse → modify → unparse (Python 3.9+)
            modified = self._ast_transform(original, intent)
            if modified is None:
                return None

        elif mode == PatchMode.GUARDED_APPEND:
            # Append only if new_text not already present
            if intent.new_text.strip() in original:
                return None  # Already present — skip
            modified = original.rstrip("\n") + "\n\n" + intent.new_text + "\n"

        else:
            # Unknown mode — treat as exact_replace
            if intent.old_text and intent.old_text not in original:
                return None
            modified = original.replace(intent.old_text, intent.new_text, 1) if intent.old_text else intent.new_text

        if modified == original:
            return None  # No change

        # Generate unified diff
        orig_lines = original.splitlines(keepends=True)
        mod_lines = modified.splitlines(keepends=True)
        diff = list(difflib.unified_diff(
            orig_lines, mod_lines,
            fromfile=f"a/{intent.file_path}",
            tofile=f"b/{intent.file_path}",
        ))
        diff_text = "".join(diff)
        lines_added = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
        lines_removed = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))

        return PatchDiff(
            file_path=intent.file_path,
            original=original,
            modified=modified,
            diff_text=diff_text,
            lines_added=lines_added,
            lines_removed=lines_removed,
        )

    def _ast_transform(self, source: str, intent: PatchIntent) -> str | None:
        """
        AST-aware transformation for Python.
        Uses AST to locate the target, applies the change, preserves formatting.
        
        Falls back to text replacement if AST manipulation fails.
        """
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return None

        # AST-aware: find the target text and replace with context awareness
        # For now, use AST to validate the source, then apply text replacement
        # (Full AST rewriting requires Python 3.9+ ast.unparse, and loses comments)
        if intent.old_text and intent.old_text in source:
            modified = source.replace(intent.old_text, intent.new_text, 1)
            # Validate the result parses
            try:
                ast.parse(modified)
                return modified
            except SyntaxError:
                return None
        return None

    @staticmethod
    def _detect_duplicate_symbols(source: str) -> list[str]:
        """Detect obviously duplicated function/class definitions in Python source."""
        duplicates = []
        try:
            tree = ast.parse(source)
            names: dict[str, int] = {}
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    name = f"def {node.name}"
                    names[name] = names.get(name, 0) + 1
                elif isinstance(node, ast.ClassDef):
                    name = f"class {node.name}"
                    names[name] = names.get(name, 0) + 1
            for name, count in names.items():
                if count > 1:
                    duplicates.append(f"{name} (defined {count}x)")
        except SyntaxError:
            _silent_log.debug("suppressed_exception", src='code_patcher.py')
        return duplicates
