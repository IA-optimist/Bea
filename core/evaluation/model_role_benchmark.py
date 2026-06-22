"""
core/evaluation/model_role_benchmark.py

Real-limited model-role benchmark for Béa.

Sends a deterministic prompt to a specific LLM provider and evaluates whether
the response passes the quality bar for the given role.  Designed for one-shot,
role-specific probing — not a full mission through the meta-orchestrator.

Supported roles: forge-builder, scout-research, shadow-advisor.

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
from urllib.parse import urlparse
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# ── Prompts ────────────────────────────────────────────────────────────────

_FORGE_BUILDER_PROMPT = """Tu es un expert Python. Genere:
1. Un fichier sha256_file.py avec une fonction sha256_file(path: str) -> str qui lit le fichier par chunks de 8192 bytes et retourne le SHA256 hexadecimal.
2. Un fichier test_sha256_file.py avec un test def test_sha256_file() utilisant un fichier temporaire.

Format exact:
=== sha256_file.py ===
<code here>
=== test_sha256_file.py ===
<code here>"""

_FORGE_BUILDER_PROMPT_LOCAL = """Python expert. Generate two files:
=== sha256_file.py ===
# Write sha256_file(path: str) -> str that reads file in 8192-byte chunks and returns hex sha256
=== test_sha256_file.py ===
# Write def test_sha256_file() using a tempfile

Reply with ONLY the code, keeping the === markers."""

_SCOUT_RESEARCH_PROMPT_TEMPLATE = """\
Analyse les risques restants de l'alpha Bea a partir du contenu suivant.
Retourne une synthese structuree avec exactement ces trois sections:
- blockers: liste des bloquants critiques
- degraded_risks: liste des risques degrades non bloquants
- recommended_next_action: action recommandee prioritaire (1 phrase)

Contenu a analyser:
{doc_content}

Reponds avec une analyse structuree claire. Cite les elements du document fourni."""

_SHADOW_ADVISOR_PROMPT = """\
Tu dois retourner uniquement un JSON valide (sans markdown, sans texte autour) \
avec exactement ces champs:
{
  "risk_level": "low|medium|high",
  "blockers": ["..."],
  "degraded_risks": ["..."],
  "recommended_next_action": "...",
  "confidence": 0.0
}
Reponds uniquement avec le JSON, sans aucun texte avant ou apres."""

_SHADOW_ADVISOR_SCHEMA_KEYS = frozenset(
    {"risk_level", "blockers", "degraded_risks", "recommended_next_action", "confidence"}
)

# ── Provider defaults ───────────────────────────────────────────────────────

_OPENROUTER_BASE = "https://openrouter.ai/api/v1"
_OPENROUTER_DEFAULT_MODEL = "openai/gpt-oss-120b:free"
_OLLAMA_BASE = "http://127.0.0.1:11434"
_OLLAMA_DEFAULT_MODEL = "gemma4:12b"

_PROVIDER_TIMEOUT = 90  # seconds per provider attempt

_ALPHA_READINESS_PATH = Path(__file__).resolve().parent.parent.parent / "docs" / "ALPHA_READINESS.md"


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
    fallback_used: bool
    error_category: str | None
    # provider availability
    skipped: bool = False
    skip_reason: str | None = None
    # forge-builder specific
    artifact_ok: bool | None = None
    syntax_valid: bool | None = None
    test_proof: bool | None = None
    # scout-research specific
    structured_output: bool | None = None
    timeout: bool | None = None
    local_docs_used: bool | None = None
    # shadow-advisor specific
    json_valid: bool | None = None
    schema_valid: bool | None = None
    retry_count: int | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        # Remove None-valued role-specific fields so output is clean per role
        _role_fields = {
            "forge-builder": {"artifact_ok", "syntax_valid", "test_proof"},
            "scout-research": {"structured_output", "timeout", "local_docs_used"},
            "shadow-advisor": {"json_valid", "schema_valid", "retry_count"},
        }
        relevant = _role_fields.get(self.role, set())
        all_role_fields = set().union(*_role_fields.values())
        to_remove = {k for k in all_role_fields - relevant if d.get(k) is None}
        for k in to_remove:
            d.pop(k, None)
        return d


# ── Forge-builder scoring ────────────────────────────────────────────────────

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
    lines = text.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines)


def _extract_python_blocks(text: str) -> list[str]:
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


# ── Scout-research scoring ────────────────────────────────────────────────────

def score_scout_research(response_text: str, *, timed_out: bool = False) -> dict[str, Any]:
    """
    Evaluate a scout-research LLM response.

    Returns: structured_output, timeout, no_timeout, useful_answer, score, error_category.
    """
    no_timeout = not timed_out
    useful_answer = bool(
        response_text
        and len(response_text.strip()) > 50
    )
    # Check for structured sections — either JSON keys or prose headers
    text_lower = response_text.lower()
    structured_output = (
        "blockers" in text_lower
        and "degraded_risk" in text_lower
        and "recommended_next_action" in text_lower
    )
    criteria = [no_timeout, structured_output, useful_answer]
    score = round(sum(criteria) / len(criteria), 4)
    error_category: str | None = "timeout" if timed_out else None
    if not useful_answer and not timed_out:
        error_category = "empty_response"

    return {
        "structured_output": structured_output,
        "timeout": timed_out,
        "no_timeout": no_timeout,
        "useful_answer": useful_answer,
        "score": score,
        "error_category": error_category,
    }


# ── Shadow-advisor scoring ────────────────────────────────────────────────────

def _strip_json_fences(text: str) -> str:
    """Remove markdown code fences around JSON."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _validate_remote_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http/https URLs are allowed")
    if not parsed.netloc:
        raise ValueError("URL must include a host")
    return url


