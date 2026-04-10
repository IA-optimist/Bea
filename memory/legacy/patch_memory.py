"""
JARVIS MAX — PatchMemory
Mémorise les patchs réussis pour privilégier les patterns qui fonctionnent.

Persistance : fichier JSON dans workspace/memory/ (zéro dépendance DB).
Interface principale :
    pm = PatchMemory(settings)
    pm.record_success(patch, model)
    patterns = pm.get_success_patterns(file)   # → liste de str injectables dans prompt
    stats = pm.get_stats()
"""
from __future__ import annotations

import json
import time
import hashlib
from pathlib import Path
from dataclasses import dataclass, field, asdict
from collections import Counter
import structlog

log = structlog.get_logger()

_MEMORY_FILE = "patch_memory.json"
_MAX_ENTRIES = 1000
_MAX_PATTERNS = 5


@dataclass
class SuccessEntry:
    patch_id:  str
    file:      str
    finding_id: str
    category:  str    # architecture_improvement | bug | security…
    patch_type: str   # replace_in_file | create_file | append_to_file
    old_str:   str
    new_str:   str
    model:     str    # llm model utilisé
    source:    str    # "pre_patch" | "llm"
    ts:        float  = field(default_factory=time.time)

    @property
    def new_str_preview(self) -> str:
        lines = self.new_str.strip().splitlines()
        return lines[0][:120] if lines else "(vide)"

    @property
    def old_str_preview(self) -> str:
        lines = self.old_str.strip().splitlines()
        return lines[0][:120] if lines else "(vide)"

    def pattern_key(self) -> str:
        """Clé de déduplication : catégorie + type + début old_str."""
        return hashlib.md5(
            f"{self.category}|{self.patch_type}|{self.old_str[:80]}".encode()
        ).hexdigest()[:12]


class PatchMemory:
    """
    Stocke les patchs qui ont passé la review et été appliqués avec succès.
    Permet à PatchBuilder de privilégier les patterns déjà validés.

    Exemple de sortie get_success_patterns() :
        === SUCCESSFUL PATTERNS for self_improve/auditor.py ===
        [1] category=architecture_improvement source=pre_patch
            old_str → new_str: async def run( → async def run(  # noqa: C901
        [2] category=bug source=llm
            old_str → except Exception: → except Exception as e:
    """

    def __init__(self, settings):
        self.s       = settings
        self._path   = self._resolve_path()
        self._entries: list[SuccessEntry] = []
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
                self._entries = [SuccessEntry(**e) for e in raw]
                log.debug("patch_memory_loaded", count=len(self._entries))
        except Exception as e:
            log.warning("patch_memory_load_error", err=str(e))
            self._entries = []

    def _save(self):
        try:
            if len(self._entries) > _MAX_ENTRIES:
                self._entries = self._entries[-_MAX_ENTRIES:]
            self._path.write_text(
                json.dumps([asdict(e) for e in self._entries], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            log.warning("patch_memory_save_error", err=str(e))

    # ── API publique ──────────────────────────────────────────

    def record_success(self, patch, model: str = "", source: str = "llm") -> None:
        """
        Enregistre un patch réussi (appliqué après review positive).
        `patch` peut être un PatchSpec ou un dict.
        """
        self._load()

        if hasattr(patch, "__dataclass_fields__"):
            p = {f: getattr(patch, f) for f in patch.__dataclass_fields__}
        elif isinstance(patch, dict):
            p = patch
        else:
            return

        entry = SuccessEntry(
            patch_id   = str(p.get("id",         p.get("patch_id", "?"))),
            file       = str(p.get("file",        "")),
            finding_id = str(p.get("finding_id",  "")),
            category   = str(p.get("category",    "")),
            patch_type = str(p.get("patch_type",  "")),
            old_str    = str(p.get("old_str",     ""))[:500],
            new_str    = str(p.get("new_str",     ""))[:500],
            model      = model[:80],
            source     = source[:40],
        )

        # Dédoublonner : ne pas stocker deux fois le même pattern
        key = entry.pattern_key()
        if any(e.pattern_key() == key for e in self._entries):
            log.debug("patch_memory_duplicate_skipped", key=key)
            return

        self._entries.append(entry)
        self._save()
        log.info("patch_memory_recorded",
                 patch_id=entry.patch_id, file=entry.file, source=source)

    def get_success_patterns(
        self,
        file: str = "",
        category: str = "",
        max_patterns: int = _MAX_PATTERNS,
    ) -> list[str]:
        """
        Retourne les patterns réussis pour un fichier et/ou une catégorie.
        Résultats triés par fréquence d'utilisation.
        """
        self._load()

        filtered = self._entries
        if file:
            filtered = [e for e in filtered if e.file == file]
        if category:
            filtered = [e for e in filtered if e.category == category]

        # Trier par récence
        filtered = sorted(filtered, key=lambda e: e.ts, reverse=True)[:max_patterns]
        return [
            f"[OK] {e.category}/{e.patch_type} | {e.old_str_preview} → {e.new_str_preview}"
            for e in filtered
        ]

    def get_context(self, file: str = "", category: str = "") -> str:
        """
        Retourne un bloc de texte injectable dans le prompt de PatchBuilder.
        Si aucun succès enregistré → retourne chaîne vide.
        """
        patterns = self.get_success_patterns(file=file, category=category)
        if not patterns:
            return ""

        scope = file or category or "global"
        lines = [f"=== SUCCESSFUL PATTERNS for {scope} ==="]
        for i, p in enumerate(patterns, 1):
            lines.append(f"[{i}] {p}")
        lines.append("")
        return "\n".join(lines)

    def get_best_model(self, category: str = "") -> str | None:
        """
        Retourne le modèle LLM qui a le plus de succès pour une catégorie.
        Utile pour choisir le modèle lors de la prochaine tentative.
        """
        self._load()
        filtered = (
            [e for e in self._entries if e.category == category]
            if category else self._entries
        )
        if not filtered:
            return None
        model_counts = Counter(e.model for e in filtered if e.model)
        return model_counts.most_common(1)[0][0] if model_counts else None

    def get_stats(self) -> dict:
        self._load()
        by_file     = Counter(e.file for e in self._entries)
        by_category = Counter(e.category for e in self._entries)
        by_source   = Counter(e.source for e in self._entries)
        by_model    = Counter(e.model for e in self._entries if e.model)
        return {
            "total":       len(self._entries),
            "by_file":     dict(by_file.most_common(10)),
            "by_category": dict(by_category.most_common(10)),
            "by_source":   dict(by_source),
            "by_model":    dict(by_model.most_common(5)),
        }

    def clear(self):
        """Vide la mémoire (utile pour les tests)."""
        self._entries = []
        self._loaded  = True
        self._save()
