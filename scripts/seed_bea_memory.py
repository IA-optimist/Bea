#!/usr/bin/env python3
"""Seed initial operational memories from known audits and docs.

Usage:
    python scripts/seed_bea_memory.py

Adds the minimal memories required for bea eval to pass and for the agent
coder to retrieve useful context when handed an issue or mission.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make repo imports work when invoked as script
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.memory.memory_item import MemoryItem, MemoryItemStatus, MemoryItemType
from core.memory.operational_memory import get_operational_memory_store


_INITIAL_MEMORIES: list[MemoryItem] = [
    MemoryItem(
        type=MemoryItemType.ARCHITECTURE_DECISION,
        title="Routeur v1 doit avoir une façade canonique",
        content="api/routes/v1.py est la façade canonique v1. Les clients doivent migrer vers /api/v2/* et /api/v3/*.",
        related_files=["api/routes/v1.py", "api/main.py"],
        related_tests=["tests/api/test_routes.py"],
        tags=["api", "v1", "canonical", "deprecated"],
        source="audit/architecture",
        confidence=0.95,
    ),
    MemoryItem(
        type=MemoryItemType.ARCHITECTURE_DECISION,
        title="Stream missions v1 encore critique pour Flutter",
        content="Tant que l'application Flutter n'est pas migrée, /api/v1/missions/{id}/stream reste important.",
        related_files=["api/routes/v1.py", "api/ws.py"],
        related_tests=["tests/api/test_missions.py"],
        tags=["api", "v1", "stream", "flutter", "legacy"],
        source="docs/decisions",
        confidence=0.9,
    ),
    MemoryItem(
        type=MemoryItemType.RISK,
        title="GitAgent indisponible = REVIEW ou REJECT",
        content="Si l'agent Git n'est pas joignable, un patch ne peut pas être poussé automatiquement : forcer REVIEW ou REJECT, jamais PROMOTE.",
        related_files=["core/business/github_automation.py"],
        related_tests=["tests/core/business/test_github_automation.py"],
        tags=["git", "risk", "self-improvement", "policy"],
        source="security/policy",
        confidence=1.0,
        status=MemoryItemStatus.DANGEROUS,
    ),
    MemoryItem(
        type=MemoryItemType.RISK,
        title="Patch non signé = jamais PROMOTE en prod/merge",
        content="Un patch self-improvement non signé ne doit jamais atteindre le statut PROMOTE ni être mergé en production.",
        related_files=["plugins/signatures.py", "core/self_improvement/promotion_pipeline.py"],
        related_tests=["tests/test_plugin_signatures.py"],
        tags=["patch", "signature", "security", "policy"],
        source="security/policy",
        confidence=1.0,
        status=MemoryItemStatus.DANGEROUS,
    ),
    MemoryItem(
        type=MemoryItemType.RISK,
        title="MemoryFacade Qdrant live doit être stress-testée",
        content="La connexion Qdrant de MemoryFacade fonctionne mais n'a pas été stress-testée en charge réelle.",
        related_files=["core/memory_facade.py", "memory/qdrant_recall.py"],
        related_tests=["tests/test_memory_facade.py"],
        tags=["memory", "qdrant", "risk", "performance"],
        source="docs/STATUS.md",
        confidence=0.7,
        status=MemoryItemStatus.DANGEROUS,
    ),
    MemoryItem(
        type=MemoryItemType.BUG_MEMORY,
        title="business.deploy_product est encore à prouver",
        content="Le handler business.deploy_product existe mais la logique de déploiement réel (Vercel API + Railway API) est encore un TODO.",
        related_files=["business/business_engine.py", "business/automation/deploy_manager.py"],
        related_tests=["tests/business/test_deploy_product.py"],
        tags=["business", "deploy", "bug", "todo"],
        source="docs/STATUS.md",
        confidence=0.85,
    ),
    MemoryItem(
        type=MemoryItemType.ARCHITECTURE_DECISION,
        title="HexStrike doit rester hors core et feature-flagged",
        content="HexStrike v2 est en cours de split et doit rester hors de core/, isolé sous mcp/hexstrike_v2 ou subprojects/, et feature-flagged.",
        related_files=["mcp/hexstrike_v2/", "subprojects/hexstrike_v2/"],
        related_tests=["tests/mcp/test_hexstrike_v2.py"],
        tags=["hexstrike", "security", "mcp", "policy"],
        source="audit/architecture",
        confidence=0.9,
    ),
    MemoryItem(
        type=MemoryItemType.ARCHITECTURE_DECISION,
        title="Béa doit stocker les résultats de mission comme mémoire",
        content="Chaque résultat de mission (succès, échec, leçon) doit être stocké dans la mémoire opérationnelle pour améliorer les futures missions.",
        related_files=["core/memory/operational_memory.py", "core/memory_facade.py"],
        related_tests=["tests/core/memory/test_operational_memory.py"],
        tags=["memory", "policy", "missions"],
        source="docs/memory_taxonomy.md",
        confidence=0.95,
    ),
]


def seed(store=None) -> dict[str, int]:
    store = store or get_operational_memory_store()
    added = 0
    skipped = 0
    for item in _INITIAL_MEMORIES:
        # Avoid duplicating exact title + source
        existing = store.search(text_query=item.title, limit=1)
        if existing and existing[0].title == item.title and existing[0].source == item.source:
            skipped += 1
            continue
        store.add(item)
        added += 1
    return {"added": added, "skipped": skipped, "total": store.count()}


def main(argv: list[str] | None = None) -> int:
    result = seed()
    print(f"Seeded operational memories: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
