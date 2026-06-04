"""Ingestion de connaissances dans la base RAG locale de Béa (sans Docker).

Indexe les fichiers .md/.txt/.rst d'un dossier (ex. un vault Obsidian) dans
``workspace/knowledge_store.json``. Béa les interroge ensuite via l'outil
``knowledge_search``.

Usage (venv local) :
    python scripts/ingest_knowledge.py "C:\\chemin\\vers\\mon-vault"
    python scripts/ingest_knowledge.py docs            # corpus de test du repo

⚠️ Arrêter le bot pendant une grosse ingestion (le store JSON est partagé).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python scripts/ingest_knowledge.py <dossier>")
        return 2
    target = Path(sys.argv[1]).expanduser()
    if not target.exists():
        print(f"erreur: chemin introuvable: {target}")
        return 1

    # Charge le .env (pour workspace_dir / config embeddings) sans écraser l'env.
    import os
    env = Path(__file__).resolve().parents[1] / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

    from config.settings import get_settings
    from memory.knowledge_base import KnowledgeBase

    kb = KnowledgeBase(get_settings())
    print(f"Ingestion de {target} … (base actuelle : {kb.count()} chunks)")
    if target.is_file():
        c = kb.ingest_file(target)
        res = {"files": 1 if c else 0, "chunks": c, "total": kb.count()}
    else:
        res = kb.ingest_directory(target)
    print(f"✅ {res['files']} fichier(s), {res['chunks']} nouveau(x) chunk(s). "
          f"Base totale : {res['total']} chunks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
