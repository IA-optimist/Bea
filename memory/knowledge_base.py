"""Base de connaissances RAG locale pour Béa — in-process, sans Docker.

S'appuie sur ``memory.vector_memory.VectorMemory`` (embeddings sentence-transformers
+ cosine numpy, persistance JSON) mais sur un fichier DÉDIÉ
(``workspace/knowledge_store.json``), séparé de la mémoire de conversation.

Usage :
    kb = KnowledgeBase(get_settings())
    kb.ingest_directory("C:/chemin/vault-obsidian")   # .md/.txt/.rst
    hits = kb.search("ma question", top_k=4)
    # -> [{"text": "...", "source": "note.md", "score": 0.83}, ...]
"""
from __future__ import annotations

from pathlib import Path

from memory.vector_memory import VectorMemory

_CHUNK = 800
_OVERLAP = 150
_KB_MAX_DOCS = 20000          # cap dédié (la conversation est plafonnée plus bas ailleurs)
_SUFFIXES = {".md", ".markdown", ".txt", ".rst", ".text"}


def chunk_text(text: str, size: int = _CHUNK, overlap: int = _OVERLAP) -> list[str]:
    """Découpe un texte en morceaux chevauchants, en cassant à une frontière proche."""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    chunks: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        end = min(i + size, n)
        if end < n:                                  # tenter une coupe propre
            brk = text.rfind("\n", i + size // 2, end)
            if brk == -1:
                brk = text.rfind(". ", i + size // 2, end)
            if brk != -1 and brk > i:
                end = brk + 1
        piece = text[i:end].strip()
        if piece:
            chunks.append(piece)
        if end >= n:
            break
        i = max(end - overlap, i + 1)
    return chunks


class _KnowledgeStore(VectorMemory):
    """VectorMemory sur un fichier dédié + cap relevé (sans tronquer la connaissance)."""

    def _resolve_path(self) -> Path:
        base = Path(getattr(self.s, "workspace_dir", "workspace"))
        base.mkdir(parents=True, exist_ok=True)
        return base / "knowledge_store.json"

    def _save(self) -> None:
        import json
        if len(self._docs) > _KB_MAX_DOCS:
            self._docs = self._docs[-_KB_MAX_DOCS:]
        try:
            self._path.write_text(json.dumps(self._docs, ensure_ascii=False), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass


class KnowledgeBase:
    """RAG : ingestion (chunk + embeddings) + recherche sémantique ancrée."""

    def __init__(self, settings):
        self._vm = _KnowledgeStore(settings)

    # ── Ingestion ─────────────────────────────────────────────
    def ingest_text(self, text: str, source: str) -> int:
        n = 0
        for ch in chunk_text(text):
            if self._vm.add(ch, {"source": source, "type": "knowledge"}):
                n += 1
        return n

    def ingest_file(self, path: str | Path) -> int:
        p = Path(path)
        if p.suffix.lower() not in _SUFFIXES:
            return 0
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            return 0
        return self.ingest_text(text, source=p.name)

    def ingest_directory(self, directory: str | Path) -> dict:
        d = Path(directory).expanduser()
        files = chunks = 0
        for p in sorted(d.rglob("*")):
            if p.is_file() and p.suffix.lower() in _SUFFIXES:
                c = self.ingest_file(p)
                if c:
                    files += 1
                    chunks += c
        return {"files": files, "chunks": chunks, "total": self.count()}

    # ── Recherche ─────────────────────────────────────────────
    def search(self, query: str, top_k: int = 4, min_score: float = 0.30) -> list[dict]:
        hits = self._vm.search(
            query, top_k=top_k,
            filter_fn=lambda d: (d.get("metadata") or {}).get("type") == "knowledge",
        )
        out = []
        for h in hits:
            score = round(float(h.get("score", 0.0)), 3)
            if score < min_score:          # bruit -> écarté (favorise l'abstention)
                continue
            meta = h.get("metadata") or {}
            out.append({"text": h.get("text", ""),
                        "source": meta.get("source", "?"), "score": score})
        return out

    def count(self) -> int:
        return sum(1 for d in self._vm._docs
                   if (d.get("metadata") or {}).get("type") == "knowledge")
