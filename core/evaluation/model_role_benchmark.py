"""
core/evaluation/model_role_benchmark.py

Real-limited model-role benchmark for Béa.

Sends a deterministic prompt to a specific LLM provider and evaluates whether
the response passes the forge-builder quality bar.  Designed for one-shot,
role-specific probing — not a full mission through the meta-orchestrator.

Scope: read-only relative to providers.  No router integration.  No API keys
in logs or return values.  An unavailable provider produces a skipped result,
not a failure.
"""
from __future__ import annotations

import ast
import json
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any

# ── Prompts ────────────────────────────────────────────────────────────────

# Used for cloud providers (OpenRouter) which handle Unicode and long prompts well.
_FORGE_BUILDER_PROMPT = """Tu es un expert Python. Genere:
1. Un fichier sha256_file.py avec une fonction sha256_file(path: str) -> str qui lit le fichier par chunks de 8192 bytes et retourne le SHA256 hexadecimal.
2. Un fichier test_sha256_file.py avec un test def test_sha256_file() utilisant un fichier temporaire.

Format exact:
=== sha256_file.py ===
<code here>
=== test_sha256_file.py ===
<code here>"""

# Shorter ASCII-only prompt for local Ollama models to minimize prompt tokens.
_FORGE_BUILDER_PROMPT_LOCAL = """Python expert. Generate two files:
=== sha256_file.py ===
# Write sha256_file(path: str) -> str that reads file in 8192-byte chunks and returns hex sha256
=== test_sha256_file.py ===
# Write def test_sha256_file() using a tempfile

Reply with ONLY the code, keeping the === markers."""

# ── Provider defaults ───────────────────────────────────────────────────────

_OPENROUTER_BASE = "https://openrouter.ai/api/v1"
_OPENROUTER_DEFAULT_MODEL = "openai/gpt-oss-120b:free"
_OLLAMA_BASE = "http://127.0.0.1:11434"
_OLLAMA_DEFAULT_MODEL = "gemma4:12b"

_PROVIDER_TIMEOUT = 90  # seconds per provider attempt


# ── Data types ──────────────────────────────────────────────────────────────

@dataclass
class BenchmarkResult:
    role: str
    provider_used: str
    model_used: str
    success: bool
    passed: bool
    score: float
    duration_s: float
    artifact_ok: bool
    syntax_valid: bool
    test_proof: bool
    fallback_used: bool
    error_category: str | None
    skipped: bool = False
    skip_reason: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


# ── Scoring ─────────────────────────────────────────────────────────────────

def _parse_sections(text: str) -> dict[str, str]:
    """Parse '=== name.py ===\\n<code>' blocks from LLM response."""
    sections: dict[str, str] = {}
    current_name: str | None = None
    current_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("===") and stripped.endswith("===") and ".py" in stripped:
            if current_name:
                sections[current_name] = "\n".join(current_lines).strip()
            current_name = stripped.strip("= ").strip()
            current_lines = []
        else:
            if current_name is not None:
                current_lines.append(line)
    if current_name:
        sections[current_name] = "\n".join(current_lines).strip()
    return sections


def _strip_code_fences(text: str) -> str:
    """Remove leading/trailing markdown code fences."""
    lines = text.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines)


def _extract_python_blocks(text: str) -> list[str]:
    """Extract code from markdown fences (```python ... ```) when sections are absent."""
    blocks: list[str] = []
    lines = text.splitlines()
    in_block = False
    current: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not in_block and stripped.startswith("```"):
            in_block = True
            current = []
        elif in_block and stripped == "```":
            if current:
                blocks.append("\n".join(current))
            in_block = False
            current = []
        elif in_block:
            current.append(line)
    return blocks


