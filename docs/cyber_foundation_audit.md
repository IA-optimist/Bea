# Béa Cyber Foundation v1 — Audit & Gap Analysis

## 1. Modules existants à réutiliser

| Module | Chemin | Rôle dans agent_cyber |
|--------|--------|-----------------------|
| `code_guard.py` | `core/security/` | AST-based code safety checker — réutilisable pour static analysis |
| `input_sanitizer.py` | `core/security/` | Validation des entrées — intégrer dans CyberActionGuard |
| `rbac.py` | `core/security/` | RBAC existant — vérifier les rôles avant d'autoriser missions cyber |
| `secret_audit.py` | `core/security/` | Audit trail immuable — à brancher sur CyberActionGuard decisions |
| `secret_crypto.py` | `core/security/` | Chiffrement secrets — n/a direct, mais utile pour vault keys |
| `secret_policy.py` | `core/security/` | Politique secrets — référencer pour EvidenceGate (pas de secrets dans claims) |
| `secret_vault.py` | `core/security/` | Vault — n/a pour cyber v1 |
| `startup_guard.py` | `core/security/` | Garde au démarrage — pattern à copier pour cyber mission init |
| `url_guard.py` | `core/security/` | Validation URLs — réutiliser pour valider cibles externes |
| `tool_permissions.py` | `core/` | ToolPermission + risk_level — référence pour RiskLevel enum |
| `execution/policy.py` | `core/` | PolicyViolation, _BLOCKED_PATTERNS — pattern pour CyberPolicyDecision |
| `redactor.py` | `core/observability/` | redact() — OBLIGATOIRE dans EvidenceGate et CyberReportGenerator |
| `sandbox_executor.py` | `core/self_improvement/` | ALLOWED_COMMANDS whitelist — pattern pour cyber action whitelist |

## 2. Points d'intégration

- **`agents/crew.py`** : ajouter un `CyberReviewerAgent` dans les variants (post-v1)
- **`agents/registry.py`** : enregistrer l'agent cyber (post-v1)
- **`core/execution/policy.py`** : `_BLOCKED_PATTERNS` → étendre avec patterns cyber offensifs
- **`kernel/improvement/gate.py`** : pattern de gate à réutiliser dans CyberActionGuard
- **`api/main.py`** : exposer endpoints `/api/v3/cyber/*` (post-v1, pas dans cette PR)

## 3. Risques actuels

1. **Aucune couche cyber** : le codebase Béa n'a actuellement aucun module dédié à l'analyse de sécurité. Toute mission cyber se déroulerait sans garde-fou spécifique.
2. **Pas de scope obligatoire** : rien n'oblige une mission à déclarer une cible autorisée avant d'agir.
3. **Pas de traçabilité evidence** : les agents peuvent affirmer qu'une vulnérabilité existe sans preuve attachée.
4. **Pas de distinction defensive/offensive** : aucune liste blanche/noire d'actions cyber.
5. **Logs potentiellement trop verbeux** : sans redacteur cyber-spécifique, des secrets pourraient fuir dans les logs d'analyse.

## 4. Plan d'implémentation

```
Phase 0  → docs/cyber_foundation_audit.md (ce fichier)
Phase 1  → agent_cyber/actions.py + agent_cyber/scope.py + tests
Phase 2  → agent_cyber/policy.py (CyberActionGuard) + tests
Phase 3  → agent_cyber/evidence.py (EvidenceGate) + tests
Phase 4  → agent_cyber/findings.py (SecurityFinding) + tests
Phase 5  → agent_cyber/mission_graph.py + tests
Phase 6  → agent_cyber/reports.py + tests
Phase 7  → agent_cyber/skills.py (11 skills défensifs) + tests
Phase 8  → agent_cyber/evals/ (benchmark L0-L3, 5 fixtures) + tests
Phase 9  → agent_cyber/integration.py + tests
Phase 10 → Documentation (6 fichiers)
Phase 11 → Qualité : pytest + ruff
Phase 12 → PR DRAFT
```

## 5. Limites v1

- **Analyse statique uniquement** : pas d'exécution de code ou de requêtes HTTP live (sauf scope explicite)
- **Pas d'agent autonome** : agent_cyber est une bibliothèque, pas un agent autonome
- **Pas d'intégration API** : les endpoints REST viendront en v2
- **Pas de base de données CVE** : les audits de dépendances délèguent à pip-audit (outil externe)
- **Scoring manuel** : CyberEvalHarness v1 score les outputs déjà produits, pas de LLM-judge intégré
- **Rate limiting stateless** : log-only en v1, enforcement Redis en v2
- **10 actions offensives bloquées HARD** : EXPLOIT, BRUTE_FORCE, WAF_BYPASS, POST_EXPLOITATION, PERSISTENCE, EXFILTRATION, PRIVILEGE_ESCALATION, DESTRUCTIVE_TEST, UNAUTHORIZED_SCAN, PAYLOAD_ESCALATION

## 6. Prochaines étapes v2

- Agent cyber autonome avec routing depuis la mission pipeline
- Endpoints `/api/v3/cyber/` : submit scope, get findings, get report
- CVE database locale (grype/trivy integration)
- LLM-judge pour scorer automatiquement les findings
- Rate limiting avec Redis
- Intégration avec DockerSandbox pour analyse dans conteneur isolé
- CyberMissionLoop inspiré de GitHubMissionLoop (PR #125)
