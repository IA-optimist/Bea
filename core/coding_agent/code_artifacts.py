"""Code artifact helpers for forge-builder style missions.

These helpers turn a textual model response into a real Python source file,
while refusing to materialize Markdown prose as executable code.
"""
from __future__ import annotations

import py_compile
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class PythonArtifactResult:
    ok: bool
    status: str
    message: str
    source: str = ""
    syntax_error: str = ""
    path: str = ""
    selected_block: str = ""
    warnings: list[str] = field(default_factory=list)


_FENCE_RE = re.compile(
    r"```(?P<label>[A-Za-z0-9_+\-]*)\s*\n(?P<body>.*?)```",
    re.DOTALL,
)

_MARKDOWN_HINTS = ("### ", "## ", "- ", "* ", "> ", "](", "---")


def extract_python_source(text: str) -> str:
    """Return the best Python source candidate from a model response."""
    candidate = _select_python_candidate(text)
    if candidate and _compiles(candidate):
        return candidate
    return ""


def materialize_python_artifact(
    response_text: str,
    target_path: str | Path,
) -> PythonArtifactResult:
    """Write an extracted Python artifact to disk and validate its syntax."""
    target = Path(target_path)
    source = _select_python_candidate(response_text)
    if not source:
        return PythonArtifactResult(
            ok=False,
            status="NEEDS_ACTION_OUTPUT",
            message="no exploitable Python block was found in the model response",
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8")
    syntax_ok, syntax_error = validate_python_file(target)
    if not syntax_ok:
        return PythonArtifactResult(
            ok=False,
            status="FAILED",
            message="materialized Python file failed syntax validation",
            source=source,
            syntax_error=syntax_error,
            path=str(target),
        )

    return PythonArtifactResult(
        ok=True,
        status="COMPLETED",
        message="Python artifact materialized successfully",
        source=source,
        path=str(target),
    )


def validate_python_file(path: str | Path) -> tuple[bool, str]:
    """Run py_compile on a Python file and return (ok, error_message)."""
    py_path = Path(path)
    try:
        py_compile.compile(str(py_path), doraise=True)
        return True, ""
    except py_compile.PyCompileError as exc:
        return False, str(exc)[:400]


def validate_python_source(source: str, *, filename: str = "<artifact>") -> tuple[bool, str]:
    """Validate Python source without keeping a temp file around."""
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as handle:
        tmp = Path(handle.name)
        handle.write(source)
    try:
        return validate_python_file(tmp)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def _clean_candidate(text: str) -> str:
    stripped = (text or "").strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return stripped.strip()


def _looks_like_python(text: str) -> bool:
    lower = text.lower()
    if any(
        line.lstrip().startswith(hint)
        for line in text.splitlines()
        for hint in ("### ", "## ", "- ", "* ", "> ")
    ):
        return False
    if any(hint in text for hint in ("```", "---")):
        return False
    return any(keyword in lower for keyword in ("def ", "class ", "import ", "from ", "return "))


def _select_python_candidate(text: str) -> str:
    candidates: list[tuple[int, int, str]] = []
    for idx, match in enumerate(_FENCE_RE.finditer(text or "")):
        label = (match.group("label") or "").strip().lower()
        body = _clean_candidate(match.group("body"))
        if not body:
            continue
        score = 1
        if label in {"py", "python", "python3"} or "python" in label:
            score += 10
        if _compiles(body):
            score += 100
        candidates.append((score, idx, body))

    if candidates:
        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return candidates[0][2]

    plain = _clean_candidate(text)
    if plain and _looks_like_python(plain):
        return plain
    return ""


def _compiles(source: str) -> bool:
    try:
        compile(source, "<artifact>", "exec")
        return True
    except SyntaxError:
        return False
