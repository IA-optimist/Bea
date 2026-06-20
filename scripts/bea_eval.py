"""bea eval — probe one or more model aliases, report score/latency/cost.

Usage:
  python scripts/bea_eval.py
  python scripts/bea_eval.py gemma4-local gptoss
  python scripts/bea_eval.py gemma4-local --json
  python scripts/bea_eval.py --api http://127.0.0.1:11434/v1 --model gemma4:12b
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

try:
    import httpx
except ImportError:
    print("Missing dependency: pip install httpx", file=sys.stderr)
    sys.exit(1)

# ── Built-in prompt suite ────────────────────────────────────────────────────
DEFAULT_PROMPTS: list[dict] = [
    {
        "id": "P1_reason",
        "domain": "reasoning",
        "prompt": "How many r's are in the word 'strawberry'? Count each one.",
        "expect_keywords": ["3", "three"],
    },
    {
        "id": "P2_code",
        "domain": "coding",
        "prompt": "Write a Python one-liner that flattens a list of lists.",
        "expect_keywords": ["for", "in"],
    },
    {
        "id": "P3_fr",
        "domain": "french",
        "prompt": "Explique en 2 phrases pourquoi la récursivité peut être dangereuse.",
        "expect_keywords": ["pile", "stack", "infini", "profondeur", "mémoire", "appel", "débordement", "récursion"],
    },
    {
        "id": "P4_instruct",
        "domain": "instruction",
        "prompt": "List three best practices for REST API design. Be concise.",
        "expect_keywords": ["version", "status", "HTTP", "endpoint", "resource", "idempotent", "stateless", "method"],
    },
    {
        "id": "P5_math",
        "domain": "math",
        "prompt": "What is the result of 17 × 23? Show your work.",
        "expect_keywords": ["391"],
    },
]

# ── Cost table: USD per 1M tokens (input, output) ────────────────────────────
_COST_TABLE: list[tuple[str, float, float]] = [
    # prefix                 inp$/1M   out$/1M
    ("gemma4", 0.0, 0.0),        # local Ollama
    ("gemma", 0.0, 0.0),
    ("devstral", 0.0, 0.0),
    ("mistral-nemo", 0.0, 0.0),
    ("gpt-oss", 0.0, 0.0),       # OpenRouter free tier
    ("gpt-4o-mini", 0.15, 0.60),
    ("gpt-4o", 2.5, 10.0),
    ("gpt-4", 10.0, 30.0),
    ("claude-haiku", 0.80, 4.0),
    ("claude-sonnet", 3.0, 15.0),
    ("claude-opus", 15.0, 75.0),
    ("mistral-medium", 2.7, 8.1),
    ("magistral", 2.0, 6.0),
    ("codestral", 0.2, 0.6),
]
_COST_DEFAULT = (1.0, 3.0)


def _estimate_cost(model: str, in_tok: int, out_tok: int) -> float:
    m = model.lower()
    for prefix, inp_r, out_r in _COST_TABLE:
        if m.startswith(prefix):
            return (in_tok * inp_r + out_tok * out_r) / 1_000_000
    inp_r, out_r = _COST_DEFAULT
    return (in_tok * inp_r + out_tok * out_r) / 1_000_000


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class PromptResult:
    prompt_id: str
    domain: str
    latency_ms: float
    in_tokens: int
    out_tokens: int
    cost_usd: float
    score: float          # 0.0–1.0
    response_preview: str
    error: str = ""


@dataclass
class ModelReport:
    model: str
    api_url: str
    results: list[PromptResult] = field(default_factory=list)

    @property
    def avg_score(self) -> float:
        vals = [r.score for r in self.results if not r.error]
        return sum(vals) / len(vals) if vals else 0.0

    @property
    def avg_latency_ms(self) -> float:
        vals = [r.latency_ms for r in self.results if not r.error]
        return sum(vals) / len(vals) if vals else 0.0

    @property
    def total_cost_usd(self) -> float:
        return sum(r.cost_usd for r in self.results)

    @property
    def total_tokens(self) -> int:
        return sum(r.in_tokens + r.out_tokens for r in self.results)

    @property
    def errors(self) -> int:
        return sum(1 for r in self.results if r.error)


# ── Core helpers ─────────────────────────────────────────────────────────────

def _score_response(text: str, keywords: list[str]) -> float:
    if not keywords:
        return 1.0 if text.strip() else 0.0
    low = text.lower()
    return sum(1 for kw in keywords if kw.lower() in low) / len(keywords)


def _run_prompt(
    client: httpx.Client,
    api_url: str,
    model: str,
    token: Optional[str],
    prompt: dict,
) -> PromptResult:
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt["prompt"]}],
        "max_tokens": 256,
        "temperature": 0.1,
    }

    t0 = time.monotonic()
    try:
        resp = client.post(
            f"{api_url.rstrip('/')}/chat/completions",
            json=payload,
            headers=headers,
            timeout=90.0,
        )
        resp.raise_for_status()
        data = resp.json()
        latency_ms = (time.monotonic() - t0) * 1000

        content: str = data["choices"][0]["message"]["content"]
        usage = data.get("usage") or {}
        in_tok = usage.get("prompt_tokens", 0)
        out_tok = usage.get("completion_tokens", 0)

        return PromptResult(
            prompt_id=prompt["id"],
            domain=prompt["domain"],
            latency_ms=round(latency_ms, 1),
            in_tokens=in_tok,
            out_tokens=out_tok,
            cost_usd=_estimate_cost(model, in_tok, out_tok),
            score=_score_response(content, prompt.get("expect_keywords", [])),
            response_preview=content[:120].replace("\n", " "),
        )
    except Exception as exc:
        return PromptResult(
            prompt_id=prompt["id"],
            domain=prompt["domain"],
            latency_ms=round((time.monotonic() - t0) * 1000, 1),
            in_tokens=0,
            out_tokens=0,
            cost_usd=0.0,
            score=0.0,
            response_preview="",
            error=str(exc)[:120],
        )


def _eval_model(
    model: str,
    api_url: str,
    token: Optional[str],
    prompts: list[dict],
    verbose: bool = True,
) -> ModelReport:
    report = ModelReport(model=model, api_url=api_url)
    with httpx.Client() as client:
        for prompt in prompts:
            result = _run_prompt(client, api_url, model, token, prompt)
            report.results.append(result)
            if verbose:
                status = "ERR" if result.error else " OK"
                print(
                    f"  [{status}] {prompt['id']:<14}"
                    f"  score={result.score:.2f}"
                    f"  latency={result.latency_ms:>6.0f}ms"
                    f"  tok={result.in_tokens}+{result.out_tokens}"
                    + (f"  err={result.error[:50]}" if result.error else ""),
                    file=sys.stderr,
                )
    return report


# ── Output ───────────────────────────────────────────────────────────────────

_SEP = "-" * 72

def _print_table(reports: list[ModelReport]) -> None:
    print(_SEP)
    print(f"{'MODEL':<32} {'SCORE':>7} {'LATENCY':>10} {'COST_USD':>12} {'TOKENS':>8} {'ERRORS':>7}")
    print(_SEP)
    for r in reports:
        print(
            f"{r.model:<32}"
            f"  {r.avg_score*100:>5.1f}%"
            f"  {r.avg_latency_ms:>7.0f}ms"
            f"  {r.total_cost_usd:>11.6f}"
            f"  {r.total_tokens:>7}"
            f"  {r.errors:>6}"
        )
    print(_SEP)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="bea eval — benchmark model aliases (score/latency/cost)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "models",
        nargs="*",
        default=["default"],
        help="Model alias(es) to test (space-separated). Default: 'default'.",
    )
    parser.add_argument(
        "--api",
        default="http://127.0.0.1:8642/v1",
        help="OpenAI-compat base URL (default: Hermes gateway at 8642)",
    )
    parser.add_argument("--token", default=None, help="Bearer token for auth")
    parser.add_argument("--json", action="store_true", help="Also print JSON report to stdout")
    parser.add_argument(
        "--prompts",
        default=None,
        metavar="FILE",
        help="Custom prompts JSON file (must be a list of {id,domain,prompt,expect_keywords})",
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress per-prompt progress lines")
    args = parser.parse_args()

    prompts = DEFAULT_PROMPTS
    if args.prompts:
        prompts = json.loads(Path(args.prompts).read_text(encoding="utf-8"))

    reports: list[ModelReport] = []
    for model in args.models:
        print(f"\n=== {model} @ {args.api} ===", file=sys.stderr)
        report = _eval_model(model, args.api, args.token, prompts, verbose=not args.quiet)
        reports.append(report)

    print(file=sys.stderr)
    _print_table(reports)

    if args.json:
        out = []
        for r in reports:
            out.append({
                "model": r.model,
                "api_url": r.api_url,
                "avg_score": round(r.avg_score, 4),
                "avg_latency_ms": round(r.avg_latency_ms, 1),
                "total_cost_usd": round(r.total_cost_usd, 8),
                "total_tokens": r.total_tokens,
                "errors": r.errors,
                "prompts": [asdict(p) for p in r.results],
            })
        print(json.dumps(out, ensure_ascii=False, indent=2))

    failed = [r for r in reports if r.avg_score < 0.4]
    if failed:
        names = ", ".join(r.model for r in failed)
        print(f"WARNING: models below 40% quality bar: {names}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
