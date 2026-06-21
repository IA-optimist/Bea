# `bea eval` — Guide

`bea eval` est une suite d’évaluations légères qui vérifie que Béa :

1. utilise sa **mémoire opérationnelle**,
2. exploite son **repo-map**,
3. route vers la **bonne classe de modèle**,
4. gère le **cycle de vie d’une mission** (contexte avant, résultat après),
5. transforme les rapports de mission en mémoires via la **mission learning loop**.

## Lancer les évals

```bash
# Suite complète (25 évals)
python scripts/bea_eval.py

# Liste disponible
python scripts/bea_eval.py --list

# Évals spécifiques
python scripts/bea_eval.py --evals memory-active-decision router-summary-small-fast

# Sortie JSON
python scripts/bea_eval.py --json

# Sortie Markdown
python scripts/bea_eval.py --markdown

# Écrire le rapport
python scripts/bea_eval.py --json --output workspace/bea_eval_last.json
python scripts/bea_eval.py --markdown --output workspace/bea_eval_report.md
```

Depuis Python :

```python
from core.evals.bea_eval import run_and_report

report, markdown = run_and_report()
print(report.overall_score())
```

## Évaluations disponibles

### Mémoire

| Nom | Ce qu’elle vérifie |
|---|---|
| `memory-active-decision` | Retrouver une décision active. |
| `memory-ignore-obsolete` | Une entrée obsolete est déclassée derrière une entrée active. |
| `memory-bug-known` | Retrouver un bug connu par son texte/tags. |
| `memory-risk-protected-file` | Retrouver un risque lié à un fichier protégé. |
| `memory-related-file-boost` | Un `repo_fact` lié au fichier cible est mieux classé. |
| `memory-contradiction-not-preferred` | Une mémoire `replaced` n’est pas préférée. |

### Repo-map

| Nom | Ce qu’elle vérifie |
|---|---|
| `repo-map-symbols` | Trouver classes/fonctions d’un fichier. |
| `repo-map-tests` | Trouver les tests probables d’un fichier. |
| `repo-map-fastapi-route` | Détecter des symboles dans `api/routes/v1.py`. |

### Model routing

| Nom | Ce qu’elle vérifie |
|---|---|
| `router-summary-small-fast` | `summary` → `SMALL_FAST`. |
| `router-simple-patch-medium` | `simple patch` → `MEDIUM_TOOL_USE`. |
| `router-protected-file-strong-review` | `core/auth.py` protégé → `STRONG_CODE_REVIEW`. |
| `router-budget-local-fallback` | `budget_cloud=False` → `LOCAL_FALLBACK`. |

### Mission lifecycle

| Nom | Ce qu’elle vérifie |
|---|---|
| `mission-context-prepare` | Préparer un contexte avec décisions + risques + tests. |
| `mission-result-record` | Stocker eval_result et bug_memory après un échec. |

### Mission learning loop

| Nom | Ce qu’elle vérifie |
|---|---|
| `learning-parse-json-valid` | Parser un rapport JSON de mission. |
| `learning-parse-missing-fields` | Parser un rapport incomplet sans crasher. |
| `learning-create-eval-result` | Créer un eval_result depuis un rapport. |
| `learning-create-bug-memory` | Créer un bug_memory depuis un échec. |
| `learning-create-skill` | Créer un skill depuis une réussite. |
| `learning-create-model-result` | Créer un model_result. |
| `learning-create-test-map` | Créer un test_map. |
| `learning-deduplicate-identical` | Ne pas dupliquer une mémoire identique. |
| `learning-router-after-failures` | Router différemment après des échecs répétés. |
| `learning-ingestion-summary` | Ingestion d’un dossier de rapports avec résumé. |

## Format du rapport JSON

```json
{
  "run_id": "a1b2c3d4",
  "created_at": 1750500000.0,
  "results": [
    {
      "eval_name": "router-summary-small-fast",
      "success": true,
      "score": 1.0,
      "duration_ms": 12,
      "files_used": [],
      "memories_retrieved": [],
      "model_class_selected": "SMALL_FAST",
      "error": null,
      "cost_estimate": null,
      "created_at": 1750500000.0,
      "metadata": {}
    }
  ],
  "summary": {
    "total": 25,
    "passed": 25,
    "failed": 0,
    "overall_score": 0.97
  }
}
```

## Format du rapport Markdown

```bash
python scripts/bea_eval.py --markdown --output workspace/bea_eval_report.md
```

Le rapport contient :

- nombre d’évals, passées/échouées,
- score moyen,
- score par famille (memory, repo-map, router, mission),
- évals en échec avec leur erreur,
- recommandations.

## Comment lire le score

- **Global** : moyenne des scores individuels (0.0–1.0).
- **Par éval** : `1.0` succès complet, `0.5` succès partiel, `0.0` échec.
- `success=false` signifie que le critère n’est pas rempli ; `error` contient l’exception si applicable.

## Stockage des résultats

Chaque run persiste un `MemoryItem(type=eval_result)` dans `OperationalMemoryStore`.

## Ajouter une nouvelle éval

1. Ouvrir `core/evals/bea_eval.py`.
2. Ajouter le nom dans `EVAL_NAMES`.
3. Ajouter `def eval_<nom>(self) -> EvalResult`.
4. L’enregistrer dans `self._evals`.
5. Ajouter un test dans `tests/core/evals/test_bea_eval.py`.

## Dépendances

Aucune dépendance externe. SQLite stdlib, AST stdlib, dataclasses.

## Limites

- Scoring manuel/simple, pas de jugement LLM.
- Repo-map AST Python seulement.
- `cost_estimate` toujours `null` (pas d’appel provider réel).
- FTS5 optionnel.
