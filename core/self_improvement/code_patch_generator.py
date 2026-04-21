"""
core/self_improvement/code_patch_generator.py — LLM-based code patch generation.

Uses the configured LLM (self_improvement_model) to generate unified diffs
from a problem description + current file content.

Output contract:
  - unified diff (--- a/file\n+++ b/file\n@@...) or empty string if no change
  - changed_files: list of relative paths touched
  - risk_level: "LOW" | "MEDIUM" | "HIGH"
  - explanation: human-readable rationale

Security:
  - NEVER generates patches for PROTECTED_FILES or PROTECTED_DIRS
  - Input sanitized before injection into prompt (sanitize_user_input)
"""
from __future__ import annotations

import structlog
import re
import textwrap
from dataclasses import dataclass, field

log = structlog.get_logger()

from core.self_improvement.protected_paths import PROTECTED_FILES, PROTECTED_DIRS


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class PatchRequest:
    """Input to the code patch generator."""
    problem_description: str        # What is wrong / what to improve
    target_file: str                # Relative path to file to patch
    current_content: str            # Current file content
    context: str = ""               # Optional: weakness context, test output, etc.
    max_lines_changed: int = 150    # Limit to keep patches reviewable


@dataclass
class GeneratedPatch:
    """Output from the code patch generator."""
    unified_diff: str               # Unified diff string or "" if nothing changed
    changed_files: list[str] = field(default_factory=list)
    risk_level: str = "MEDIUM"      # LOW | MEDIUM | HIGH
    explanation: str = ""
    tokens_used: int = 0
    model_used: str = ""
    success: bool = False
    error: str = ""


# ── Protected file check ──────────────────────────────────────────────────────

def _is_protected(relative_path: str) -> bool:
    """Returns True if the path matches any protected file or directory."""
    normalized = relative_path.replace("\\", "/")
    for protected_dir in PROTECTED_DIRS:
        if normalized.startswith(protected_dir) or f"/{protected_dir}" in normalized:
            return True
    for protected_file in PROTECTED_FILES:
        if normalized.endswith(protected_file) or protected_file in normalized:
            return True
    return False


# ── Prompt builder ────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = textwrap.dedent("""
You are an expert Python software engineer performing a controlled self-improvement patch.
Your task is to generate a minimal, surgical unified diff to fix or improve the target file.

Rules:
1. Output ONLY a valid unified diff (--- a/... +++ b/... @@ format). No prose before or after.
2. The diff must be minimal — only change what is needed to fix the stated problem.
3. Do NOT change public APIs, function signatures, or class names unless strictly required.
4. Do NOT touch security controls, authentication logic, or protected modules.
5. Keep the change under {max_lines} lines total (additions + deletions).
6. After the diff, output exactly one line: RISK: LOW|MEDIUM|HIGH
7. Then output one line starting with EXPLANATION: followed by a brief rationale (1-2 sentences).

If no change is needed, output: NO_CHANGE_NEEDED

Example output format:
--- a/core/some_module.py
+++ b/core/some_module.py
@@ -42,7 +42,8 @@
     def run(self):
-        result = self._execute()
+        result = self._execute()
+        log.debug("execution complete", result=result)
         return result
RISK: LOW
EXPLANATION: Added debug logging to help diagnose execution issues without changing behavior.
""").strip()


_USER_PROMPT_TEMPLATE = textwrap.dedent("""
FILE: {target_file}
PROBLEM: {problem_description}
{context_section}
CURRENT CONTENT:
```python
{current_content}
```

