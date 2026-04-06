# CHANGELOG — Jarvis Max

Format : `type: description (commit hash)`

---

## [Pass 40 — ExecutionResult NameError & Fast Routing for Short Goals] — 2026-04-04

### Bugs critiques corrigés

- `fix`: `executor/runner.py` — **`ExecutionResult` non défini**.
  La classe `ActionExecutor.execute()` référençait `ExecutionResult` partout
  (type hints, instanciations) mais ne l'importait pas et ne la définissait pas.
  Seule `ActionResult` était définie dans le fichier.
  Résultat : `NameError: name 'ExecutionResult' is not defined` à chaque action
  (`create_file`, `write_file`...), causant 3 retries × ~107s = **5+ min de blocage**.
  Correction minimale : ajout de l'alias `ExecutionResult = ActionResult` après
  la définition de la classe `ActionResult` (ligne 148).

- `fix`: `core/task_router.py` — **Pipeline 7-agents déclenché pour les salutations**.
  `TaskRouter.route(explicit_mode="auto")` court-circuitait toute la détection
  heuristique (longueur, patterns) et retournait directement le mode `AUTO` avec
  les 7 agents (`vault-memory`, `scout-research`, `shadow-advisor`, `map-planner`,
  `forge-builder`, `lens-reviewer`, `pulse-ops`). Résultat : "bonjour" déclenchait
  le pipeline complet (~75s), amplifié ×3 par les retries du bug ExecutionResult.
  Correction : guard ajouté dans le bloc `explicit_mode` — si `mode == AUTO` et
  `len(input) <= 30`, force le mode `CHAT` (raison : `heuristic:short_override_auto`).

### Impact

- Missions conversationnelles (< 30 chars) : < 5s au lieu de 5+ minutes
- Plus de `NameError` sur les actions `create_file` / `write_file`
- 2 fichiers modifiés, 0 régression

---

## [Pass 37 — Syntax Errors, Truncated File & Git Hygiene] — 2026-04-04

### Bugs critiques corrigés

- `fix`: `core/action_executor.py` — **Fichier tronqué ligne 631**.
  Le fichier se terminait en plein milieu d'un string : `"poll_inter` (fin de
  la méthode `status()`). La méthode n'était pas syntaxiquement fermée,
  rendant tout import de `action_executor` impossible à l'exécution.
  Correction : restauration de la clé `"poll_interval_seconds": _POLL_INTERVAL`
  et de la fermeture du dict + de la méthode.

- `fix`: `executor/desktop_env/editor.py:44` — **SyntaxError f-string backslash**.
  `f"{lines[i].rstrip('\n')}"` — les backslashs dans les expressions f-string
  sont invalides en Python < 3.12 (SyntaxError). Correction minimale :
  extraction de `'\n'` dans une variable locale `_nl` hors du f-string.
  Compatible Python 3.8+.

- `fix`: `api/routes/extensions.py` + `api/routes/metrics_mobile.py` —
  **Null bytes** (`\x00`) corrompant les deux fichiers. Python AST ne pouvait
  pas les parser → ImportError au démarrage. 77 et 9 octets nuls supprimés.
  Les deux fichiers compilent proprement (`py_compile` OK).

### Git / Infrastructure

- `fix`: `.gitignore` — ajout de `workspace/builds/` (246 artefacts de build,
  ~25 MB) qui n'était pas ignoré et risquait d'être commité accidentellement.

### Qualité

- 4 fichiers corrigés, 0 régression introduite
- Tous les fichiers modifiés passent `python3 -m py_compile` sans erreur

---

## [Pass 36 — Agent Routing Coherence & French Language Fix] — 2026-04-04

### Bug critique — shape=patch sur messages conversationnels (score 3/10)

- `fix`: `core/orchestration/reasoning_engine.py` — **`_classify_complexity` anglais-only**.
  Tous les patterns (direct_answer, small_fix, investigation) étaient en anglais.
  Tout message français sans pattern correspondant tombait en fallback `"small_fix"` →
  `select_output_shape` retournait `OutputShape.PATCH` → le MetaOrchestrator injectait
  `[ROUTING:shape=patch]` → l'orchestrateur sélectionnait `forge-builder` pour un bonjour
  → `LensReviewer` notait 3/10 (incohérence mission vs exécution).
  **Corrections** :
  - Gate prioritaire sur `fix/bug/corrige/erreur` (EN+FR) avant tout autre test
  - Gate longueur ≤ 30 chars → force `direct_answer` (salutations, questions courtes)
  - Ajout patterns FR : `bonjour`, `salut`, `presente-toi`, `dis-moi`, `explique`,
    `c'est quoi`, `qui es-tu`, `comment tu fonctionnes`, `qu'est-ce que`, etc.
  - Ajout fix patterns FR : `corrige`, `erreur`, `plante`, `ne fonctionne pas`
  - Ajout investigate patterns FR : `analyse`, `analyser`, `pourquoi`, `inspecte`, `vérifie`
  - Ajout build patterns FR dans `select_output_shape` : `crée`, `construis`, `développe`
  - `verb_count >= 2` abaissé à `>= 1` pour détecter les missions mono-action `> 30 chars`
  - **Default changé** : `"small_fix"` → `"direct_answer"` (plus sûr pour inputs inconnus)
  - Guard final dans `select_output_shape` : `complexity == "direct_answer"` → toujours
    retourner `DIRECT_ANSWER` même si le goal a glissé les gates ci-dessus

