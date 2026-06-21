"""Audit Bea's Qdrant memory for stale/conflicting entries.

This is intentionally read-only. It writes a JSON report under
``data/memory_audits`` and never deletes or rewrites memory points.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

COLLECTION = "beamax_memory_384"
REPORT_DIR = Path("data/memory_audits")

log = logging.getLogger(__name__)

SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|token|secret|password|refresh[_-]?token)\s*[:=]\s*['\"]?[A-Za-z0-9_\-./+]{12,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{20,}"),
)

OBSOLETE_PATTERNS = (
    re.compile(r"\bjarvismax_memory_384\b", re.IGNORECASE),
    re.compile(r"\bjarvismax\b", re.IGNORECASE),
    re.compile(r"\bjarvis\b", re.IGNORECASE),
    re.compile(r"\bARCHIVED\b|\barchive\b|supprim[eé]|mort[es]?\b", re.IGNORECASE),
)

ACTIVE_PATTERNS = (
    re.compile(r"\bACTIF\b|\bactive\b|beamax|B[eé]a", re.IGNORECASE),
)


def _qdrant_key() -> str:
    if os.environ.get("QDRANT_API_KEY"):
        return os.environ["QDRANT_API_KEY"]
    try:
        output = subprocess.check_output(
            ["docker", "exec", "beamax-qdrant", "env"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except Exception:
        return ""
    for line in output.splitlines():
        if line.startswith("QDRANT__SERVICE__API_KEY="):
            return line.split("=", 1)[1].strip()
    return ""


def _classify(payload: dict[str, Any]) -> tuple[str, list[str]]:
    text = str(payload.get("text", ""))
    key = str(payload.get("key", ""))
    haystack = f"{key}\n{text}"
    reasons: list[str] = []

    if any(pattern.search(haystack) for pattern in SECRET_PATTERNS):
        reasons.append("possible_secret")
    if any(pattern.search(haystack) for pattern in OBSOLETE_PATTERNS):
        reasons.append("legacy_or_obsolete_terms")
    if any(pattern.search(haystack) for pattern in ACTIVE_PATTERNS):
        reasons.append("active_terms")

    if "possible_secret" in reasons:
        return "review_sensitive", reasons
    if "legacy_or_obsolete_terms" in reasons and "active_terms" not in reasons:
        return "likely_obsolete", reasons
    if "legacy_or_obsolete_terms" in reasons and "active_terms" in reasons:
        return "mixed_historical_context", reasons
    return "active_or_neutral", reasons


def _safe_snippet(text: str, limit: int = 180) -> str:
    snippet = " ".join(text.split())[:limit]
    for pattern in SECRET_PATTERNS:
        snippet = pattern.sub("[REDACTED]", snippet)
    return snippet


def _scroll_all(qdrant_url: str, api_key: str, limit: int) -> list[dict[str, Any]]:
    import httpx

    headers = {"Content-Type": "application/json", "api-key": api_key}
    points: list[dict[str, Any]] = []
    offset: Any = None
    with httpx.Client(headers=headers, timeout=20) as client:
        while True:
            body: dict[str, Any] = {"limit": min(limit, 256), "with_payload": True, "with_vector": False}
            if offset is not None:
                body["offset"] = offset
            response = client.post(
                f"{qdrant_url.rstrip('/')}/collections/{COLLECTION}/points/scroll",
                json=body,
            )
            response.raise_for_status()
            result = response.json()["result"]
            batch = result.get("points", [])
            points.extend(batch)
            offset = result.get("next_page_offset")
            if not offset or len(points) >= limit:
                return points[:limit]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit Bea memory conflicts without mutating Qdrant.")
    parser.add_argument("--qdrant-url", default=os.environ.get("QDRANT_URL", "http://127.0.0.1:6333"))
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--report-dir", default=str(REPORT_DIR))
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args()
    key = _qdrant_key()
    if not key:
        log.error("QDRANT_API_KEY introuvable. Audit impossible.")
        return 1

    points = _scroll_all(args.qdrant_url, key, args.limit)
    buckets: dict[str, list[dict[str, Any]]] = {
        "review_sensitive": [],
        "likely_obsolete": [],
        "mixed_historical_context": [],
        "active_or_neutral": [],
    }
    bucket_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    tag_counts: Counter[str] = Counter()

    for point in points:
        payload = point.get("payload") or {}
        bucket, reasons = _classify(payload)
        bucket_counts[bucket] += 1
        source_counts[str(payload.get("source", ""))] += 1
        for tag in payload.get("tags") or []:
            tag_counts[str(tag)] += 1
        if bucket != "active_or_neutral":
            buckets[bucket].append(
                {
                    "id": str(point.get("id", "")),
                    "key": str(payload.get("key", "")),
                    "source": str(payload.get("source", "")),
                    "category": str(payload.get("category", "")),
                    "reasons": reasons,
                    "snippet": _safe_snippet(str(payload.get("text", ""))),
                }
            )

    report = {
        "collection": COLLECTION,
        "generated_at": datetime.now(UTC).isoformat(),
        "scanned": len(points),
        "counts": {name: bucket_counts[name] for name in buckets},
        "top_sources": source_counts.most_common(20),
        "top_tags": tag_counts.most_common(30),
        "candidates": buckets,
        "policy": "read_only_audit_no_delete_no_update",
    }

    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"bea_memory_audit_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("OK: scanned=%s report=%s", len(points), report_path)
    log.info("counts=%s", report["counts"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