def score_response(response_text: str) -> dict[str, Any]:
    """
    Evaluate a forge-builder LLM response for the SHA256 fixture.

    Tries the explicit section format (=== sha256_file.py ===) first; falls
    back to markdown code fences so local models that ignore the format still
    receive partial credit for valid Python code.

    Returns a dict with keys: artifact_ok, syntax_valid, test_proof, score, error_category.
    """
    sections = _parse_sections(response_text)

    artifact_ok = bool(sections.get("sha256_file.py"))
    syntax_valid = False
    test_proof = bool("def test_" in response_text)
    error_category: str | None = None
    src_to_check: str | None = None

    if artifact_ok:
        src_to_check = _strip_code_fences(sections["sha256_file.py"])
    else:
        # Fallback: accept markdown fences that contain sha256_file or sha256
        blocks = _extract_python_blocks(response_text)
        for block in blocks:
            if "sha256_file" in block or ("sha256" in block and "def " in block):
                artifact_ok = True
                src_to_check = block
                break

    if src_to_check is not None:
        try:
            ast.parse(src_to_check)
            syntax_valid = True
        except SyntaxError:
            syntax_valid = False
            error_category = "syntax_error"
    if not artifact_ok:
        error_category = "artifact_invalid"

    criteria = [artifact_ok, syntax_valid, test_proof]
    score = round(sum(criteria) / len(criteria), 4)

    return {
        "artifact_ok": artifact_ok,
        "syntax_valid": syntax_valid,
        "test_proof": test_proof,
        "score": score,
        "error_category": error_category,
    }


# ── Provider health checks ───────────────────────────────────────────────────

def _check_openrouter(api_key: str, base_url: str = _OPENROUTER_BASE) -> bool:
    """Return True if OpenRouter is reachable and the key is accepted."""
    if not api_key or len(api_key) < 20:
        return False
    try:
        req = urllib.request.Request(
            f"{base_url.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception:  # noqa: BLE001
        return False


def _check_ollama(base_url: str = _OLLAMA_BASE) -> bool:
    """Return True if Ollama is reachable."""
    try:
        with urllib.request.urlopen(f"{base_url.rstrip('/')}/api/tags", timeout=5) as resp:
            return resp.status == 200
    except Exception:  # noqa: BLE001
        return False


# ── LLM call helpers ─────────────────────────────────────────────────────────

def _call_openrouter(
    prompt: str,
    api_key: str,
    model: str,
    base_url: str = _OPENROUTER_BASE,
    timeout: int = _PROVIDER_TIMEOUT,
) -> str:
    """POST a chat completion request to OpenRouter, return response text."""
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1024,
        "temperature": 0.2,
    }).encode()
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/IA-optimist/Bea",
            "X-Title": "Bea-Benchmark",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode())
    return body["choices"][0]["message"]["content"]


def _call_ollama(
    prompt: str,
    model: str,
    base_url: str = _OLLAMA_BASE,
    timeout: int = _PROVIDER_TIMEOUT,
) -> str:
    """POST a chat completion request to Ollama, return response text."""
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        # num_predict 2048 to give local models enough room for both files.
        # num_ctx 4096 ensures the prompt + output fit in one context window
        # even for models with a small default (gemma4, mistral-7b etc.).
        "options": {"temperature": 0.2, "num_predict": 2048, "num_ctx": 4096},
    }).encode()
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode())
    return body["message"]["content"]


# ── Benchmark runners ────────────────────────────────────────────────────────

def _run_openrouter(
    role: str,
    api_key: str,
    model: str = _OPENROUTER_DEFAULT_MODEL,
    base_url: str = _OPENROUTER_BASE,
) -> BenchmarkResult:
    t0 = time.monotonic()
    try:
        text = _call_openrouter(_FORGE_BUILDER_PROMPT, api_key, model, base_url)
        duration = round(time.monotonic() - t0, 2)
        ev = score_response(text)
        success = ev["artifact_ok"]
        passed = success and ev["score"] >= 0.7
        return BenchmarkResult(
            role=role,
            provider_used="openrouter",
            model_used=model,
            success=success,
            passed=passed,
            score=ev["score"],
            duration_s=duration,
            artifact_ok=ev["artifact_ok"],
            syntax_valid=ev["syntax_valid"],
            test_proof=ev["test_proof"],
            fallback_used=False,
            error_category=ev["error_category"],
        )
    except Exception as exc:  # noqa: BLE001
        duration = round(time.monotonic() - t0, 2)
        return BenchmarkResult(
            role=role,
            provider_used="openrouter",
            model_used=model,
            success=False,
            passed=False,
            score=0.0,
            duration_s=duration,
            artifact_ok=False,
            syntax_valid=False,
            test_proof=False,
            fallback_used=False,
            error_category=type(exc).__name__,
        )


