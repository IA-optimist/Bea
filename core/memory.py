"""
JARVIS MAX v3 — Long-Term Episodic Memory
Permet à l'agent de ne pas répéter les mêmes erreurs de syntaxe, ou de se souvenir
des configurations systèmes spécifiques utiles à sa survie.
"""
import json
import os
import structlog
from pathlib import Path

log = structlog.get_logger()

class MemoryBank:
    """Base de données locale (JSON) des leçons apprises (RAG basique contextuel)."""
    
    def __init__(self, db_path: str = "workspace/.jarvis_memory.json"):
        self.db_path = Path(db_path).absolute()
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            _silent_log.debug("suppressed_exception", src='memory.py')
        self.memories = self._load()

    def _load(self) -> list[dict]:
        if not self.db_path.exists():
            return []
        try:
            with open(self.db_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log.error("memory_load_failed", error=str(e))
            return []

    def _save(self):
        try:
            with open(self.db_path, "w", encoding="utf-8") as f:
                json.dump(self.memories, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log.error("memory_save_failed", error=str(e))

    def add_lesson(self, error_context: str, successful_solution: str):
        """Mémorise qu'une solution a corrigé un problème spécifique."""
        self.memories.append({
            "context": error_context,
            "solution": successful_solution
        })
        self._save()
        log.info("memory_saved", context=error_context[:30])

    def query(self, current_problem: str, limit: int = 2) -> str:
        """
        Trouve les mémoires pertinentes par un Jaccard index / Token Overlap (TF-IDF rudimentaire).
        Évite d'utiliser une lib énorme comme ChromaDB pour rester léger.
        """
        if not self.memories:
            return ""
            
        words = set(current_problem.lower().replace('.', ' ').replace('_', ' ').split())
        words = {w for w in words if len(w) > 3} # Pseudo stop-words removal
        
        scored = []
        for mem in self.memories:
            mem_words = set(mem["context"].lower().replace('.', ' ').replace('_', ' ').split())
            score = len(words.intersection(mem_words))
            scored.append((score, mem))
            
        scored.sort(key=lambda x: x[0], reverse=True)
        best = [m[1] for m in scored if m[0] > 0][:limit] 
        
        if not best:
            return ""
            
        out = "\\n\\n[MÉMOIRE] Il semble que j'ai déjà rencontré un problème similaire :\\n"
        for b in best:
            out += f"- Scénario : {b['context']}\\n  Solution trouvée : {b['solution']}\\n"
        return out
