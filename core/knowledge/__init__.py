"""
core/knowledge — Knowledge & Capability Engine pour Bea.

Modules:
  knowledge_index      — Enregistrement entrées + indexation Qdrant (bea_knowledge)
  pattern_detector     — Détection similarités + séquences efficaces
  capability_scorer    — Score par domaine (coding, debugging, planning…)
  knowledge_cleanup    — Merge/suppression patterns obsolètes
  memory_quality       — Score de qualité mémoire (0–1, anti-pattern detection)
  difficulty_estimator — Estimation de difficulté avant planification (LOW→VERY_HIGH)

Tous les imports sont fail-open (try/except ImportError).
Tous les appels Qdrant sont non-bloquants (timeout ≤ 3s).
"""
