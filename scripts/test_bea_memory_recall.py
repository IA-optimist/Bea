"""Live recall smoke test for Bea's seeded Qdrant memory.

This script exercises the same path Telegram/agents use via ``MemoryBus`` and
checks that ``beamax_memory_384`` contributes relevant hits.

Run:
    python scripts/test_bea_memory_recall.py
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import get_settings
from memory.memory_bus import MemoryBus

log = logging.getLogger(__name__)

DEFAULT_QUERIES = (
    "Comment Bea doit gerer les secrets et tokens dans sa memoire ?",
    "Quelle methode Bea doit suivre avant de corriger son propre code ?",
    "Quel style de reponse Max prefere-t-il ?",
    "Comment Bea doit resoudre un conflit entre une ancienne memoire et le code actuel ?",
)


def _seed_qdrant_env_from_docker() -> None:
    if os.environ.get("QDRANT_API_KEY"):
        return
    try:
        output = subprocess.check_output(
            ["docker", "exec", "beamax-qdrant", "env"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except Exception as exc:
        log.info("qdrant_key_auto_discovery_skipped: %s", str(exc)[:80])
        return

    for line in output.splitlines():
        if line.startswith("QDRANT__SERVICE__API_KEY="):
            os.environ["QDRANT_API_KEY"] = line.split("=", 1)[1].strip()
            break


async def _run_query(bus: MemoryBus, query: str) -> bool:
    hits = await bus.recall(query, top_k=5, min_score=0.2)
    qdrant_hits = [hit for hit in hits if hit.get("backend") == "qdrant_beamax"]
    log.info("query=%r hits=%s qdrant_hits=%s", query, len(hits), len(qdrant_hits))
    for hit in qdrant_hits[:2]:
        metadata = hit.get("metadata", {})
        log.info(
            "  %.4f %s",
            float(hit.get("score", 0.0)),
            metadata.get("key", ""),
        )
    return bool(qdrant_hits)


async def _run_search_probe(bus: MemoryBus) -> bool:
    hits = await bus.search("style de reponse prefere par Max", top_k=5)
    qdrant_hits = [hit for hit in hits if hit.get("backend") == "qdrant_beamax"]
    log.info("search_probe hits=%s qdrant_hits=%s", len(hits), len(qdrant_hits))
    return bool(qdrant_hits)


async def main_async() -> int:
    os.environ["QDRANT_URL"] = os.environ.get("BEA_RECALL_TEST_QDRANT_URL", "http://127.0.0.1:6333")
    _seed_qdrant_env_from_docker()

    bus = MemoryBus(get_settings())
    results = [await _run_query(bus, query) for query in DEFAULT_QUERIES]
    results.append(await _run_search_probe(bus))
    failed = results.count(False)
    if failed:
        log.error("FAIL: %s/%s queries had no qdrant_beamax hit", failed, len(results))
        return 1
    log.info("OK: all %s recall probes returned qdrant_beamax hits", len(results))
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
