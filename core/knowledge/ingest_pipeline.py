"""
core/knowledge/ingest_pipeline.py — Knowledge ingestion for AI OS.

Allows Bea to learn from:
- Documentation files (markdown, txt)
- Code repositories (Python files)
- API specs (OpenAPI/JSON)
- Logs (structured/unstructured)
- Conversation history

Stores structured knowledge in vector memory with typed metadata.
"""
from __future__ import annotations

import hashlib
import os
import structlog
from dataclasses import dataclass, field
from typing import Literal
from pathlib import Path

log = structlog.get_logger("bea.knowledge_ingest")

KnowledgeSource = Literal["documentation", "code", "api_spec", "logs", "conversation"]


# ── Knowledge Entry ──────────────────────────────────────────────────────────

@dataclass
class KnowledgeEntry:
    """A piece of ingested knowledge."""
    content: str
    source_type: KnowledgeSource
    source_path: str = ""
    content_hash: str = ""
    chunk_index: int = 0
    total_chunks: int = 1
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.content_hash:
            self.content_hash = hashlib.sha256(self.content.encode()).hexdigest()[:16]


# ── Chunking ─────────────────────────────────────────────────────────────────

def chunk_text(text: str, max_chars: int = 1000, overlap: int = 100) -> list[str]:
    """Split text into overlapping chunks for embedding."""
    if len(text) <= max_chars:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = start + max_chars
        # Try to break at paragraph or sentence boundary
        if end < len(text):
            for boundary in ["\n\n", "\n", ". ", "! ", "? "]:
                idx = text.rfind(boundary, start, end)
                if idx > start + max_chars // 2:
                    end = idx + len(boundary)
                    break
        chunks.append(text[start:end].strip())
        start = end - overlap
    return [c for c in chunks if c]


# ── Source Readers ───────────────────────────────────────────────────────────

def read_markdown(path: str) -> list[KnowledgeEntry]:
    """Ingest a markdown document."""
    try:
        with open(path) as f:
            text = f.read()
        chunks = chunk_text(text)
        return [
            KnowledgeEntry(
                content=chunk,
                source_type="documentation",
                source_path=path,
                chunk_index=i,
                total_chunks=len(chunks),
                metadata={"format": "markdown", "filename": os.path.basename(path)},
            )
            for i, chunk in enumerate(chunks)
        ]
    except Exception as e:
        log.warning("ingest_markdown_failed", path=path, err=str(e)[:60])
        return []


def read_python_file(path: str) -> list[KnowledgeEntry]:
    """Ingest a Python source file — extracts docstrings and structure."""
    try:
        with open(path) as f:
            text = f.read()
        # Extract module-level docstring and class/function signatures
        lines = text.split("\n")
        sections = []
        current = []
        for line in lines:
            if line.startswith("class ") or line.startswith("def ") or line.startswith("async def "):
                if current:
                    sections.append("\n".join(current))
                current = [line]
            else:
                current.append(line)
        if current:
            sections.append("\n".join(current))

        # Chunk each section
        entries = []
        for i, section in enumerate(sections):
            if len(section.strip()) < 20:
                continue
            chunks = chunk_text(section, max_chars=800)
            for j, chunk in enumerate(chunks):
                entries.append(KnowledgeEntry(
                    content=chunk,
                    source_type="code",
                    source_path=path,
                    chunk_index=len(entries),
                    metadata={"language": "python", "filename": os.path.basename(path)},
                ))
        return entries
    except Exception as e:
        log.warning("ingest_python_failed", path=path, err=str(e)[:60])
        return []


def read_json_spec(path: str) -> list[KnowledgeEntry]:
    """Ingest a JSON/OpenAPI spec file."""
    import json
    try:
        with open(path) as f:
            data = json.load(f)
        text = json.dumps(data, indent=2)
        chunks = chunk_text(text, max_chars=1200)
        return [
            KnowledgeEntry(
                content=chunk,
                source_type="api_spec",
                source_path=path,
                chunk_index=i,
                total_chunks=len(chunks),
                metadata={"format": "json", "filename": os.path.basename(path)},
            )
            for i, chunk in enumerate(chunks)
        ]
    except Exception as e:
        log.warning("ingest_json_failed", path=path, err=str(e)[:60])
        return []


def read_log_file(path: str, max_lines: int = 500) -> list[KnowledgeEntry]:
    """Ingest a log file — recent lines only."""
    try:
        with open(path) as f:
            lines = f.readlines()
        recent = lines[-max_lines:]
        text = "".join(recent)
        chunks = chunk_text(text, max_chars=800)
        return [
            KnowledgeEntry(
                content=chunk,
                source_type="logs",
                source_path=path,
                chunk_index=i,
                total_chunks=len(chunks),
                metadata={"format": "log", "filename": os.path.basename(path)},
            )
            for i, chunk in enumerate(chunks)
        ]
    except Exception as e:
        log.warning("ingest_log_failed", path=path, err=str(e)[:60])
        return []


