# Plan de découpage — `core/meta_orchestrator.py` (2 843 lignes)

Audit 2026-06-10. Fichier le plus gros et le plus actif du repo (modifié la
veille de l'audit) : c'est là que le risque de régression par collision de
modifications est le plus élevé.

## Pourquoi des mixins et pas des modules libres

`MetaOrchestrator` hérite déjà de `CustomMissionHandlerMixin` : le pattern
mixin est établi. Extraire des mixins est un déplacement **mécanique**
(aucune signature ne change, `self` reste le même objet, aucun appelant
externe à modifier, `get_meta_orchestrator()` inchangé). C'est le découpage
au risque minimal pour un fichier sans couverture de tests dédiée complète.

## Découpage cible (5 fichiers, ~600 lignes max chacun)

| Nouveau fichier (core/orchestration/ — paquet existant, pas de nouveau top-level) | Méthodes déplacées | Lignes actuelles |
|---|---|---|
| `routing_mixin.py` | `_classify_mission`, `_match_ai_os_capabilities`, `_route_mission`, `_enrich_kernel_registry`, `_apply_performance_intelligence`, `_kernel_planning` | 422–790 (~370) |
| `execution_mixin.py` | `_execute_reasoning_prepass`, `_execute_creative_mode`, `_execute_supervised`, `_assemble_mission_context` | 321–363, 791–1606 (~860) |
| `outcome_mixin.py` | `_handle_success_outcome`, `_handle_kernel_retry`, `_handle_failed_outcome`, `_handle_awaiting_approval`, `_emit_completion_events` | 1607–1898, 1981–2036, 2134–2232 (~550) |
| `learning_mixin.py` | `_post_mission_learning`, `_store_mission_memories`, `_execute_kernel_learning`, `_record_skills`, `_store_to_memory_facade` | 378–421, 1899–1980, 2037–2133 (~270) |
| `meta_orchestrator.py` (réduit) | `__init__`, propriétés lazy (`bea`, `v2`, `capability_dispatcher`), `_transition`, cycle cognitif, event stream, circuit breaker, `run_mission`, `get_status`, `get_mission`, `resolve_approval`, `recover_from_persistence`, `run`, `check`, `get_meta_orchestrator` | (~800) |

Résultat : `class MetaOrchestrator(RoutingMixin, ExecutionMixin, OutcomeMixin,
LearningMixin, CustomMissionHandlerMixin)`.

Note : `_execute_supervised` fait à elle seule ~756 lignes (851–1606).
Une 2e passe la découpera en étapes privées DANS `execution_mixin.py` —
ne pas mélanger les deux passes.

## Procédure (1 PR par mixin, dans cet ordre)

1. `learning_mixin.py` (le plus petit, le moins couplé) — valide le pattern.
2. `outcome_mixin.py`
3. `routing_mixin.py`
4. `execution_mixin.py` (le plus gros, en dernier, quand le pattern est rodé)

Pour chaque PR :

- Déplacement strict copier/coller (aucune amélioration opportuniste —
  les améliorations viennent après, dans des PR dédiées).
- `from __future__ import annotations` + imports nécessaires dans le mixin ;
  les imports devenus inutiles dans `meta_orchestrator.py` sont retirés
  (ruff F401 le signale).
- Gate avant merge : `ruff check .` + suite pre-push
  (`scripts/validate_local.ps1`) + le fast gate de CONTRIBUTING §3 +
  `pytest tests/ -k "orchestrator or mission" -q`.

## Critère de fin

`core/meta_orchestrator.py` < 900 lignes, aucun fichier du paquet > 900
lignes, comportement identique (aucun test modifié).

## État final — 2026-06-12

Découpage terminé : `MetaOrchestrator` hérite de `RoutingMixin`,
`ExecutionMixin`, `OutcomeMixin`, `LearningMixin` et
`CustomMissionHandlerMixin`. Tous les fichiers ciblés restent sous 900 lignes.
Les tests d'inspection de source ont été adaptés pour suivre les méthodes
héritées sans modifier les assertions comportementales.
