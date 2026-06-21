# Mémoire hygiène — memory-hygiene-dedup-ranking

Ce document explique comment garder la mémoire opérationnelle de Béa utile, silencieuse et sûre.

## Pourquoi l'hygiène mémoire est nécessaire

Un store trop dense crée plusieurs problèmes :

* **Bruit** : plus de 27 000 mémoires augmentent le risque de remonter une information faiblement pertinente.
* **Doublons** : un même rapport ingéré plusieurs fois génère des entrées quasi-identiques.
* **Obsolescence** : une décision remplacée reste retournable si le ranking ne pénalise pas `obsolete`/`replaced`.
* **Fuites contextuelles** : un `fun_fact` ou `private_joke` personnel peut être proposé dans une mission technique.
* **Mémoires sans source/confidence** : difficile à auditer et à valoriser.

## Auditer le store

```bash
# Console lisible (read-only par défaut)
python scripts/audit_memory_store.py

# Mode dry-run explicite (identique au défaut ; utile en checklist)
python scripts/audit_memory_store.py --dry-run

# JSON
python scripts/audit_memory_store.py --json

# Écriture fichier
python scripts/audit_memory_store.py --json --output workspace/memory_audit.json
```

L'audit est **read-only** par défaut — aucune mémoire n'est modifiée. Le flag
`--dry-run` est équivalent et peut être utilisé pour rendre l'intention explicite
dans des scripts ou une checklist. La sortie affiche toujours le mode en tête :

```
Mode : dry-run (read-only, no changes)
```

L'audit fournit :

* nombre total de mémoires
* répartition par type et status
* top tags
* compteurs `low_importance`, `obsolete/replaced`, `unverified`
* doublons potentiels
* mémoires sans source ou sans confidence
* contenus trop courts ou trop longs
* top risques de bruit

### Appliquer un nettoyage (DESTRUCTIF)

```bash
# Vérifier d'abord en dry-run
python scripts/audit_memory_store.py --dry-run

# Backup recommandé avant --apply
python scripts/backup_db.sh

# Appliquer : mark-as-pruned sur les obsolete sans successeur de +90 jours
python scripts/audit_memory_store.py --apply
```

> ⚠️ `--apply` est l'unique mode destructif. `--dry-run` l'annule même s'il est
> passé en même temps (`--dry-run --apply` reste read-only).

Aucune suppression physique n'est possible sans le flag `--apply` explicite.

## Cycle de maintenance après ingestion

Après avoir ingéré un batch de rapports :

```bash
python scripts/ingest_mission_report.py reports/
python scripts/audit_memory_store.py
```

Si le taux de doublons dépasse 5 %, examiner les premières paires signalées. Relancer l'ingestion d'un fichier identique mettra à jour `occurrence_count` au lieu de créer une nouvelle entrée.

## Déduplication

La déduplication est gérée par `MissionLearner._create_or_update()` (core/evaluation/mission_learning.py) :

* critères : type, title normalisé, content normalisé, related_files, mission_id
* si doublon : pas de nouvelle entrée, `updated_at` rafraîchi, `confidence += 0.05` (plafond 1.0), `occurrence_count++`
* le slug de comparaison est passé de 120 à 200 caractères pour réduire les faux négatifs

L'audit indépendant (`_scan_duplicates`) détecte aussi les doublons existants dans le store.

## Ranking

`OperationalMemoryStore.ranked_search()` calcule un score par item :

| Signal | Poids | Sens |
|---|---|---|
| `active` | +1.0 | toujours favoriser les entrées actives |
| `confidence` | × 0.6 | élevé = meilleur |
| `related_file_match` | +0.8 | fichier en commun |
| `related_test_match` | +0.5 | test en commun |
| `tag_match` | +0.4 | tag en commun |
| `trusted_source` | +0.2 | audit, security/policy, ci, repo_map, bea_eval |
| `recency` | +0.3 × exp(-age/30j) | récent mieux |
| `obsolete` / `replaced` | -2.0 | fortement pénalisé |
| `unverified` | -0.5 | dépriorisé |
| `low_importance` | -0.7 | moins visible sauf contexte léger |
| `no_source` | -0.4 | mémoire orpheline pénalisée |
| `private_joke` | -1.5 | exclu des missions sérieuses |
| `old` (>365j) | -0.2 | pénalité de vieillesse |

L'option `include_obsolete=False` filtre les status `obsolete`/`replaced`. L'option `include_private_joke=False` filtre les `fun_fact`/`private_joke` sauf si la requête contient des mots légers (`fun`, `joke`, `humour`, `personal`, `light`, `max`, `béa`, `romance`, etc.).

## `fun_fact` et `private_joke`

* `type = fun_fact`
* tags : `private_joke`, `humour`, `romance` si pertinent
* `importance = low`
* `privacy = personal`
* `not_for_decision = true`
* doivent avoir `source` explicite (`seed:fun_fact`, `user:max`, etc.)

Règles de récupération :

* Mission "analyse API v3" → ne jamais remonter le fun fact romantique.
* Mission "dis un fun fact sur Max" → peut remonter.

Le fun fact attendu est :

> Max aime que Béa retienne qu'il est l'amour de la vie de sa petite amie.

L'entrée « Max est le seul humain qui a créé et entraîne Béa » est classée `project_fact`, pas `fun_fact` ni `private_joke`, car c'est une vérité factuelle sur le projet.

## Éviter qu'une mémoire personnelle influence une décision technique

Trois mécanismes sont en place :

1. `is_not_for_decision` sur `MemoryItem` détecte `not_for_decision=true`, `usage_rule=light_context_only`, ou les tags `private_joke`/`fun_fact`.
2. `_is_light_context()` dans le ranking inspecte les mots de la requête pour décider si la mission est humoristique/personnelle.
3. Si le contexte n'est pas léger, les items marqués `private_joke`/`fun_fact` sont filtrés et fortement pénalisés.

## Status

* `active` — entrée valide par défaut.
* `obsolete` / `replaced` — remplacée, fortement pénalisée.
* `unverified` — information potentielle mais non confirmée.
* `dangerous` — risque ; surfacé explicitement dans `MissionContextBuilder`.

## Confidence et importance

* `confidence` 0.0–1.0 ; 1.0 pour un fait validé.
* `importance` 0.0–1.0 ; une valeur < 0.3 ou `metadata["importance"] == "low"` pénalise le score.

## Commandes de validation

```bash
# Lint
python -m ruff check scripts/audit_memory_store.py core/memory/operational_memory.py core/memory/memory_item.py core/evaluation/mission_learning.py scripts/seed_bea_memory.py

# Tests mémoire
python -m pytest tests/core/memory -q

# Tests évaluation liés
python -m pytest tests/core/evaluation -q

# Audit dry-run
python scripts/audit_memory_store.py

# bea eval
python scripts/bea_eval.py --json
```

## Limites et prochaines étapes

* Le scan de doublons est quadratique O(n²) ; OK pour quelques dizaines de milliers d'items, à surveiller au-delà.
* Pas de suppression réelle d'items ; le nettoyage se fait par mark-pruned.
* Pas d'intégration automatique post-ingestion dans le CI.
* Amélioration possible : classification automatique `low_importance`/private via un modèle léger.
