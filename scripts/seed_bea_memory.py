"""
Béa — Public memory seeding for private beta.

Usage:
    python scripts/seed_bea_memory.py --report --profile public
    python scripts/seed_bea_memory.py --apply --profile public

Exit codes:
    0  -> seed is public-safe and (if --apply) persisted
    1  -> profile unknown or seed not public-safe
    2  -> internal error

For the private beta, this script deliberately uses an offline JSONL store
(Qdrant is optional). It never stores real secrets.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = REPO_ROOT / "workspace" / "memory_seed_public.jsonl"

PUBLIC_SAMPLE = [
    {
        "key": "bea:private_beta:what_is_bea",
        "tags": ["bea", "private_beta", "overview"],
        "text": (
            "Béa is an experimental AI orchestration system. It is currently in a "
            "private developer preview. It is NOT stable, NOT production-ready, and "
            "NOT fully autonomous. Testers should use isolated environments and avoid "
            "submitting secrets or personal data."
        ),
    },
    {
        "key": "bea:private_beta:safety_rules",
        "tags": ["bea", "private_beta", "safety"],
        "text": (
            "Private beta safety rules: (1) keep self-improvement disabled unless you "
            "explicitly accept autonomous changes; (2) never submit API keys, passwords, "
            "or personal data into Béa's memory or chat; (3) run Béa in an isolated "
            "environment; (4) keep the BEA_SKIP_IMPROVEMENT_GATE variable unset; "
            "(5) report any suspected security issue privately."
        ),
    },
    {
        "key": "bea:private_beta:limitations",
        "tags": ["bea", "private_beta", "limitations"],
        "text": (
            "Known limitations of the private beta: some business handlers are scaffolding "
            "only; v1 API routes are deprecated and will be removed; the React frontend and "
            "React Native mobile app are secondary/unsupported; HexStrike v2 is a rough "
            "refactor in progress; Windows test suite has known path/encoding failures."
        ),
    },
    {
        "key": "bea:private_beta:ollama_fallback",
        "tags": ["bea", "private_beta", "ollama", "provider"],
        "text": (
            "To avoid cloud LLM costs or network dependencies, Béa can fall back to a local "
            "Ollama server. Set MODEL_FALLBACK=ollama and OLLAMA_HOST to your endpoint. "
            "tinyllama or mistral:7b are typical fallback models. Local models are slower "
            "and may produce lower quality reasoning than cloud providers."
        ),
    },
    {
        "key": "bea:private_beta:reporting_bugs",
        "tags": ["bea", "private_beta", "feedback"],
        "text": (
            "When reporting a bug during the private beta, include: OS, commit SHA, launch "
            "mode, provider used, endpoint/surface, exact reproduction steps, expected vs "
            "observed behavior, redacted logs, and a confirmation that no secrets or "
            "private data are included in the report."
        ),
    },
]

SECRET_RE = re.compile(
    r"\b(sk-[a-zA-Z0-9_-]{20,}|ghp_[a-zA-Z0-9]{36,}|gho_[a-zA-Z0-9]{36,}|"
    r"glpat-[a-zA-Z0-9_\-]{20,}|xoxb-[a-zA-Z0-9_\-]{10,}|AKIA[0-9A-Z]{16})\b",
    re.I,
)
SENSITIVE_TERMS = re.compile(
    r"\b(password|secret|token|api_key|private_key|credit_card|ssn)\b", re.I
)


def _looks_private(entry: dict) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    text = entry.get("text", "")
    if SECRET_RE.search(text):
        reasons.append("contains_secret_pattern")
    if SENSITIVE_TERMS.search(text):
        reasons.append("contains_sensitive_term")
    if re.search(r"\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b", text):
        reasons.append("contains_possible_card_number")
    return bool(reasons), reasons


def _check_public_safe(entries: list[dict]) -> tuple[bool, list[dict]]:
    bad: list[dict] = []
    for e in entries:
        is_private, reasons = _looks_private(e)
        if is_private:
            bad.append({"key": e.get("key"), "reasons": reasons})
    return not bad, bad


def _try_qdrant_upsert(entries: list[dict]) -> tuple[bool, str]:
    try:
        from qdrant_client import QdrantClient
    except Exception as exc:
        return False, f"qdrant_client not available ({exc})"

    url = os.environ.get("QDRANT_URL", "http://localhost:6333")
    key = os.environ.get("QDRANT_API_KEY", "")
    collection = os.environ.get("QDRANT_COLLECTION", "beamax_memory_384")
    try:
        client = QdrantClient(url=url, api_key=key or None)
        # best-effort collection creation
        try:
            client.create_collection(
                collection_name=collection,
                vectors_config={"size": 384, "distance": "Cosine"},
            )
        except Exception:
            pass
        for e in entries:
            client.upsert(
                collection_name=collection,
                points=[{
                    "id": e["key"],
                    "vector": [0.0] * 384,  # placeholder; real beta must use embeddings
                    "payload": {k: v for k, v in e.items() if k != "text"},
                }],
            )
        return True, "qdrant"
    except Exception as exc:
        return False, f"qdrant upsert failed ({exc})"


def _persist_jsonl(entries: list[dict]) -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed Béa public memory")
    parser.add_argument("--profile", required=True, choices=["public"], help="Seed profile")
    parser.add_argument("--report", action="store_true", help="Emit JSON report")
    parser.add_argument("--apply", action="store_true", help="Persist the seed")
    args = parser.parse_args(argv)

    if args.profile != "public":
        print(json.dumps({"error": "only the 'public' profile is supported"}), file=sys.stderr)
        return 1

    entries = PUBLIC_SAMPLE
    public_safe, bad = _check_public_safe(entries)

    report = {
        "profile": args.profile,
        "total_entries": len(entries),
        "public_safe": public_safe,
        "private_items": bad,
        "applied": False,
        "backend": None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if args.apply:
        if not public_safe:
            report["error"] = "apply_refused_unclean_seed"
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 1
        ok_qdrant, qdrant_msg = _try_qdrant_upsert(entries)
        if ok_qdrant:
            report["backend"] = qdrant_msg
        else:
            _persist_jsonl(entries)
            report["backend"] = f"jsonl:{OUTPUT_PATH.as_posix()} ({qdrant_msg})"
        report["applied"] = True

    if args.report or args.apply:
        print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))

    return 0 if public_safe else 1


if __name__ == "__main__":
    sys.exit(main())
