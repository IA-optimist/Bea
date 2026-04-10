"""
JARVIS MAX — FailureMemory
Mémorise les patchs rejetés pour éviter de reproduire les mêmes erreurs.

Persistance : fichier JSON dans workspace/memory/ (zéro dépendance DB).
Interface principale :
    fm = FailureMemory(settings)
    fm.record_rejection(patch, reason)      # enregistre un rejet
    fm.get_context(file)                    # retourne contexte injectables dans PatchBuilder
    fm.has_failed_before(patch)             # True si old_str déjà rejeté
"""
from __future__ import annotations

import json
import time
import hashlib
from pathlib import Path
from dataclasses import dataclass, field, asdict
import structlog

log = structlog.get_logger()

_MEMORY_FILE = "failure_memory.json"
_MAX_ENTRIES = 500      # limite pour éviter croissance illimitée
_MAX_PER_FILE = 10      # max rejets affichés par fichier dans le contexte


@dataclass
class FailureEntry:
    patch_id:   str
    file:       str
    finding_id: str
    old_str:    str
    new_str:    str
    reason:     str
    category:   str   = ""    # architecture_improvement | bug | security…
    model:      str   = ""    # modèle LLM qui a généré le patch
    ts:         float = field(default_factory=time.time)

    @property
    def old_str_preview(self) -> str:
        lines = self.old_str.strip().splitlines()
        return lines[0][:120] if lines else "(vide)"

    def signature(self) -> str:
        """Hash stable pour dédoublonner les échecs identiques."""
        return hashlib.md5(
            f"{self.file}|{self.old_str[:200]}|{self.reason[:80]}".encode()
        ).hexdigest()[:12]


class FailureMemory:
    """
    Stocke les patchs rejetés afin de les injecter comme contexte
    dans PatchBuilder avant la prochaine génération LLM.

    Format du contexte injecté (str) :
        === PREVIOUS FAILURES for self_improve/auditor.py ===
        [1] SyntaxError : unexpected indent
            old_str: async def run(
        [2] no_old_str : old_str vide après extraction
            old_str: (vide)
    """

    def __init__(self, settings):
        self.s = settings
        self._path = self._resolve_path()
        self._entries: list[FailureEntry] = []
        self._loaded = False

    # ── Chemin de persistance ─────────────────────────────────

    def _resolve_path(self) -> Path:
        base = Path(getattr(self.s, "workspace_dir", "/app/workspace"))
        mem_dir = base / "memory"
        mem_dir.mkdir(parents=True, exist_ok=True)
        return mem_dir / _MEMORY_FILE

    # ── Chargement / sauvegarde ───────────────────────────────

    def _load(self):
        if self._loaded:
            return
        self._loaded = True
        try:
            if self._path.exists():
                raw = json.loads(self._path.read_text("utf-8"))
                self._entries = [FailureEntry(**e) for e in raw]
                log.debug("failure_memory_loaded", count=len(self._entries))
        except Exception as e:
            log.warning("failure_memory_load_error", err=str(e))
            self._entries = []

    def _save(self):
        try:
            # Tronquer si trop grand
            if len(self._entries) > _MAX_ENTRIES:
                self._entries = self._entries[-_MAX_ENTRIES:]
            self._path.write_text(
                json.dumps([asdict(e) for e in self._entries], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            log.warning("failure_memory_save_error", err=str(e))

    # ── API publique ──────────────────────────────────────────

    def record_rejection(self, patch, reason: str, model: str = "") -> None:
        """
        Enregistre un rejet de patch.
        `patch` peut être un PatchSpec ou un dict avec les mêmes champs.
        """
        self._load()

        # Normaliser patch → dict
        if hasattr(patch, "__dataclass_fields__"):
            p = {f: getattr(patch, f) for f in patch.__dataclass_fields__}
        elif isinstance(patch, dict):
            p = patch
        else:
            log.warning("failure_memory_unknown_type", type=type(patch).__name__)
            return

        entry = FailureEntry(
            patch_id   = str(p.get("id",         p.get("patch_id", "?"))),
            file       = str(p.get("file",        "")),
            finding_id = str(p.get("finding_id",  "")),
            old_str    = str(p.get("old_str",     "")),
            new_str    = str(p.get("new_str",     ""))[:500],
            reason     = reason[:300],
            category   = str(p.get("category",   "")),
            model      = model[:80],
        )

        # Dédoublonner : ne pas stocker deux fois la même signature
        sig = entry.signature()
        if any(e.signature() == sig for e in self._entries):
            log.debug("failure_memory_duplicate_skipped", sig=sig)
            return

        self._entries.append(entry)
        self._save()
        log.info("failure_memory_recorded",
                 patch_id=entry.patch_id, file=entry.file, reason=reason[:60])

    def has_failed_before(self, patch, threshold: int = 1) -> bool:
        """
        Retourne True si un patch similaire (même file + old_str) a déjà été rejeté
        au moins `threshold` fois.
        """
        self._load()
        if hasattr(patch, "__dataclass_fields__"):
            file    = getattr(patch, "file", "")
            old_str = getattr(patch, "old_str", "")
        elif isinstance(patch, dict):
            file    = patch.get("file", "")
            old_str = patch.get("old_str", "")
        else:
            return False

        count = sum(
            1 for e in self._entries
            if e.file == file and e.old_str[:100] == old_str[:100]
        )
        return count >= threshold

    def get_context(self, file: str, max_entries: int = _MAX_PER_FILE) -> str:
        """
        Retourne un bloc de texte injectable dans le prompt de PatchBuilder.
        Si aucun échec enregistré pour ce fichier → retourne chaîne vide.

        Format :
            === PREVIOUS FAILURES for <file> ===
            [1] SyntaxError : unexpected indent
                old_str: async def run(
        """
        self._load()

        relevant = [e for e in self._entries if e.file == file]
        if not relevant:
            return ""

        # Les plus récents en premier
        relevant = sorted(relevant, key=lambda e: e.ts, reverse=True)[:max_entries]

        lines = [f"=== PREVIOUS FAILURES for {file} ==="]
        for i, e in enumerate(relevant, 1):
            lines.append(f"[{i}] {e.reason[:120]}")
            lines.append(f"    old_str: {e.old_str_preview}")
        lines.append("")

        return "\n".join(lines)

    def get_all_files_with_failures(self) -> list[str]:
        """Liste les fichiers qui ont au moins un échec enregistré."""
        self._load()
        return list({e.file for e in self._entries})

    def get_stats(self) -> dict:
        self._load()
        from collections import Counter
        by_file = Counter(e.file for e in self._entries)
        by_reason = Counter(e.reason.split(":")[0].strip() for e in self._entries)
        return {
            "total":     len(self._entries),
            "files":     dict(by_file.most_common(10)),
            "top_reasons": dict(by_reason.most_common(5)),
        }

    def clear(self):
        """Vide la mémoire (utile pour les tests)."""
        self._entries = []
        self._loaded  = True
        self._save()
