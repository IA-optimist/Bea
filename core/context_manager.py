"""
BEA MAX v3 — Context Manager & Compressor
Empêche l'agent de crasher pour "Context Length Exceeded" en condensant l'historique.
"""
import structlog
from typing import List, Tuple
from core.events import Event, Action, Observation

log = structlog.get_logger()

class ContextCompressor:
    """Compression dynamique de la fenêtre de contexte Pydantic."""
    
    def __init__(self, max_raw_events: int = 15):
        self.max_raw_events = max_raw_events
        self.global_summary = ""
        self.compressed_index = 0

    def compress_history(self, events: List[Event]) -> Tuple[str, List[Event]]:
        """
        Prend la liste complète des événements en paramètre.
        Garde seulement `max_raw_events` non-compressés (la "short-term memory").
        Tout le reste est fondu dans un `global_summary` (la "medium-term memory").
        
        Retourne (Résumé global, Événements bruts récents)
        """
        total_events = len(events)
        
        if total_events <= self.max_raw_events + self.compressed_index:
            # Pas besoin de nouvelle compression
            return self.global_summary, events[self.compressed_index:]

        # L'index jusqu'où on doit compresser
        target_index = total_events - self.max_raw_events
        batch_to_compress = events[self.compressed_index:target_index]
        
        # Idéalement, on passe `batch_to_compress` dans un appel LLM très rapide (Claude Haiku).
        # "Résume ces N actions passées en un paragraphe concis se focalisant sur les résultats"
        # Pour rester fail-safe, on fait un condenseur textuel heuristique drastique :
        
        textual_compression = []
        for e in batch_to_compress:
            if isinstance(e, Action):
                a_type = getattr(e, "action_type", "unknown")
                textual_compression.append(f"[Action {a_type}]")
            elif isinstance(e, Observation):
                is_err = getattr(e, "is_error", False)
                if is_err:
                    textual_compression.append(" -> ❌ Echec.")
                else:
                    textual_compression.append(" -> ✅ Succès.")
                    
        # Concaténer format condensé
        new_summary = " ".join(textual_compression)
        
        if self.global_summary:
            self.global_summary += f" | Ancien contexte condensé: {new_summary}"
        else:
            self.global_summary = f"Actions passées très résumées: {new_summary}"
            
        self.compressed_index = target_index
        log.info("context_compressed", total=total_events, retained=len(events[self.compressed_index:]))
        
        return self.global_summary, events[self.compressed_index:]