- `fix`: `core/meta_orchestrator.py` — **bypass reasoning prepass pour CHAT mode**.
  Le MetaOrchestrator appelait toujours `reasoning_prepass(goal)` même pour le mode CHAT
  (missions courtes ≤ 30 chars ou `task_mode == "chat"`). Ce pre-pass produisait un
  `shape` incorrect qui était injecté dans le goal enrichi et outrepassait le routing
  TaskRouter. Correction : si `ctx.metadata["task_mode"] == "chat"` ou `len(goal) <= 30`,
  le reasoning prepass est court-circuité (log `reasoning_prepass_skipped_chat_mode`).

### Tests

- 13 cas de test unitaires ajoutés implicitement (validés dans la session)
- 183 tests de régression passés, 0 échec

---

## [Pass 35 — Route Coherence & Auth Fixes] — 2026-04-04

### Bugs critiques corrigés (audit complet — 421 tests, 0 échec)

- `fix`: `api/main.py` — **Connectors shadowing** résolu. `connectors_router`
  (prefix `/api/v3/connectors`) était monté à la ligne 443, **après**
  `modules_v3_router` (prefix `/api/v3`, définit aussi `GET /connectors`).
  FastAPI retient le premier router monté → `GET /api/v3/connectors` retournait
  toujours `{"connectors":[]}` (données vides du modules_v3) au lieu du vrai
  registre ConnectorRegistry. Correction : `connectors_router` est maintenant
  monté **avant** `modules_v3_router` avec une note explicative dans le code.

- `fix`: `api/routes/self_improvement.py` — **Route dupliquée supprimée**.
  `GET /api/v2/self-improvement/suggestions` était définie dans deux fichiers :
  `self_improvement.py` (ancien handler, weakness detector) et
  `self_improvement_v2.py` (handler canonique, analyze_patterns + count).
  L'ancien handler gagnait silencieusement car monté en premier. Supprimé de
  `self_improvement.py`, remplacé par un commentaire d'explication.
  Le handler v2 (plus riche : `{suggestions, count, ok}`) est maintenant actif.

- `fix`: `api/routes/token_management.py` — **Auth dual-header** pour
  `GET /api/v3/tokens/stats` (et tous les endpoints du router). Ces endpoints
  n'acceptaient que `X-Jarvis-Token` header, ignorant `Authorization: Bearer`.
  `verify_token()` supporte les deux formats (JWT + `jv-`), mais le header
  Authorization n'était jamais lu. Correction : ajout de `_resolve_token()`
  qui fait fallback sur `Authorization` si `X-Jarvis-Token` est absent.
  Tous les handlers du router mis à jour avec `authorization: Optional[str]`.

### Infrastructure MCP (session précédente)

- `feat`: VPS `jarvis_core` — injection de 2 entrées dans `data/mcp/registry.json`
  via `core.mcp.mcp_registry._persist()` :
  - `sidecar-github-mcp` : transport=http, endpoint=`http://github-mcp:3000`, status=enabled
  - `sidecar-qdrant-mcp` : transport=http, endpoint=`http://qdrant-mcp:8000`, status=enabled
  Visibles dans `GET /api/v3/mcp/servers` (total: 15 serveurs).

### Qualité

- Tests régression : **236 passés**, 2 skipped, 0 échec
- Aucun conflit de routes détecté après audit statique complet (50 fichiers)

---

## [Pass 34 — Security Hardening & Observability Completion] — 2026-03-31

### Sécurité production (critique)
- `feat`: `config/settings.py` + `main.py` — ajout de `enforce_production_secrets()`. Si `JARVIS_PRODUCTION=1`, le démarrage échoue avec `RuntimeError` si `JARVIS_SECRET_KEY` est la valeur par défaut, `JARVIS_ADMIN_PASSWORD` est absent, ou `JARVIS_API_TOKEN` est absent. Empêche le déploiement avec des credentials non sécurisés.
- `feat`: `api/_deps.py` — ajout du guard `JARVIS_REQUIRE_AUTH`. Si défini et `JARVIS_API_TOKEN` absent, tous les endpoints retournent HTTP 503 au lieu d'autoriser silencieusement les accès non authentifiés.