# ── Ingest Pipeline ──────────────────────────────────────────────────────────

_READER_MAP = {
    ".md": read_markdown,
    ".txt": read_markdown,
    ".py": read_python_file,
    ".json": read_json_spec,
    ".log": read_log_file,
}


class IngestPipeline:
    """Knowledge ingestion pipeline for AI OS."""

    def __init__(self):
        self._ingested_hashes: set[str] = set()
        self._total_ingested = 0
        self._total_chunks = 0

    def ingest_file(self, path: str) -> int:
        """Ingest a single file. Returns number of chunks stored."""
        ext = Path(path).suffix.lower()
        reader = _READER_MAP.get(ext)
        if not reader:
            log.debug("ingest_skip_unsupported", path=path, ext=ext)
            return 0

        entries = reader(path)
        stored = 0
        for entry in entries:
            if entry.content_hash in self._ingested_hashes:
                continue
            if self._store_entry(entry):
                self._ingested_hashes.add(entry.content_hash)
                stored += 1

        self._total_ingested += 1
        self._total_chunks += stored
        if stored:
            log.info("knowledge_ingested", path=path, chunks=stored)
        return stored

    def ingest_directory(self, directory: str, extensions: list[str] | None = None,
                         max_files: int = 100) -> dict:
        """Ingest all supported files in a directory. Returns summary."""
        exts = set(extensions or _READER_MAP.keys())
        files_processed = 0
        total_chunks = 0

        for root, dirs, files in os.walk(directory):
            # Skip hidden dirs, __pycache__, node_modules
            dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__'
                        and d != 'node_modules' and d != '.git']
            for fname in sorted(files):
                if files_processed >= max_files:
                    break
                ext = Path(fname).suffix.lower()
                if ext not in exts:
                    continue
                fpath = os.path.join(root, fname)
                chunks = self.ingest_file(fpath)
                total_chunks += chunks
                files_processed += 1

        return {
            "files_processed": files_processed,
            "chunks_stored": total_chunks,
            "directory": directory,
        }

    def ingest_text(self, text: str, source_type: KnowledgeSource = "documentation",
                    source_label: str = "") -> int:
        """Ingest raw text content. Returns number of chunks stored."""
        chunks = chunk_text(text)
        stored = 0
        for i, chunk in enumerate(chunks):
            entry = KnowledgeEntry(
                content=chunk,
                source_type=source_type,
                source_path=source_label,
                chunk_index=i,
                total_chunks=len(chunks),
            )
            if entry.content_hash not in self._ingested_hashes:
                if self._store_entry(entry):
                    self._ingested_hashes.add(entry.content_hash)
                    stored += 1
        return stored

    def _store_entry(self, entry: KnowledgeEntry) -> bool:
        """Store a knowledge entry in vector memory."""
        try:
            from core.memory.vector_memory import get_vector_memory
            vm = get_vector_memory()
            eid = vm.store_embedding(
                entry.content,
                "long_term_knowledge",
                source=f"ingest:{entry.source_type}",
                importance=0.6,
                confidence=0.7,
                tags=[entry.source_type, entry.metadata.get("format", ""),
                      entry.metadata.get("filename", "")],
            )
            return len(eid) > 0
        except Exception as e:
            log.debug("knowledge_store_failed", err=str(e)[:60])
            return False

    def search_knowledge(self, query: str, source_type: str = "",
                         limit: int = 5) -> list[dict]:
        """Search ingested knowledge."""
        try:
            from core.memory.vector_memory import get_vector_memory
            vm = get_vector_memory()
            results = vm.search_similar(query, memory_type="long_term_knowledge", limit=limit)
            if source_type:
                results = [r for r in results if source_type in str(r.get("tags", []))]
            return results
        except Exception as e:
            log.warning("knowledge_search_failed", err=str(e)[:60])
            return []

    def stats(self) -> dict:
        return {
            "total_files_ingested": self._total_ingested,
            "total_chunks": self._total_chunks,
            "unique_hashes": len(self._ingested_hashes),
            "supported_extensions": list(_READER_MAP.keys()),
        }


# ── Singleton ────────────────────────────────────────────────────────────────

_pipeline: IngestPipeline | None = None

def get_ingest_pipeline() -> IngestPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = IngestPipeline()
    return _pipeline