Generate the unified diff now.
""").strip()


# ── Diff extraction ───────────────────────────────────────────────────────────

_DIFF_RE = re.compile(
    r"(---\s+a/\S+.*?(?=\nRISK:|\Z))",
    re.DOTALL,
)
_RISK_RE = re.compile(r"RISK:\s*(LOW|MEDIUM|HIGH)", re.I)
_EXPLANATION_RE = re.compile(r"EXPLANATION:\s*(.+)", re.I)
_CHANGED_FILE_RE = re.compile(r"^\+\+\+\s+b/(\S+)", re.MULTILINE)


def _parse_llm_response(raw: str, target_file: str) -> tuple[str, str, str]:
    """Parse LLM response → (unified_diff, risk_level, explanation)."""
    raw = raw.strip()

    if "NO_CHANGE_NEEDED" in raw:
        return "", "LOW", "No change needed."

    # Extract diff block
    diff_match = _DIFF_RE.search(raw)
    diff = diff_match.group(1).strip() if diff_match else ""

    # If no proper diff header found but there's @@ content, try simpler extraction
    if not diff and "@@" in raw:
        lines = []
        in_diff = False
        for line in raw.splitlines():
            if line.startswith("---") or line.startswith("+++") or line.startswith("@@"):
                in_diff = True
            if in_diff and not line.startswith("RISK:") and not line.startswith("EXPLANATION:"):
                lines.append(line)
        diff = "\n".join(lines).strip()

    risk_match = _RISK_RE.search(raw)
    risk = risk_match.group(1).upper() if risk_match else "MEDIUM"

    explanation_match = _EXPLANATION_RE.search(raw)
    explanation = explanation_match.group(1).strip() if explanation_match else ""

    return diff, risk, explanation


# ── Main generator ────────────────────────────────────────────────────────────

class CodePatchGenerator:
    """
    Generates code patches using the configured LLM.
    Uses self_improvement_model from settings (default: anthropic/claude-sonnet-4.5).
    """

    def generate(self, request: PatchRequest) -> GeneratedPatch:
        """
        Generate a patch for the given request.

        Security guard: raises ValueError if target_file is protected.
        Returns GeneratedPatch with success=False on LLM error.
        """
        # Security check
        if _is_protected(request.target_file):
            log.warning("code_patch_blocked_protected_file", file=request.target_file)
            return GeneratedPatch(
                unified_diff="",
                success=False,
                error=f"Protected file — cannot generate patch for: {request.target_file}",
            )

        # Sanitize inputs
        try:
            from core.security.input_sanitizer import sanitize_user_input
            problem = sanitize_user_input(request.problem_description, strict=False).value
            context_raw = sanitize_user_input(request.context, strict=False).value if request.context else ""
        except Exception:
            problem = request.problem_description[:2000]
            context_raw = request.context[:1000] if request.context else ""

        # Build prompt
        context_section = f"CONTEXT:\n{context_raw}\n" if context_raw else ""
        system_prompt = _SYSTEM_PROMPT.replace("{max_lines}", str(request.max_lines_changed))

        # Truncate current content to avoid token overflow
        content = request.current_content
        if len(content) > 8000:
            content = content[:8000] + "\n# ... [truncated for brevity] ..."

        user_prompt = _USER_PROMPT_TEMPLATE.format(
            target_file=request.target_file,
            problem_description=problem,
            context_section=context_section,
            current_content=content,
        )

        # Call LLM
        try:
            from config.settings import get_settings
            settings = get_settings()
            llm = settings.get_llm("self_improvement")
        except Exception as exc:
            log.error("code_patch_llm_unavailable", err=str(exc))
            return GeneratedPatch(
                unified_diff="",
                success=False,
                error=f"LLM unavailable: {exc}",
            )

        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]
            response = llm.invoke(messages)
            raw_text = response.content if hasattr(response, "content") else str(response)
        except Exception as exc:
            log.error("code_patch_llm_error", err=str(exc)[:120])
            return GeneratedPatch(
                unified_diff="",
                success=False,
                error=f"LLM call failed: {exc}",
            )

        # Parse response
        unified_diff, risk_level, explanation = _parse_llm_response(raw_text, request.target_file)

        # Extract changed files from diff
        changed_files = list(set(_CHANGED_FILE_RE.findall(unified_diff)))
        if not changed_files and unified_diff:
            changed_files = [request.target_file]

        log.info(
            "code_patch_generated",
            file=request.target_file,
            risk=risk_level,
            has_diff=bool(unified_diff),
        )

        return GeneratedPatch(
            unified_diff=unified_diff,
            changed_files=changed_files,
            risk_level=risk_level,
            explanation=explanation,
            success=True,
            model_used=getattr(settings, "self_improvement_model", "unknown"),
        )


# ── Singleton ──────────────────────────────────────────────────────────────────

_generator: CodePatchGenerator | None = None


def get_code_patch_generator() -> CodePatchGenerator:
    global _generator
    if _generator is None:
        _generator = CodePatchGenerator()
    return _generator
