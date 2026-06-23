# Cross-Audit Truth Map — Opus × Codex
**Date:** 2026-06-23  
**Branch:** `claude/audit-truth-map-and-runtime-triage`  
**Auditor:** Claude Opus (Sonnet 4.6)  
**Gate evidence:** `validate_local.py --quick` → ALL PASS; `smoke_e2e_cycle.py --fixture sha256 --skip-bea-eval` → PASS

---

## Methodology

Direct code reading + import probing + git-verified docs. No LLM speculation about runtime behaviour.

---

## Truth Table

| Affirmation | Source | Verdict | Impact | Action |
|---|---|---|---|---|
| MetaOrchestrator est le seul point d'entrée | ARCHITECTURE.md, meta_orchestrator.py:1 | **VRAI** | — | Rien |
| OrchestratorV2 a un import legacy cassé | Audit précédent (pré-S8) | **FAUX (corrigé S8 2026-05-20)** | — | Doc à jour dans orchestrator_v2.py |
| OrchestratorV2 importe sans erreur | Import probe | **VRAI** | — | — |
| `tool_executor` vérifie ExecutionPolicy à runtime | tool_executor.py:733 | **FAUX (fail silencieux)** | P1 | Voir § Enjeux runtime |
| `core.policy.policy_engine.get_policy_engine` existe | Import probe | **FAUX** (mauvais chemin ET fonction absente) | P1 | Voir § Enjeux runtime |
| BeaOrchestrator est mort / legacy | Audit précédent | **FAUX** | — | Vivant dans core/bea_executor.py |
| `from core.bea_orchestrator import BeaOrchestrator` fonctionne | Import probe | **FAUX** (module absent) | P2-doc | Le vrai chemin est core.bea_executor |
| DevinAgent importe sans erreur | Import probe | **VRAI** | — | — |
| `core.memory.MemoryBank` importe dans DevinAgent | Import probe | **FAUX** (MemoryBank pas dans core.memory.__init__) | P1-DevinAgent | MemoryBank introuvable → compressor dégradé |
| 3 appels v1 restent dans Flutter | STATUS.md L135 | **FAUX (PR #91 corrigé 2026-06-21)** | P0-doc | Corriger STATUS.md |
| `psutil` manque dans requirements.txt | STATUS.md L266 | **FAUX** | — | Corriger STATUS.md (psutil==5.9.8 présent) |
| `structlog` manque dans requirements.txt | STATUS.md L266 | **FAUX** | — | Corriger STATUS.md (structlog==25.5.0 présent) |
| `langchain_*` manque dans requirements.txt | STATUS.md L266 | **FAUX** | — | Corriger STATUS.md (langchain==1.3.9 présent) |
| pytest==7.4.4, fastapi==0.109.0 (stale) | STATUS.md L267 | **FAUX** | — | pytest==9.0.3, fastapi==0.137.1, starlette==1.3.1 |
| hexstrike_v2 import échoue (psutil manquant) | STATUS.md L215 | **FAUX** | — | Import OK, psutil présent |
| Admin password sans fallback hardcodé | api/auth.py | **VRAI** | — | auth.py raise RuntimeError si BEA_ADMIN_PASSWORD absent |
| Settings.py documente un fallback BEA_SECRET_KEY | config/settings.py:380 | **VRAI (avertissement, pas bypass)** | — | Warning de config, pas de vulnérabilité |
| CI bloque sur ruff, coverage, mypy delta | ci.yml | **VRAI** | — | — |
| validate_local.py --quick passe localement | Exécution 2026-06-23 | **VRAI** | — | — |
| smoke_e2e_cycle sha256 passe | Exécution 2026-06-23 | **VRAI** | — | — |
| SupervisedExecutor utilise RiskEngine avant exécution | supervised_executor.py | **VRAI** | — | — |
| DevinAgent/HexStrike représentent du code offensif actif | Status.md, architecture | **FAUX** | — | DevinAgent = stub IA, HexStrike v2 = 17 templates vides |
| 37 secrets historiques rotatés | Issue #14, audit Gitleaks | **NON CONFIRMÉ** | P0-sec | À vérifier / confirmer dans issue #14 |
| La boucle d'amélioration a produit un vrai proposal | STATUS.md L17 | **VRAI** | — | Attesté "proposal_saved 2026-06-16" |
| Flutter v3 migration complete (code) | ALPHA_READINESS.md, FRONTEND_SURFACES.md | **VRAI** | — | APK rebuild non fait, v1 endpoints toujours actifs côté serveur |
| APK rebuild distribué sur Pixel 7 | Aucun doc | **FAUX** | P1 | Rebuild requis avant suppression endpoints v1 |

---

## Points confirmés par les deux audits

1. MetaOrchestrator est le point d'entrée canonique — aucun doute.  
2. Les gates CI (ruff, coverage, mypy delta, gitleaks) sont réels et bloquants.  
3. La dette HexStrike v2 est réelle (17 stubs à 5% du refactor).  
4. Les secrets historiques doivent être rotatés si encore valides (issue #14 P0).  
5. La boucle auto-amélioration fonctionne end-to-end (proposal_saved attesté).

## Points où l'audit précédent avait raison

- L'import legacy de orchestrator_v2 était cassé → **corrigé** depuis Audit S8 (2026-05-20). Le correctif est documenté dans le docstring.
- La dette registries/orchestrateurs est réelle → confirmé (8+ orchestrators-like référencés, mais un seul point d'entrée runtime).

## Points où ce nouvel audit a raison

- `core.policy.policy_engine` est un import systématiquement échoué dans `tool_executor.py:733`. Ni le chemin ni la fonction n'existent. Fail-open pour la majorité des outils, fail-closed pour `shell_execute` et `code_execute`. Ce n'est pas un crash mais la guardrail économique (rate-limits, coût) ne fonctionne jamais.
- STATUS.md a 4 affirmations fausses sur les dépendances et 1 sur Flutter v1. Toutes corrigibles en une passe.
- `core.memory.MemoryBank` n'est pas exporté par `core/memory/__init__.py`. DevinAgent en dépend à l'instanciation : `self.memory_bank = MemoryBank()` échoue à runtime, dégrade la compression de contexte.

## Points à nuancer

- **Admin password fallback**: `config/settings.py:380` parle de "fallback to BEA_SECRET_KEY" en mode non-production. `api/auth.py:62` lève une RuntimeError en production. Ce sont deux niveaux de garde différents — pas de contradiction vraie, documentation imprécise.
- **DevinAgent**: les imports LangChain échouent si langchain non installé, mais langchain est dans requirements.txt (1.3.9) → en environnement standard, l'agent est fonctionnel modulo MemoryBank.
- **OrchestratorV2**: activement utilisé par MetaOrchestrator pour `use_budget=True`. N'est PAS dead code. Le docstring le dit clairement depuis S8.

---

## Enjeux runtime P0/P1/P2

### P0 — Bloque public beta

| ID | Problème | Fichier | Justification |
|----|---------|---------|---------------|
| P0-SEC-1 | 37 tokens historiques potentiellement valides (issue #14) | git history | Fuite de credentials si non rotatés |
| P0-TRUTH-1 | Completion truth non fermée : missions `needs_actions=True` pouvaient retourner COMPLETED sans artefact vérifiable (SHA256 était invalide) | ALPHA_READINESS.md | La gate est maintenant active mais les missions historiques ne sont pas revalidées |

### P1 — Risque sérieux

| ID | Problème | Fichier | Justification |
|----|---------|---------|---------------|
| P1-POLICY | `core.policy.policy_engine.get_policy_engine` import échoue silencieusement | tool_executor.py:733 | La guardrail économique (budget/rate-limit) ne s'exécute jamais |
| P1-DEVIN | `core.memory.MemoryBank` absent de core.memory.__init__ | devin_agent.py:64 | DevinAgent.memory_bank est None → compressor épisodique dégradé |
| P1-APK | APK Flutter non rebuild depuis migration v3 | - | L'APK sur Pixel 7 appelle encore v1 si non reconstruit |
| P1-FASTAPI | Issue #13 : CVE-2024-47874 starlette 0.40 → **RÉSOLU** (starlette==1.3.1) | requirements.txt | Marquer l'issue comme fermée |

### P2 — Dette technique

| ID | Problème | Fichier | Justification |
|----|---------|---------|---------------|
| P2-SHADOW | Routes shadowing entre modules_v3.py et connectors.py | api/routes/ | Fragile selon API_VERSIONING.md |
| P2-DOC | STATUS.md 5 assertions fausses | docs/STATUS.md | Confusion contributeurs |
| P2-ORCH | 8+ fichiers "orchestrateur" dans le repo | core/ | Navigabilité difficile malgré MetaOrchestrator unique |
| P2-HEXSTRIKE | HexStrike v2 : 17 stubs non intégrés, ~5% complet | mcp/hexstrike_v2/ | Scopé subprojects/ pour split |

---

## Priorités finales

1. **Rotation secrets** (issue #14) — confirmer statut, forcer si non fait.
2. **Corriger STATUS.md** — 5 assertions fausses nuisent à la confiance.
3. **Fix import policy dans tool_executor** — la guardrail doit fonctionner.
4. **Rebuild APK Flutter** — avant de supprimer les endpoints v1.
5. **Fermer issue #13** (FastAPI CVE) — déjà résolu dans requirements.txt.
