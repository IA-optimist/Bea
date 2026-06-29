# Béa Cyber Safety Model v1

## 1. Ce que Béa Cyber v1 PEUT faire

Actions autorisées (liste complète, exhaustive) :

| Action | Description |
|--------|-------------|
| `code_review` | Analyse statique de code Python/JS/etc. |
| `dependency_audit` | Audit requirements.txt/pyproject.toml pour CVEs |
| `secret_scan` | Scan de secrets hardcodés (résultats redactés) |
| `config_review` | Analyse de configuration (Flask, Docker, nginx…) |
| `auth_review` | Analyse statique du code d'authentification |
| `access_control_review` | Analyse RBAC, permissions, access control |
| `security_headers_review` | Analyse des headers HTTP de sécurité |
| `static_analysis` | Analyse statique générale (AST, patterns) |
| `generate_report` | Génération de rapport Markdown + JSON |
| `propose_fix` | Proposition de correctifs (jamais appliqués auto) |
| `generate_regression_tests` | Plans de tests de régression (pas d'exécution auto) |

## 2. Ce que Béa Cyber v1 NE PEUT PAS faire

Actions **bloquées HARD par design** — il n'existe aucun bypass :

| Action bloquée | Raison |
|----------------|--------|
| `exploit` | Exploitation réelle = hors scope éthique et légal |
| `brute_force` | Attaque par force brute sur systèmes réels |
| `waf_bypass` | Contournement de WAF = attaque offensive |
| `post_exploitation` | Mouvements latéraux = compromettre davantage |
| `persistence` | Installer une backdoor = crime |
| `exfiltration` | Exfiltrer des données = violation RGPD + crime |
| `privilege_escalation` | Escalade de privilèges = compromission système |
| `destructive_test` | Tests destructifs sur systèmes réels |
| `unauthorized_scan` | Scanner une cible sans autorisation explicite |
| `payload_escalation` | Escalade de payload = exploitation avancée |

## 3. Pourquoi exploitation/post-exploitation sont bloquées

1. **Légal** : l'exploitation non autorisée est une infraction dans tous les pays de l'UE.
2. **Éthique** : Béa est un outil d'assistance, pas un outil d'attaque.
3. **Risque opérationnel** : une exploitation automatique mal calibrée peut mettre hors ligne un système en production.
4. **Pas de supervision humaine** : l'exploitation automatique sans supervision humaine est inacceptable.
5. **v1 = défensif uniquement** : la fondation v1 pose les bases. L'escalade vers des capacités offensives nécessite une gouvernance formelle (v3+).

## 4. Comment le scope est validé

Chaque action passe par `CyberActionGuard.validate()` qui vérifie :

1. **Scope présent** — pas de scope = refus immédiat
2. **Scope non expiré** — scope expiré = refus
3. **Action non bloquée** — liste noire vérifiée en O(1)
4. **Action connue** — liste blanche vérifiée en O(1)
5. **Cible externe** — requiert `authorization_status == EXPLICIT`
6. **report_only** — si True, bloque `propose_fix` et `generate_regression_tests`
7. **Risque élevé** — `HIGH`/`CRITICAL` → `required_approval=True`

Toute décision est loggée avec un `audit_ref` unique.

## 5. Comment les preuves sont exigées

`EvidenceGate` valide les claims avant qu'ils deviennent `VERIFIED` :

- `VULNERABILITY_EXISTS` sans preuve → `UNVERIFIED` (jamais `CONFIRMED`)
- `TEST_PASSED` sans `TEST_OUTPUT` evidence → `REJECTED`
- `SCOPE_AUTHORIZED` sans `USER_PROVIDED_AUTHORIZATION` → `REJECTED`
- `CONFIRMED` finding sans `evidence_refs` → exception `ValueError` au modèle

Ce mécanisme empêche Béa d'affirmer qu'une vulnérabilité existe sans l'avoir prouvée.

## 6. Comment les rapports sont produits

`CyberReportGenerator` produit :
- **Markdown** : 11 sections obligatoires, findings UNVERIFIED clairement marqués ⚠️
- **JSON** : `model_dump()` + redaction via `core.observability.redactor`
- **Redaction** : API keys, Bearer tokens, bea-tokens → `[REDACTED]` systématique

Les secrets ne transitent jamais dans les rapports ou les logs.

## 7. Comment les évaluations fonctionnent

`CyberEvalHarness` utilise des fixtures YAML éducatives (code synthétique) :
- L0-L3 : progression de difficulté
- Score 0-100 : verdict (40pts) + classe (25pts) + localisation (25pts) + evidence (5pts) + remédiation (5pts)
- Verdict wrong → total capé à 10pts maximum

Toutes les fixtures contiennent du **code fictif/éducatif**, jamais de vrai code de production.

## 8. Gestion des erreurs / faux positifs

- `UNVERIFIED` findings : présents dans le rapport, clairement marqués, à confirmer manuellement
- `FALSE_POSITIVE` : statut disponible après review humaine
- `CANDIDATE` : état par défaut — non confirmé, non rejeté
- Findings `CONFIRMED` sans evidence → downgraded automatiquement à `UNVERIFIED` par `finalize_cyber_mission`

## 9. Roadmap v2

- Agent cyber autonome dans le pipeline de missions
- Endpoints REST `/api/v3/cyber/`
- Intégration CVE database (grype/trivy)
- LLM-judge automatisé
- Rate limiting Redis
- CyberMissionLoop (GitHubMissionLoop-style)
- Gouvernance formelle pour capacités offensives en environnement contrôlé (v3+)