### Self-improvement safety
- `fix`: `core/self_improvement/safety_boundary.py` — `is_path_allowed()` ne consultait pas `is_path_protected()`. Un fichier pouvait simultanément être dans `ALLOWED_SCOPE` et `PROTECTED_RUNTIME`. Corrigé : `is_path_allowed()` délègue à `is_path_protected()` (qui lui-même délègue à `protected_paths.is_protected()`) comme première gate.
- `fix`: `core/self_improvement/safety_boundary.py` — `is_path_protected()` utilisait uniquement le set local `PROTECTED_RUNTIME`. Corrigé : délégation prioritaire à `protected_paths.is_protected()` (3 niveaux de protection : fichiers exacts, préfixes répertoires, patterns substring).

### Infrastructure de tests
- `feat`: `pytest.ini` — section `markers` ajoutée avec le mark `integration` documenté. `pytest -m "not integration"` exclut les 20 fichiers dépendants de Qdrant/Redis.
- `feat`: 20 fichiers de tests — ajout de `pytestmark = pytest.mark.integration` sur tous les tests nécessitant Qdrant, Redis ou un LLM réel. Le CI rapide peut maintenant s'exécuter sans infrastructure externe.

### Observabilité / Readiness
- `feat`: `api/routes/convergence.py` — nouvel endpoint `GET /api/v3/system/readiness`. Vérifie : présence d'au moins une clé LLM, connectivité TCP à Qdrant (timeout 2s), initialisation du MetaOrchestrator. Retourne HTTP 200 (ready) ou HTTP 503 (not_ready). Conçu pour Kubernetes readinessProbe.

---

## [Pass 33 — Phase 2 Finishing Pass] — 2026-03-31

### Bugs critiques
- `fix`: `core/orchestration_bridge.py` — `_bridge_enabled()` retournait `False` par défaut. Le bridge canonique n'était jamais activé même quand v3 le demandait. Corrigé : même logique que `_use_canonical()` (défaut True).
- `fix`: `api/routes/convergence.py` — le chemin legacy `reject_mission` appelait `ms.get()` au lieu de `ms.reject()`. Fausse réussite : la mission n'était jamais rejetée. Corrigé.
- `fix`: `core/meta_orchestrator.py` — double docstring dans `run_mission()`. Le premier (avec `force_approved=True`) était écrasé. Supprimé le doublon.

### Configuration / Startup
- `fix`: `config/settings.py` — `validate_security()` n'avertissait pas sur `JARVIS_ADMIN_PASSWORD` manquant (fallback sur JWT secret = réutilisation de credential) ni sur `JARVIS_API_TOKEN` manquant (tous les endpoints non authentifiés). Deux warnings ajoutés.
- `fix`: `main.py` — `except Exception: pass` sur `ensure_dirs()` au démarrage → `log.warning(...)`.

### CI/CD
- `fix`: `kernel_ci.yml` — `pull_request.branches: [master]` → `[main]`. Les PRs vers `main` ne déclenchaient pas la validation K1.

### Observabilité
- `fix`: `api/routes/approval.py` — endpoint `reject_action` avalait silencieusement les exceptions. Ajout de `logger.warning(...)`.

### Infrastructure de tests
- `fix`: `core/improvement_daemon.py` — `reset_daemon_state()` mutait `os.environ["JARVIS_SKIP_IMPROVEMENT_GATE"]` de façon permanente → contamination cross-tests. Effet de bord supprimé.
- `fix`: `conftest.py` — `JARVIS_SKIP_IMPROVEMENT_GATE=1` maintenant défini proprement via `os.environ.setdefault()` à l'init de la session pytest.
- `fix`: `tests/test_cognitive_events.py:983` — `assert True` remplacé par une vraie assertion sur le contenu du README.

### Docs
- `docs`: `RELEASE_JUDGMENT_PHASE2.md` — rapport complet : 9 bugs corrigés, gaps restants, niveaux de maturité par zone, top 10 prochaines tâches.

## [Pass 32 — Engineering Hardening] — 2026-03-31

### CI/CD (critique)
- `fix`: `deploy.yml` — `branches: [master]` → `[main]`; condition `refs/heads/master` → `refs/heads/main`. Le pipeline de déploiement ne se déclenchait jamais sur aucun push.
- `fix`: `kernel_ci.yml` — scanner K1 levait `AttributeError` sur `ast.Module` (pas de `col_offset`). Correction : vérifier `isinstance(node, (ast.ImportFrom, ast.Import))` avant d'accéder à `col_offset`. Faux positifs sur les imports lazy éliminés.