def _urlopen_checked(url_or_request: str | urllib.request.Request, timeout: int):
    raw_url = getattr(url_or_request, "full_url", None) or str(url_or_request)
    _validate_remote_url(raw_url)
    return urllib.request.urlopen(url_or_request, timeout=timeout)  # nosec B310 - URL is validated by _validate_remote_url()


def score_shadow_advisor(response_text: str) -> dict[str, Any]:
    """
    Evaluate a shadow-advisor LLM response expecting raw JSON.

    Returns: json_valid, schema_valid, no_markdown, score, error_category.
    """
    raw = response_text.strip()
    no_markdown = "```" not in raw

    cleaned = _strip_json_fences(raw)
    json_valid = False
    schema_valid = False
    error_category: str | None = None
    parsed: dict | None = None

    try:
        parsed = json.loads(cleaned)
        json_valid = isinstance(parsed, dict)
    except (json.JSONDecodeError, ValueError):
        error_category = "json_invalid"

    if json_valid and parsed is not None:
        missing = _SHADOW_ADVISOR_SCHEMA_KEYS - parsed.keys()
        schema_valid = not missing
        if not schema_valid:
            error_category = f"schema_missing:{','.join(sorted(missing))}"

    if not no_markdown and error_category is None:
        error_category = "markdown_in_response"

    criteria = [json_valid, schema_valid, no_markdown]
    score = round(sum(criteria) / len(criteria), 4)

    return {
        "json_valid": json_valid,
        "schema_valid": schema_valid,
        "no_markdown": no_markdown,
        "score": score,
        "error_category": error_category,
    }


# ── Provider health checks ───────────────────────────────────────────────────

def _check_openrouter(api_key: str, base_url: str = _OPENROUTER_BASE) -> bool:
    if not api_key or len(api_key) < 20:
        return False
    try:
        req = urllib.request.Request(
            f"{base_url.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        _validate_remote_url(base_url)
        with _urlopen_checked(req, timeout=10) as resp:
            return resp.status == 200
    except Exception:  # noqa: BLE001
        return False


def _check_ollama(base_url: str = _OLLAMA_BASE) -> bool:
    try:
        tags_url = _validate_remote_url(f"{base_url.rstrip('/')}/api/tags")
        with _urlopen_checked(tags_url, timeout=5) as resp:
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
    max_tokens: int = 1024,
) -> str:
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
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
    _validate_remote_url(base_url)
    with _urlopen_checked(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode())
    return body["choices"][0]["message"]["content"]


