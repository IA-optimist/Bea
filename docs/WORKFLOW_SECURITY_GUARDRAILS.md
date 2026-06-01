# Workflow Security Guardrails (P1)

Ce document cadre la protection des workflows GitHub Actions sensibles.

## Objectif
Empêcher les modifications non revues des pipelines CI/CD et réduire le risque supply-chain.

## Contrôles à activer (Settings GitHub)

### 1) Branch protection (main)
- ✅ Require a pull request before merging
- ✅ Require approvals: **minimum 1** (idéal 2)
- ✅ Require review from Code Owners
- ✅ Dismiss stale pull request approvals when new commits are pushed
- ✅ Require status checks to pass before merging
- ✅ Require branches to be up to date before merging
- ✅ Include administrators

### 2) Ruleset ciblé workflows
Cibler :
- `.github/workflows/**`
- `.github/actions/**`

Règles recommandées :
- ✅ Pull request obligatoire
- ✅ Au moins 1 approbation
- ✅ Code owner review obligatoire
- ✅ Interdire force-push
- ✅ Interdire suppression de branche protégée

### 3) Actions permissions (repo)
Dans `Settings → Actions → General` :
- ✅ Workflow permissions: **Read repository contents and packages permissions**
- ❌ Disable "Allow GitHub Actions to create and approve pull requests"

### 4) Fork pull requests
- ✅ Require approval for first-time contributors
- ✅ Require approval for all outside collaborators

## Validation rapide
- Ouvrir une PR qui modifie `.github/workflows/*`.
- Vérifier que :
  - les Code Owners sont demandés,
  - la fusion est bloquée sans review.

## Notes
- Les garde-fous repo-level ne peuvent pas être appliqués directement dans un commit ; ce fichier sert de référence opérationnelle.
