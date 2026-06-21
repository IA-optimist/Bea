# Taxonomie mémoire opérationnelle de Béa

Ce document définit les types d’entrées mémoire que Béa manipule pour devenir un agent codeur guidé par la mémoire.  
Il est **additif** : il ne remplace pas `memory/schemas.py` ni `core/memory/memory_schema.py`. Il fournit un vocabulaire opérationnel pour `core/memory/memory_item.py` et `core/evals/`.

## Vue d’ensemble

Béa mémorise ce qui aide à agir :

- fichiers et patterns importants du repo
- décisions architecturales (ADRs)
- bugs connus et leur correction
- tests liés aux modules
- erreurs passées et solutions validées
- skills réutilisables
- résultats d’évaluation
- choix de modèles efficaces
- résultats et leçons tirées des missions exécutées

## Types de mémoire

| Type | Usage | Exemple |
|---|---|---|
| `repo_fact` | Fait consolidé sur le code source | `api/routes/v1.py` est la façade canonique v1. |
| `bug_memory` | Bug ou piège connu | `core/observability.py` peut masquer `core/observability/`. |
| `architecture_decision` | Décision d’architecture / policy | Les patchs self-improvement critiques passent en review humaine. |
| `test_map` | Lien entre un module et ses tests | `tests/api/test_routes.py` couvre le registre API. |
| `skill` | Procédure réutilisable | Corriger un routeur FastAPI dupliqué. |
| `risk` | Risque opérationnel ou sécurité | GitAgent indisponible = jamais PROMOTE. |
| `model_result` | Performance d’un modèle sur une tâche | tel modèle réussit mieux les tâches de refactor léger. |
| `eval_result` | Résultat d’une évaluation `bea eval` | `bea eval code-simple` score 0.82. |
| `fun_fact` | Fait léger / anecdote personnelle, non utilisable pour décider | Max aime que Béa retienne qu'il est l'amour de la vie de sa petite amie. |
| `project_fact` | Fait vérifié sur le projet ou l’équipe, pas sur le code seul | Béa a été créée et entraînée par Max. |

## Schéma `MemoryItem`

Chaque entrée mémoire typée est normalisée dans un `MemoryItem` minimal :

```python
class MemoryItem:
    id: str
    type: MemoryItemType
    title: str
    content: str
    status: MemoryItemStatus
    confidence: float  # 0.0–1.0
    source: str
    related_files: list[str]
    related_tests: list[str]
    created_at: float  # epoch
    updated_at: float  # epoch
    supersedes: list[str]   # ids des entrées remplacées
    superseded_by: str | None
    tags: list[str]
    metadata: dict  # peut contenir importance, privacy, not_for_decision, occurrence_count
```

### Statuts possibles

- `active` — entrée valide et utilisable par défaut.
- `obsolete` — remplacée par une autre, ne pas préférer sauf contexte historique.
- `replaced` — synonyme opérationnel d’`obsolete` (alias dans le code).
- `unverified` — information potentiellement utile mais pas encore confirmée.
- `dangerous` — entrée signalant un risque (bloquant, règle de sécurité).

### Conventions

- `type` est obligatoire et fait partie de `MemoryItemType`.
- `status` vaut `active` par défaut au moment de la création.
- `confidence` = 0.5 par défaut ; 1.0 pour un fait vérifié passé en CI.
- `related_files` et `related_tests` stockent des chemins relatifs au repo.
- `tags` permettent le filtrage rapide (`api`, `v1`, `fastapi`, `deprecated`, etc.).
- Une entrée peut être liée à une mission via `source` (`mission:{id}`) ou via `metadata["mission_id"]`.
- `metadata` accepte `importance` (`low`/`medium`/`high`), `privacy` (`personal`), `not_for_decision` (`true`) et `occurrence_count`.

## Stockage

- **Structuré / exact** : `OperationalMemoryStore` (SQLite), pour les recherches par `type`, `status`, `related_files`, `tags`, dates.
- **Sémantique** : Qdrant / `VectorMemory` via `MemoryBus` ou `MemoryFacade`, pour les recherches par similarité textuelle.
- **Fallback** : JSONL dans `workspace/` via `MemoryFacade`, si SQLite n’est pas disponible.

## Mémoire active

La mémoire n’est pas seulement stockée : elle est utilisée.

- **Avant mission** : `MissionContextBuilder` ( `core/memory/mission_context.py` ) recherche décisions, risques, repo_fact, tests et bug_memory pertinents pour constituer un contexte.
- **Routing modèle** : `ModelRouter` ( `core/evaluation/model_router.py` ) choisit la classe de modèle adaptée au `task_type`, aux fichiers protégés et aux `model_result` passés.
- **Après mission** : `MissionResultRecorder` ( `core/memory/mission_result.py` ) et `MissionLearner` ( `core/evaluation/mission_learning.py` ) créent automatiquement `eval_result`, `model_result`, `bug_memory` (échec), `skill` (succès répétable), `test_map`, `risk` et mettent à jour les scores du routeur.

## Cycle de vie

1. **Création** : issue ou mission → `MemoryItem` créé par agent ou script.
2. **Recherche** : `OperationalMemoryStore.search(...)` combine filtres exacts + LIKE/FTS.
3. **Mise à jour** : mise à jour de `status`, `confidence`, `updated_at`, `superseded_by`.
4. **Obsolescence** : quand une décision change, l’ancienne entrée passe à `obsolete` et la nouvelle référence `supersedes`.

## Notes spécifiques par type

### `repo_fact`
- Produit par le repo-map (`core/repo_map/repo_map_service.py`).
- Doit citer une source de vérité (fichier analysé, commit, ligne de détection).

### `bug_memory`
- Doit indiquer le symptôme, la cause racine et la correction validée si connue.
- `status = dangerous` si la non-connaissance du bug peut entraîner une régression.

### `architecture_decision`
- Miroir des ADRs dans `docs/decisions/`.
- `confidence` élevé (> 0.8) si validé par review.

### `test_map`
- Produit par `RepoMapService` quand un test partage un préfixe ou une cible de module.
- Permet à l’agent codeur de proposer les tests pertinents.

### `skill`
- Description d’une procédure ou pattern réutilisable.
- Peut être enrichi par des `repo_fact` et `test_map` liés.

### `risk`
- Produit par les audits, policy kernel, ou échecs passés.
- Doit avoir `status = dangerous` ou `active`.

### `model_result`
- Résultat d’une comparaison de modèles.
- `metadata` peut contenir `model`, `task_type`, `score`, `cost_usd`.

### `eval_result`
- Résultat d’une run `bea eval`.
- `content` contient le JSON court ; `metadata["eval_name"]`, `metadata["score"]`, `metadata["duration_ms"]`.

## Exemple minimal

```python
from core.memory.memory_item import MemoryItem, MemoryItemType, MemoryItemStatus
from core.memory.operational_memory import get_operational_memory_store

store = get_operational_memory_store()
item = MemoryItem(
    type=MemoryItemType.REPO_FACT,
    title="Façade v1 canonique",
    content="api/routes/v1.py est la façade canonique v1.",
    related_files=["api/routes/v1.py"],
    related_tests=["tests/api/test_routes.py"],
    tags=["api", "v1", "canonical"],
    source="repo_map",
    confidence=0.95,
)
store.add(item)
results = store.search(type=MemoryItemType.REPO_FACT, tags=["v1"])
```