def _call_ollama(
    prompt: str,
    model: str,
    base_url: str = _OLLAMA_BASE,
    timeout: int = _PROVIDER_TIMEOUT,
    max_tokens: int = 2048,
) -> str:
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": max_tokens, "num_ctx": 4096},
    }).encode()
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    _validate_remote_url(base_url)
    with _urlopen_checked(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode())
    return body["message"]["content"]


# ── Role prompt builders ──────────────────────────────────────────────────────

def _forge_builder_prompt(*, local: bool = False) -> str:
    return _FORGE_BUILDER_PROMPT_LOCAL if local else _FORGE_BUILDER_PROMPT


def _scout_research_prompt() -> str:
    try:
        doc_content = _ALPHA_READINESS_PATH.read_text(encoding="utf-8")
    except OSError:
        doc_content = "[docs/ALPHA_READINESS.md not found — use general alpha risk knowledge]"
    return _SCOUT_RESEARCH_PROMPT_TEMPLATE.format(doc_content=doc_content)


def _shadow_advisor_prompt() -> str:
    return _SHADOW_ADVISOR_PROMPT


# ── Role scorers ──────────────────────────────────────────────────────────────

def _score_for_role(role: str, response_text: str, *, timed_out: bool = False) -> dict[str, Any]:
    if role == "forge-builder":
        return score_response(response_text)
    if role == "scout-research":
        return score_scout_research(response_text, timed_out=timed_out)
    if role == "shadow-advisor":
        return score_shadow_advisor(response_text)
    # Unknown role: minimal scoring
    useful = bool(response_text and len(response_text.strip()) > 20)
    return {"score": 1.0 if useful else 0.0, "error_category": None if useful else "empty_response"}


def _result_from_score(
    role: str,
    provider: str,
    model: str,
    ev: dict,
    duration: float,
) -> BenchmarkResult:
    """Build a BenchmarkResult from a role-specific score dict."""
    score = ev.get("score", 0.0)
    success = not ev.get("timeout", False) and bool(
        ev.get("artifact_ok", True) if role == "forge-builder"
        else ev.get("json_valid", True) if role == "shadow-advisor"
        else len(str(ev)) > 0
    )
    # For roles without artifact_ok, success = response obtained and no timeout
    if role == "scout-research":
        success = ev.get("no_timeout", True) and ev.get("useful_answer", False)
    elif role == "shadow-advisor":
        # Got a response, even if invalid JSON
        success = True  # we got a response; passed depends on score

    passed = success and score >= 0.7

    return BenchmarkResult(
        role=role,
        provider_used=provider,
        model_used=model,
        success=success,
        passed=passed,
        score=score,
        duration_s=duration,
        fallback_used=False,
        error_category=ev.get("error_category"),
        # forge-builder
        artifact_ok=ev.get("artifact_ok"),
        syntax_valid=ev.get("syntax_valid"),
        test_proof=ev.get("test_proof"),
        # scout-research
        structured_output=ev.get("structured_output"),
        timeout=ev.get("timeout"),
        local_docs_used=True if role == "scout-research" else None,
        # shadow-advisor
        json_valid=ev.get("json_valid"),
        schema_valid=ev.get("schema_valid"),
        retry_count=1 if role == "shadow-advisor" else None,
    )


# ── Benchmark runners ────────────────────────────────────────────────────────

