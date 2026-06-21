#!/usr/bin/env python3
"""
scripts/memory_ensure_fun_fact.py — Ensure the canonical Max fun fact is stored safely.

Corrects any existing misclassification and upserts the expected fun fact.

Usage:
    python scripts/memory_ensure_fun_fact.py
    python scripts/memory_ensure_fun_fact.py --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Make repo imports work when invoked as script
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.memory.memory_item import MemoryItem, MemoryItemStatus, MemoryItemType
from core.memory.operational_memory import OperationalMemoryStore, get_operational_memory_store


_FUN_FACT_CONTENT = "Max aime que Béa retienne qu'il est l'amour de la vie de sa petite amie."


def _stdout(text: str) -> None:
    sys.stdout.write(text + "\n")


def ensure(store: OperationalMemoryStore) -> dict[str, Any]:
    """Upsert the canonical fun fact and fix misclassified project/fun facts."""
    result: dict[str, Any] = {"fun_fact_id": None, "corrected_ids": [], "skipped": []}

    # 1. Correct any repo_fact / REPO_FACT that contains the project fact title but is tagged as fun_fact
    candidates = store.search(text_query="Max est le seul humain", limit=10)
    for item in candidates:
        if "Max est le seul humain" in item.title or "Max est le seul humain" in item.content:
            if item.type != MemoryItemType.PROJECT_FACT or "fun_fact" in item.tags:
                item.type = MemoryItemType.PROJECT_FACT
                item.tags = [t for t in item.tags if t not in {"fun_fact", "private_joke", "humour", "romance"}]
                if "max" not in item.tags:
                    item.tags.append("max")
                if "origin" not in item.tags:
                    item.tags.append("origin")
                if "identity" not in item.tags:
                    item.tags.append("identity")
                item.source = "seed:project_fact"
                item.metadata.pop("importance", None)
                item.metadata.pop("privacy", None)
                item.metadata.pop("not_for_decision", None)
                store.add(item)
                result["corrected_ids"].append(item.id)

    # 2. Upsert the canonical romantic fun fact
    existing_fun = store.search(type=MemoryItemType.FUN_FACT, text_query="amour de la vie", limit=5)
    canonical = None
    for item in existing_fun:
        if _FUN_FACT_CONTENT in item.content:
            canonical = item
            break

    if canonical is None:
        canonical = MemoryItem(
            type=MemoryItemType.FUN_FACT,
            title="Fun fact romantique sur Max",
            content=_FUN_FACT_CONTENT,
            tags=["private_joke", "humour", "romance"],
            source="seed:fun_fact",
            confidence=0.9,
            status=MemoryItemStatus.ACTIVE,
            metadata={"importance": "low", "privacy": "personal", "not_for_decision": True},
        )
        store.add(canonical)
    else:
        # Ensure metadata/tags are canonical
        canonical.type = MemoryItemType.FUN_FACT
        canonical.tags = ["private_joke", "humour", "romance"]
        canonical.metadata["importance"] = "low"
        canonical.metadata["privacy"] = "personal"
        canonical.metadata["not_for_decision"] = True
        store.add(canonical)

    result["fun_fact_id"] = canonical.id
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ensure the canonical Max fun fact is safe")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--db-path", type=str, default="", help="Optional operational memory DB path")
    args = parser.parse_args(argv)

    store = OperationalMemoryStore(db_path=args.db_path) if args.db_path else get_operational_memory_store()
    result = ensure(store)

    if args.json:
        sys.stdout.write(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    else:
        _stdout(f"Fun fact id      : {result['fun_fact_id']}")
        _stdout(f"Corrected ids    : {result['corrected_ids']}")
        _stdout(f"Store total      : {store.count()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
