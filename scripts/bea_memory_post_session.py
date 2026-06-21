"""Post-session memory ritual for Bea.

Use this after a meaningful development/debugging session to persist durable
lessons into ``beamax_memory_384``. The script refuses likely secrets and uses
stable UUIDs so entries can be updated without duplication.

Example:
    python scripts/bea_memory_post_session.py \
      --key session:2026-06-21:lesson \
      --title "Rappel Qdrant Bea" \
      --lesson "MemoryBus must query beamax_memory_384 before local fallback." \
      --tags bea memory qdrant
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

COLLECTION = "beamax_memory_384"
SOURCE = "bea_post_session_ritual"
MODEL = "all-MiniLM-L6-v2"

log = logging.getLogger(__name__)

SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|token|secret|password|refresh[_-]?token)\s*[:=]\s*['\"]?[A-Za-z0-9_\-./+]{12,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{20,}"),
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


def _has_secret(text: str) -> bool:
    return any(pattern.search(text) for pattern in SECRET_PATTERNS)


def _point_id(key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{COLLECTION}:{SOURCE}:{key}"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Store a durable post-session lesson in Bea memory.")
    parser.add_argument("--key", required=True, help="Stable unique key, e.g. session:2026-06-21:qdrant-recall")
    parser.add_argument("--title", required=True, help="Short human-readable title")
    parser.add_argument("--lesson", required=True, help="Durable lesson to remember")
    parser.add_argument("--tags", nargs="+", default=["bea", "post-session"], help="Tags for retrieval")
    parser.add_argument("--category", default="bea_post_session_lesson", help="Memory category")
    parser.add_argument("--qdrant-url", default=os.environ.get("QDRANT_URL", "http://127.0.0.1:6333"))
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args()
    text = f"{args.title}: {args.lesson}".strip()
    if _has_secret(text):
        log.error("Refus: le texte ressemble a un secret. Redige une lecon sans valeur sensible.")
        return 2

    key = _qdrant_key()
    if not key:
        log.error("QDRANT_API_KEY introuvable. Demarrer beamax-qdrant ou definir QDRANT_API_KEY.")
        return 1

    try:
        import httpx
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        log.error("Dependance manquante: %s", exc)
        return 1

    vector = SentenceTransformer(MODEL).encode(text, normalize_embeddings=True).tolist()
    point = {
        "id": _point_id(args.key),
        "vector": vector,
        "payload": {
            "key": args.key,
            "tags": args.tags,
            "text": text,
            "category": args.category,
            "source": SOURCE,
            "ts": time.time(),
        },
    }
    response = httpx.put(
        f"{args.qdrant_url.rstrip('/')}/collections/{COLLECTION}/points",
        headers={"Content-Type": "application/json", "api-key": key},
        json={"points": [point]},
        timeout=20,
    )
    response.raise_for_status()
    log.info("OK: lesson upserted as %s", args.key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