def _run_openrouter(
    role: str,
    api_key: str,
    model: str = _OPENROUTER_DEFAULT_MODEL,
    base_url: str = _OPENROUTER_BASE,
) -> BenchmarkResult:
    t0 = time.monotonic()
    try:
        prompt = (
            _forge_builder_prompt(local=False) if role == "forge-builder"
            else _scout_research_prompt() if role == "scout-research"
            else _shadow_advisor_prompt()
        )
        # Scout-research may need more tokens for the injected doc + response
        max_tokens = 2048 if role == "scout-research" else 1024
        text = _call_openrouter(prompt, api_key, model, base_url, max_tokens=max_tokens)
        duration = round(time.monotonic() - t0, 2)
        ev = _score_for_role(role, text)
        return _result_from_score(role, "openrouter", model, ev, duration)
    except TimeoutError:
        duration = round(time.monotonic() - t0, 2)
        ev = _score_for_role(role, "", timed_out=True)
        r = _result_from_score(role, "openrouter", model, ev, duration)
        r.error_category = "TimeoutError"
        return r
    except Exception as exc:  # noqa: BLE001
        duration = round(time.monotonic() - t0, 2)
        ev = _score_for_role(role, "", timed_out=False)
        r = _result_from_score(role, "openrouter", model, ev, duration)
        r.success = False
        r.passed = False
        r.score = 0.0
        r.error_category = type(exc).__name__
        return r


def _run_ollama(
    role: str,
    model: str = _OLLAMA_DEFAULT_MODEL,
    base_url: str = _OLLAMA_BASE,
) -> BenchmarkResult:
    t0 = time.monotonic()
    try:
        prompt = (
            _forge_builder_prompt(local=True) if role == "forge-builder"
            else _scout_research_prompt() if role == "scout-research"
            else _shadow_advisor_prompt()
        )
        max_tokens = 2048 if role == "scout-research" else 1024
        text = _call_ollama(prompt, model, base_url, max_tokens=max_tokens)
        duration = round(time.monotonic() - t0, 2)
        ev = _score_for_role(role, text)
        return _result_from_score(role, "ollama", model, ev, duration)
    except TimeoutError:
        duration = round(time.monotonic() - t0, 2)
        ev = _score_for_role(role, "", timed_out=True)
        r = _result_from_score(role, "ollama", model, ev, duration)
        r.error_category = "TimeoutError"
        return r
    except Exception as exc:  # noqa: BLE001
        duration = round(time.monotonic() - t0, 2)
        ev = _score_for_role(role, "", timed_out=False)
        r = _result_from_score(role, "ollama", model, ev, duration)
        r.success = False
        r.passed = False
        r.score = 0.0
        r.error_category = type(exc).__name__
        return r


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

_MOCK_SCOUT_RESPONSE = """\
blockers:
- forge-builder alpha-ready only when artifact extraction gate is active
- older learning_runs.json entries lack provider/model metadata

degraded_risks:
- validator checks presence and test evidence but not semantic correctness
- free-tier model returned by OpenRouter may differ from the model_id sent
- agents_used from bus reflects routing plan, not actual execution

recommended_next_action: Run benchmark multi-role to confirm provider readiness before enabling continuous improvement in production.
"""

_MOCK_SHADOW_RESPONSE = """{
  "risk_level": "medium",
  "blockers": ["forge-builder artifact gate required for code missions"],
  "degraded_risks": ["provider/model tracking incomplete for chat fast-path"],
  "recommended_next_action": "Enable BEA_CONTINUOUS_IMPROVEMENT only after multi-role benchmark confirms providers are stable",
  "confidence": 0.8
}"""


