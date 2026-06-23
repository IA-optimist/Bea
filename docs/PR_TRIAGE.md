# PR & Issues Triage
**Mis à jour :** 2026-06-23  
**Audit :** Claude Opus (cross-audit session)  
**Source :** `gh pr list --state open` + `gh issue list --state open` + lecture directe

---

## PRs ouvertes — Ordre de merge recommandé

### Tier 1 — Merger en premier (bloquants ou faible risque)

| PR | Titre | Pourquoi en premier | Action |
|----|-------|---------------------|--------|
| #95 | Dependabot: bump runtime group (6 deps) | Sécurité, CI-validé automatiquement | Vérifier CI verte, merger |
| #60 | Dependabot: bump test-tooling group (4 deps) | Test isolation, faible risque | Vérifier CI, merger |
| **Ce PR** | Audit truth map + runtime triage | Corrections docs + STATUS.md | Merger après review |

### Tier 2 — Méritent review humaine avant merge

| PR | Titre | Note | Action |
|----|-------|------|--------|
| #112 | fix(eval): stabilize bea_eval + completion truth gates | Corrige la gate P0-TRUTH-1. Important pour public beta | Review + test local bea_eval |
| #94 | docs(flutter): validate v3 migration + APK rebuild | Documente le state APK ; n'inclut pas le rebuild réel | Merger si la doc est correcte, noter que l'APK reste à faire |
| #93 | fix(scripts): Windows Unicode + --dry-run alpha diagnostics | Qualité scripts, faible risque | Review rapide, merger |

### Tier 3 — À rebaser/revalider (potentiellement stale)

| PR | Titre | Problème | Action |
|----|-------|---------|--------|
| #68 | Fix remaining Dependabot dependency alerts | Peut être dépassé par #95/#60 | Vérifier si encore pertinent après merge #95/#60 ; rebaser ou fermer |
| #27 | docs(security): audit deps pip-audit + P0/P1/P2 | Du contenu de cet audit est maintenant plus à jour | Fermer ou archiver ; référencer ce PR et l'audit 2026-06-23 |

### Tier 4 — Dependabot Flutter (pub) — À traiter ensemble

| PR | Titre | Action |
|----|-------|--------|
| #39 | flutter_secure_storage 9→10 | Merger après test APK rebuild |
| #38 | flutter_local_notifications 17→21 | Merger après test APK rebuild |
| #37 | web_socket_channel 2→3 | Merger après test APK rebuild |
| #36 | stripe 8→15 | Tester l'API Stripe (breaking changes possibles) |

**Note Flutter:** les 4 PRs pub doivent être testés ensemble sur un APK rebuild. Ne pas merger séparément sans vérifier la compatibilité Dart/Gradle.

---

## Issues ouvertes — Triage

### Issues critiques à garder ouvertes (actives)

| Issue | Titre | Priorité | Statut réel |
|-------|-------|----------|-------------|
| **#14** | Rotate 37 historical secret tokens (gitleaks) | **P0** | Non confirmé comme résolu. Vérifier token par token. |
| **#12** | Split god objects (meta_orchestrator / api/main / crew) | P0-tech | Partiellement résolu : MetaOrchestrator est splitté en mixins. api/main reste large. Mettre en P1 si le split mixins satisfait l'audit. |

### Issues à fermer / mettre à jour

| Issue | Titre | Raison | Action |
|-------|-------|--------|--------|
| **#13** | Bump fastapi 0.109 → 0.115+ / starlette 0.40+ (CVE-2024-47874) | **RÉSOLU** : fastapi==0.137.1, starlette==1.3.1 en requirements.txt | Fermer avec note "Résolu dans requirements.txt, validé 2026-06-23" |
| **#16** | Code quality: mypy strict + contracts + print→structlog | Partiellement résolu : mypy strict sur auth/kernel en CI, delta gate actif. print→structlog P2 reste | Mettre à jour le titre, conserver pour la partie non résolue |
| **#17** | Configure repo secrets for Auto Deploy VPS1 workflow | Hors scope audit. Deploy VPS = feature, pas dette runtime | Garder ouvert, label P2 |

### Issues stale à documenter

| Issue | Note |
|-------|------|
| #15 | Lié à Audit S8 (orchestrator_v2 legacy) — **RÉSOLU** dans le code. Vérifier si l'issue est déjà fermée. |

---

## Ordre recommandé pour les agents (Codex / Claude / KiloCode)

### Pour Codex (cerveau Béa, missions business)
1. Vérifier et clore issue #13 (FastAPI CVE)
2. Merger #95 et #60 (dependabot runtime + test-tooling)
3. Merger #94 (flutter docs)

### Pour Claude (audit, architecture, qualité)
1. Merger ce PR (cross-audit truth map)
2. Review #112 (bea_eval + completion truth)
3. Fix P1-POLICY : corriger l'import `core.policy.policy_engine` dans `tool_executor.py`
4. Mettre à jour issue #12 avec l'état réel du split

### Pour KiloCode (refactor, cleanup)
1. Merger #93 (Windows Unicode)
2. Traiter Flutter deps (#37, #38, #39) après APK rebuild
3. Consolider les 4 copies de `_check_auth` en P2

---

## Actions hors-PR (non-code)

| Action | Responsable | Priorité |
|--------|-------------|----------|
| Rotation tokens issue #14 | Max (manuelle) | **P0** |
| Rebuild APK Flutter + install Pixel 7 | Max | P1 |
| Confirmer statut gitleaks scan sur main actuel | CI automatique | P0 |
