# Plan d’exécution post-audit — Bea (P0 / P1 / P2)

## Objectif
Transformer les résultats d’audit en exécution incrémentale, avec risques réduits rapidement et sans bloquer la livraison.

## PR-1 (P0) — Alignement doc & onboarding dev

### But
Supprimer l’ambiguïté structurelle et réduire le temps d’onboarding.

### Scope
- Mettre à jour `README.md` racine pour refléter la structure réelle.
- Clarifier les commandes de bootstrap local (Python, frontend, mobile, Docker).
- Clarifier commandes de tests/lint minimales.

### Critères d’acceptation
- README cohérent avec arborescence actuelle.
- Un nouveau développeur peut démarrer localement sans hypothèses cachées.

---

## PR-2 (P0/P1) — Sécurité dépendances (lot contrôlé)

### But
Réduire la surface CVE en traitant les dépendances signalées “deferred”.

### Scope
- Auditer et planifier les upgrades prioritaires (`fastapi/starlette`, `cryptography`, `pytest` et transitives critiques).
- Faire les upgrades par petits lots compatibles.
- Valider via tests ciblés + collecte globale.

### Critères d’acceptation
- Diminution mesurable des vulnérabilités connues.
- Pas de régression fonctionnelle sur suites de tests ciblées.

---

## PR-3 (P1) — Durcissement exécution & hygiène repo

### But
Réduire les risques opérationnels et améliorer la maintenabilité.

### Scope
- Réduire/encadrer strictement les chemins `shell=True` encore nécessaires.
- Refactor `/.gitignore` (déduplication + sections).
- Proposer un guide “deploy hardening” (utilisateur non-root, principe du moindre privilège).

### Critères d’acceptation
- Surface exécution shell diminuée ou davantage contrainte.
- `.gitignore` lisible, non redondant.
- Recommandations deploy documentées et actionnables.

---

## Ordonnancement recommandé
1. PR-1 immédiatement (faible risque, gain rapide).
2. PR-2 en lots progressifs avec validations.
3. PR-3 en parallèle partiel (doc + hygiène), puis durcissement code.

## Validation transversale
- `ruff check .`
- `pytest -q tests/test_v1_invariants.py tests/test_tool_registry.py tests/test_policy_engine.py`
- `pytest --collect-only -q`

## Notes
- Toute valeur sensible doit rester hors dépôt (`.env`, secrets GitHub Actions, vault).
- Les changements de sécurité critiques se font via PR dédiée avec rollback simple.