def _mock_result(role: str, provider: str) -> BenchmarkResult:
    if role == "scout-research":
        ev = score_scout_research(_MOCK_SCOUT_RESPONSE)
        return BenchmarkResult(
            role=role,
            provider_used=provider,
            model_used="mock-model",
            success=True,
            passed=ev["score"] >= 0.7,
            score=ev["score"],
            duration_s=0.01,
            fallback_used=False,
            error_category=None,
            structured_output=ev["structured_output"],
            timeout=ev["timeout"],
            local_docs_used=True,
        )
    if role == "shadow-advisor":
        ev = score_shadow_advisor(_MOCK_SHADOW_RESPONSE)
        return BenchmarkResult(
            role=role,
            provider_used=provider,
            model_used="mock-model",
            success=True,
            passed=ev["score"] >= 0.7,
            score=ev["score"],
            duration_s=0.01,
            fallback_used=False,
            error_category=None,
            json_valid=ev["json_valid"],
            schema_valid=ev["schema_valid"],
            retry_count=1,
        )
    # forge-builder default
    ev = score_response(_MOCK_RESPONSE)
    return BenchmarkResult(
        role=role,
        provider_used=provider,
        model_used="mock-model",
        success=True,
        passed=True,
        score=ev["score"],
        duration_s=0.01,
        fallback_used=False,
        error_category=None,
        artifact_ok=ev["artifact_ok"],
        syntax_valid=ev["syntax_valid"],
        test_proof=ev["test_proof"],
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
        fallback_used=False,
        error_category=None,
        skipped=True,
        skip_reason=reason,
    )


# ── Summary builder ──────────────────────────────────────────────────────────

def _build_summary(results: list[dict]) -> dict:
    """Compute best_by_role: highest score per role, ignoring skipped entries."""
    best: dict[str, dict] = {}
    for r in results:
        if r.get("skipped"):
            continue
        role = r["role"]
        if role not in best or r["score"] > best[role]["score"]:
            best[role] = {
                "provider_used": r["provider_used"],
                "model_used": r["model_used"],
                "score": r["score"],
                "passed": r["passed"],
            }
    return {"best_by_role": best}


# ── Public API ───────────────────────────────────────────────────────────────

def run_benchmark(
    role: str = "forge-builder",
    roles: list[str] | None = None,
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
        role: Single role name (for backward compat; overridden by `roles`).
        roles: List of roles to benchmark. If provided, returns multi-role format.
        providers: List of provider ids to test ('openrouter', 'ollama').
        mock: If True, skip real LLM calls and return deterministic mock results.
        openrouter_api_key: OpenRouter API key — NEVER included in return value.
        openrouter_base_url: OpenRouter base URL.
        openrouter_model: Model slug to send to OpenRouter.
        ollama_base_url: Ollama API base URL.
        ollama_model: Ollama model name.

    Returns:
        Single-role: {"mode": ..., "role": ..., "results": [...]}
        Multi-role:  {"mode": ..., "roles": [...], "providers": [...], "results": [...], "summary": {...}}
        No API keys appear anywhere in the returned dict.
    """
    if providers is None:
        providers = ["openrouter", "ollama"]

    mode = "mock" if mock else "real"
    role_list = roles if roles else [role]
    multi_role = bool(roles)
    all_results: list[dict] = []

    # Pre-check providers once (not per role)
    or_available = (
        _check_openrouter(openrouter_api_key, openrouter_base_url)
        if (not mock and "openrouter" in providers)
        else False
    )
    ol_available = (
        _check_ollama(ollama_base_url)
        if (not mock and "ollama" in providers)
        else False
    )

    for r_role in role_list:
        for provider in providers:
            if mock:
                result = _mock_result(r_role, provider)
                all_results.append(result.to_dict())
                continue

            if provider == "openrouter":
                if not or_available:
                    all_results.append(_skipped(r_role, provider, "provider_unavailable").to_dict())
                else:
                    result = _run_openrouter(
                        r_role, openrouter_api_key, openrouter_model, openrouter_base_url
                    )
                    all_results.append(result.to_dict())

            elif provider == "ollama":
                if not ol_available:
                    all_results.append(_skipped(r_role, provider, "provider_unavailable").to_dict())
                else:
                    result = _run_ollama(r_role, ollama_model, ollama_base_url)
                    all_results.append(result.to_dict())

            else:
                all_results.append(
                    _skipped(r_role, provider, f"unknown_provider:{provider}").to_dict()
                )

    if multi_role:
        return {
            "mode": mode,
            "roles": role_list,
            "providers": providers,
            "results": all_results,
            "summary": _build_summary(all_results),
        }
    # Single-role backward-compat format
    return {"mode": mode, "role": role_list[0], "results": all_results}