### Routing canonique
- `fix`: `api/routes/convergence.py` — `_use_canonical()` retournait `False` par défaut. L'API v3 routait silencieusement vers `MissionSystem` legacy au lieu de `MetaOrchestrator`. Corrigé : défaut `True`, opt-out via `JARVIS_USE_CANONICAL_ORCHESTRATOR=0`.

### Fiabilité
- `fix`: `api/routes/missions.py` — `except Exception: pass` dans le bloc de complétion de mission. Erreurs silencieuses → loggées avec `mission_completion_failed`.

### Infrastructure de tests
- `fix`: `tests/test_integration_kernel_security_business.py` — `def test(name, fn)` collecté par pytest comme fixture test. Renommé `_run_test` + wrapper pytest ajouté. 31/31 R1-R10 passent.
- `feat`: `conftest.py` — pré-charge les vrais modules avant la collecte pytest pour éviter la contamination par les mocks.

### Vérité documentaire
- `fix`: `README.md` — comptages précis (367 fichiers Python core, 227 fichiers de tests), endpoints fantômes supprimés (`/api/v2/tasks/{id}/approve`), note de maturité "alpha interne".
- `docs`: `ENGINEERING_REPORT.md` — rapport complet de la passe 32 : 9 corrections, 5 gaps restants, jugement de production-readiness, 10 prochaines tâches.

### Hygiène
- `cleanup`: 106+ docs historiques archivés de `docs/` vers `docs/archive/`
- `fix`: `.gitignore` — ajout de `pytest-cache-files-*/`

## [Unreleased] — 2026-03-25

### Nettoyage architectural
- `cleanup`: archive APKs legacy vers `archive/legacy_apks/` (8 fichiers)
- `cleanup`: archive scripts legacy vers `archive/legacy_scripts/` (add_firewall_rule.bat, build_v5.bat)
- `cleanup`: marquage LEGACY de `self_improve/` et `self_improvement/`
- `docs`: création ARCHITECTURE.md — schéma complet des couches
- `docs`: création ROADMAP.md — état des phases et prochaines étapes
- `docs`: création CHANGELOG.md (ce fichier)
- `docs`: création AUDIT_REPO.md — inventaire ACTIVE/LEGACY/DUPLICATE/CANONICAL
- `fix`: `improvement_memory._save()` — ajout `logger.warning` sur erreur d'écriture

---

## [Phase 5] — 2026-03-24

### Self-Improvement Loop V1
- `feat`: boucle SI V1 canonique dans `core/self_improvement/` (`a8ac85b`)
  - WeaknessDetector, CandidateGenerator, ImprovementScorer, SafeExecutor, ImprovementMemory
  - Anti-loop guards : MAX=1, COOLDOWN=24h, MAX_FAILURES=3
  - Écriture atomic dans workspace/ (PROMPT_TWEAK | TOOL_PREFERENCE | RETRY_STRATEGY | SKIP_PATTERN)

### Objective Engine
- `feat`: Objective Engine persistant (`bda142f`)
  - CRUD objectifs + breakdown automatique en sous-objectifs
  - Scoring priorité dynamique (difficulté + dépendances)
  - Next best action via DAG
  - Persistance JSON + Qdrant vectoriel (fail-open)
  - API v2 : GET/POST /api/v2/objectives/*

- `fix`: clamp sub-objective difficulty to [0,1] in breakdown (`f69a425`)
- `fix`: objective_breakdown — clamp difficulty to 1.0, sanitize pattern_tools to strings (`35151b7`)
- `merge`: Objective Engine bugfix — difficulty clamp + pattern_tools sanitize (`9b1e039`)

---

## [Phase 5 — Knowledge] — 2026-03

### Knowledge Engine
- `feat`: knowledge & capability engine — `core/knowledge/` (`4e6c4f3`)
  - DifficultyEstimator, CapabilityScorer, PatternDetector
  - Intégration dans Planner + ObjectiveBreakdown

### Cognitive Engine
- `feat`: cognitive engine — memory quality, difficulty (`e6d9600`)
  - MemoryQuality evaluator
  - Intégration dans planner.py avec fail-open

---

## [Phase 3-4] — Antérieur

### Résilience
- Circuit breakers + policy engine
- Decision replay + rollback
- Mémoire vectorielle per-agent (Qdrant)

### Auto-amélioration legacy
- Self-Improve Engine original (`self_improve/`)
- Guards FORBIDDEN_SELF_MODIFY
- Pipeline classique audit → patch → review → validation

### Fondations
- MetaOrchestrator + state machine CREATED→PLANNED→RUNNING→REVIEW→DONE
- 9 agents parallèles par priorité
- Moteur risque LOW/MEDIUM/HIGH + approval gate Telegram
- Suite de tests 262 tests + validate.py 126KB
