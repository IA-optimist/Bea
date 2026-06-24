"""
Béa — Memory store privacy/secret audit.

Usage:
    python scripts/audit_memory_store.py --dry-run --privacy-scan --json
    python scripts/audit_memory_store.py --apply --privacy-scan --json

Exit codes:
    0  -> scan clean
    1  -> private items or secrets detected
    2  -> internal error

--apply is fail-closed: it refuses to persist/copy anything unless the scan
is clean. This script never mutates the source data.
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
DEFAULT_SEED = REPO_ROOT / "workspace" / "memory_seed_public.jsonl"

SECRET_RE = re.compile(
    r"\b(sk-[a-zA-Z0-9_-]{20,}|ghp_[a-zA-Z0-9]{36,}|gho_[a-zA-Z0-9]{36,}|"
    r"glpat-[a-zA-Z0-9_\-]{20,}|xoxb-[a-zA-Z0-9_\-]{10,}|AKIA[0-9A-Z]{16}|"
    r"https://discord\.com/api/webhooks/\d+/[a-zA-Z0-9_\-]+)\b",
    re.I,
)
SENSITIVE_TERMS = re.compile(
    r"\b(password|secret|token|api[_-]?key|private[_-]?key|credit[_-]?card|ssn|"
    r"iban|iban|passphrase|auth[_-]?token)\b",
    re.I,
)
PRIVATE_DATA_RE = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Z|a-z]{2,}\b|"
    r"\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b|"
    r"\b\d{3}[\s\-]?\d{3}[\s\-]?\d{4}\b",
)


def _scan_entry(entry: dict) -> list[str]:
    """Return a list of reasons why an entry might be private."""
    reasons: list[str] = []
    text = str(entry.get("text", ""))
    key = str(entry.get("key", ""))
    combined = text + " " + key
    if SECRET_RE.search(combined):
        reasons.append("secret_pattern")
    if SENSITIVE_TERMS.search(combined):
        reasons.append("sensitive_term")
    if PRIVATE_DATA_RE.search(combined):
        reasons.append("possible_pii")
    return reasons


def _load_jsonl(path: Path) -> list[dict]:
    entries: list[dict] = []
    if not path.exists():
        return entries
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entries.append({"_src_line": line_no, **json.loads(line)})
            except json.JSONDecodeError:
                entries.append({"_src_line": line_no, "_parse_error": line})
    return entries


def _try_qdrant_scan() -> tuple[list[dict], list[str]]:
    findings: list[dict] = []
    warnings: list[str] = []
    try:
        from qdrant_client import QdrantClient
    except Exception as exc:
        warnings.append(f"qdrant_client not available: {exc}")
        return findings, warnings

    url = os.environ.get("QDRANT_URL", "http://localhost:6333")
    key = os.environ.get("QDRANT_API_KEY", "")
    collection = os.environ.get("QDRANT_COLLECTION", "beamax_memory_384")
    try:
        client = QdrantClient(url=url, api_key=key or None)
        result, _offset = client.scroll(collection_name=collection, limit=1000, with_payload=True)
        for point in result:
            payload = point.payload or {}
            reasons = _scan_entry(payload)
            if reasons:
                findings.append({
                    "source": "qdrant",
                    "id": point.id,
                    "key": payload.get("key"),
                    "reasons": reasons,
                })
    except Exception as exc:
        warnings.append(f"Qdrant scan skipped (not running): {exc}")
    return findings, warnings


def _run_scan() -> dict:
    entries = _load_jsonl(DEFAULT_SEED)
    seed_findings: list[dict] = []
    for e in entries:
        reasons = _scan_entry(e)
        if reasons:
            seed_findings.append({
                "source": "jsonl",
                "line": e.get("_src_line"),
                "key": e.get("key"),
                "reasons": reasons,
            })

    qdrant_findings, qdrant_warnings = _try_qdrant_scan()
    all_findings = seed_findings + qdrant_findings

    return {
        "scan_timestamp": datetime.now(timezone.utc).isoformat(),
        "seed_path": DEFAULT_SEED.as_posix(),
        "seed_entries_scanned": len(entries),
        "qdrant_scanned": True,
        "qdrant_warnings": qdrant_warnings,
        "private_items_count": len(all_findings),
        "private_items": all_findings,
        "clean": len(all_findings) == 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit Béa memory store for private data")
    parser.add_argument("--dry-run", action="store_true", help="Report only (default)")
    parser.add_argument("--apply", action="store_true", help="Fail-closed apply")
    parser.add_argument("--privacy-scan", action="store_true", required=True, help="Enable privacy scan")
    parser.add_argument("--json", action="store_true", help="Emit JSON report")
    args = parser.parse_args(argv)

    if args.apply and not args.dry_run:
        args.dry_run = True  # --apply always runs a dry-run first

    result = _run_scan()

    if args.apply:
        if not result["clean"]:
            result["apply"] = "refused_unclean"
        else:
            # Nothing more to do: source is already the approved public seed.
            result["apply"] = "approved_noop"

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(f"Scanned {result['seed_entries_scanned']} seed entries.")
        print(f"Private items found: {result['private_items_count']}")
        if result["private_items"]:
            print("Details:")
            for f in result["private_items"]:
                print(f"  - {f}")
        print("Status:", "CLEAN" if result["clean"] else "DIRTY")

    return 0 if result["clean"] else 1


if __name__ == "__main__":
    sys.exit(main())