def _run_ollama(
    role: str,
    model: str = _OLLAMA_DEFAULT_MODEL,
    base_url: str = _OLLAMA_BASE,
) -> BenchmarkResult:
    t0 = time.monotonic()
    try:
        text = _call_ollama(_FORGE_BUILDER_PROMPT_LOCAL, model, base_url)
        duration = round(time.monotonic() - t0, 2)
        ev = score_response(text)
        success = ev["artifact_ok"]
        passed = success and ev["score"] >= 0.7
        return BenchmarkResult(
            role=role,
            provider_used="ollama",
            model_used=model,
            success=success,
            passed=passed,
            score=ev["score"],
            duration_s=duration,
            artifact_ok=ev["artifact_ok"],
            syntax_valid=ev["syntax_valid"],
            test_proof=ev["test_proof"],
            fallback_used=False,
            error_category=ev["error_category"],
        )
    except Exception as exc:  # noqa: BLE001
        duration = round(time.monotonic() - t0, 2)
        return BenchmarkResult(
            role=role,
            provider_used="ollama",
            model_used=model,
            success=False,
            passed=False,
            score=0.0,
            duration_s=duration,
            artifact_ok=False,
            syntax_valid=False,
            test_proof=False,
            fallback_used=False,
            error_category=type(exc).__name__,
        )


# ── Mock mode ────────────────────────────────────────────────────────────────

_MOCK_RESPONSE = """=== sha256_file.py ===
import hashlib

def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()
=== test_sha256_file.py ===
import tempfile, os
from sha256_file import sha256_file

def test_sha256_file():
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(b"hello")
        name = f.name
    try:
        digest = sha256_file(name)
        assert len(digest) == 64
        assert all(c in "0123456789abcdef" for c in digest)
    finally:
        os.unlink(name)
"""


def _mock_result(role: str, provider: str) -> BenchmarkResult:
    ev = score_response(_MOCK_RESPONSE)
    return BenchmarkResult(
        role=role,
        provider_used=provider,
        model_used="mock-model",
        success=True,
        passed=True,
        score=ev["score"],
        duration_s=0.01,
        artifact_ok=ev["artifact_ok"],
        syntax_valid=ev["syntax_valid"],
        test_proof=ev["test_proof"],
        fallback_used=False,
        error_category=None,
    )


def _skipped(role: str, provider: str, reason: str) -> BenchmarkResult:
    return BenchmarkResult(
        role=role,
        provider_used=provider,
        model_used="",
        success=False,
        passed=False,
        score=0.0,
        duration_s=0.0,
        artifact_ok=False,
        syntax_valid=False,
        test_proof=False,
        fallback_used=False,
        error_category=None,
        skipped=True,
        skip_reason=reason,
    )


# ── Public API ───────────────────────────────────────────────────────────────

def run_benchmark(
    role: str = "forge-builder",
    providers: list[str] | None = None,
    mock: bool = False,
    openrouter_api_key: str = "",
    openrouter_base_url: str = _OPENROUTER_BASE,
    openrouter_model: str = _OPENROUTER_DEFAULT_MODEL,
    ollama_base_url: str = _OLLAMA_BASE,
    ollama_model: str = _OLLAMA_DEFAULT_MODEL,
) -> dict:
    """
    Run a limited model-role benchmark.

    Args:
        role: Role name (only 'forge-builder' is currently supported).
        providers: List of provider ids to test ('openrouter', 'ollama').
        mock: If True, skip real LLM calls and return deterministic mock results.
        openrouter_api_key: OpenRouter API key — NEVER included in return value.
        openrouter_base_url: OpenRouter base URL.
        openrouter_model: Model slug to send to OpenRouter.
        ollama_base_url: Ollama API base URL.
        ollama_model: Ollama model name.

    Returns:
        {"mode": "mock"|"real", "role": ..., "results": [...]}
        No API keys appear anywhere in the returned dict.
    """
    if providers is None:
        providers = ["openrouter", "ollama"]

    mode = "mock" if mock else "real"
    results: list[dict] = []

    for provider in providers:
        if mock:
            r = _mock_result(role, provider)
            results.append(r.to_dict())
            continue

        if provider == "openrouter":
            if not _check_openrouter(openrouter_api_key, openrouter_base_url):
                results.append(_skipped(role, provider, "provider_unavailable").to_dict())
            else:
                r = _run_openrouter(role, openrouter_api_key, openrouter_model, openrouter_base_url)
                results.append(r.to_dict())

        elif provider == "ollama":
            if not _check_ollama(ollama_base_url):
                results.append(_skipped(role, provider, "provider_unavailable").to_dict())
            else:
                r = _run_ollama(role, ollama_model, ollama_base_url)
                results.append(r.to_dict())

        else:
            results.append(_skipped(role, provider, f"unknown_provider:{provider}").to_dict())

    return {"mode": mode, "role": role, "results": results}
