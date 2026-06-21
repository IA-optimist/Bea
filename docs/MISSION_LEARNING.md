# Mission Learning Loop

La **mission learning loop** transforme les rapports de missions exécutées par Béa en mémoires opérationnelles réutilisables. Elle connecte l’agent codeur (Codex) au système de mémoire et au `ModelRouter` pour améliorer les prochaines missions.

## Vue d’ensemble

```text
Rapport de mission (JSON/Markdown)
        │
        ▼
MissionReportParser ──► MissionLearningInput
        │
        ▼
MissionLearner.learn()
 ├── eval_result (toujours)
 ├── model_result (si modèle connu)
 ├── bug_memory  (échec / NEEDS_FIX)
 ├── skill       (succès + lesson)
 ├── test_map    (fichiers × tests)
 └── risk        (risque explicite ou fichier protégé)
        │
        ▼
ModelRouter lit model_result → ajuste prochain choix de classe de modèle
```

## Formats acceptés

- **JSON** : objet avec des clés `snake_case` ou `camelCase`.
- **Markdown structuré** : fallback quand JSON absent.

Champs reconnus :

| Champ | Type | Défaut |
|-------|------|--------|
| `mission_id` | string | `""` |
| `title` | string | `""` |
| `status` | string | `""` |
| `task_type` | string | `""` |
| `files_changed` | list ou CSV | `[]` |
| `tests_run` | list ou CSV | `[]` |
| `success` | bool | déduit de `status` |
| `failure_reason` | string | `""` |
| `model_used` | string | `""` |
| `model_class` | string | `""` |
| `duration_ms` | int | `0` |
| `cost_estimate` | float | `null` |
| `lessons_learned` | string | `""` |
| `risks_detected` | list | `[]` |

Le parseur ne plante jamais ; il ajoute un `warning` par champ critique manquant.

## Mémoires créées

| Mémoire | Quand ? | Contenu |
|---------|---------|---------|
| `eval_result` | toujours | statut, succès, modèle, durée |
| `model_result` | si `model_used` présent | modèle, classe, tâche, succès, coût |
| `bug_memory` | échec / `NEEDS_FIX` | cause, fichiers, tests concernés |
| `skill` | succès + `lessons_learned` | procédure réutilisable |
| `test_map` | fichiers source + tests | association fichiers ↔ tests |
| `risk` | risque explicite ou fichier protégé | zone sensible |

## Déduplication

Avant d’insérer, `MissionLearner` cherche une mémoire existante du même type avec le même `title` (ou `content`) et les mêmes `related_files`. Si elle existe :

- `updated_at` est rafraîchi,
- `confidence` augmente de `0.05` (plafond `1.0`),
- `metadata.occurrence_count` est incrémenté.

Ainsi, relire le même rapport ou un rapport similaire n’engendre pas de doublons.

## Influence sur le ModelRouter

Les `model_result` sont lus par `ModelRouter._history_for_task()` ; une classe de modèle est :

- **favorisée** si son taux de succès sur `task_type` est ≥ 50 % avec assez d’échantillons ;
- **dérioritisée** si elle échoue ≥ 3 fois avec un taux < 34 % ;
- **pénalisée** si son coût moyen dépasse 0.02 $ sans gain proportionnel ;
- **boostée** si `LOCAL_FALLBACK` réussit des tâches simples (`summary`, `retrieve`, etc.).

## Utilisation

```bash
# Un seul rapport
python scripts/ingest_mission_report.py path/to/report.json

# Tout un dossier
python scripts/ingest_mission_report.py reports/

# Sortie JSON
python scripts/ingest_mission_report.py reports/ --json
```

### Exemple Python

```python
from core.evaluation import learn_from_mission_report

result = learn_from_mission_report("path/to/report.json")
print(result.created_memory_ids)
print(result.updated_memory_ids)
```

## Limites actuelles

- Le parser Markdown est minimal.
- Le scoring modèle est heuristique (pas de ML).
- La déduplication repose sur une normalisation textuelle simple ; deux leçons formulées différemment donneront deux `skill`.
- Aucune intégration temps réel avec le runner Codex ; l’ingestion reste explicite.

## Prochaines étapes recommandées

- Connecter `ingest_mission_report` au CI après chaque run agent.
- Enrichir le parser Markdown pour supporter les tableaux.
- Ajouter un replayer qui compare le contexte suggéré par `MissionContextBuilder` avant/après ingestion.
