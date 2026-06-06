# Prompt de passation — à coller dans Claude Code (CLI)

> Copie tout le bloc ci-dessous dans Claude Code, lancé depuis `C:\Users\maxen\Documents\Béa`.

---

Tu reprends le projet **Béa / Jarvis Max**. Travaille dans : `C:\Users\maxen\Documents\Béa`
(branche git actuelle : `hardening/critical-fixes`, remote `origin = git@github.com:IA-optimist/Bea.git`).

## Préférences de travail (à respecter strictement)
- Ingénieur senior Python / IA autonome / Docker / agents LLM.
- Analyse avant d'agir ; explique brièvement le raisonnement.
- Solutions **robustes et minimales** ; pas de refactor inutile.
- Ne modifie jamais plusieurs fichiers si un seul suffit ; ne crée pas d'arborescence ni de dossiers dupliqués (ex. `jarvismax/jarvismax`).
- Vérifie : compat Docker/Linux, imports réellement existants, chemins corrects, non-régression.
- Pour toute modif : (1) explique le bug, (2) correctif minimal, (3) montre le diff, (4) **attends ma validation** avant d'appliquer.

## État actuel du dépôt (IMPORTANT — rien n'est commité)
- ~122 changements **non commités** dans le working tree (aucun `git commit`/`push` n'a été fait). Dernier commit = `85ca002`.
- **À faire en premier** : supprimer le lock git résiduel → `del .git\index.lock` (sinon tout commit échoue).
- Lint : `ruff check .` → « All checks passed! ». Collecte de tests : `pytest --co` = 6017 tests, 0 erreur d'import.
- **Jalon bloquant non franchi** : aucun `pytest` complet vert dans le venv 3.12 (services requis : Postgres/Redis/Qdrant/Docker + stack langchain). À valider avant prod.

## Ce qui a déjà été fait (additif, testé unitairement, NON câblé d'office)
- Outils agent (Axe Hermes 3) : `core/tools/code_execution_tool.py` (sandbox), `core/tools/delegate_tool.py`, `core/tools/tool_pipeline_tool.py` — déjà enregistrés dans `core/tool_executor.py` (loose-coupled).
- Mémoire (Axe 2) : `memory/fts_recall.py` (SQLite FTS5), `memory/user_model.py` — à brancher sur `memory/memory_bus.py` (opt-in).
- Skills (Axe 1) : `core/skills/agentskill_format.py` (interop agentskills.io) + `propose_skill_from_mission`.
- Gateway (Axe 4) : `gateway/base.py` + `gateway/runner.py` (squelette ; adaptateur Telegram concret à écrire).
- 8 bugs `call-arg` (mauvais arguments d'appel) corrigés. Détails dans `docs/AUDIT_ROADMAP_2026-06-01.md` et `docs/ADR_HERMES_INSPIRED_2026-06-01.md`.

### Modules ajoutés (additifs, testés unitairement — 59 tests verts)
| Capacité | Module | Test |
|---|---|---|
| Sandbox code-exec | `core/tools/code_execution_tool.py` | `tests/test_code_execution_tool.py` |
| Subagent délégué | `core/tools/delegate_tool.py` | `tests/test_delegate_tool.py` |
| Programmatic tool calling | `core/tools/tool_pipeline_tool.py` | `tests/test_tool_pipeline_tool.py` |
| Recall FTS5 | `memory/fts_recall.py` | `tests/test_fts_recall.py` |
| Modèle utilisateur | `memory/user_model.py` | `tests/test_user_model.py` |
| Mémoire auto-réorg | `memory/consolidator.py` | `tests/test_memory_consolidator.py` |
| Format agentskills.io | `core/skills/agentskill_format.py` | `tests/test_agentskill_format.py` |
| Gateway (base+runner) | `gateway/base.py`, `gateway/runner.py` | `tests/test_gateway_runner.py` |
| Adaptateur webhook | `gateway/platforms/webhook.py` | `tests/test_gateway_webhook.py` |
| Observabilité LLM | `core/observability/llm_tracer.py` | `tests/test_llm_tracer.py` |
| Sorties typées | `core/structured_output.py` | `tests/test_structured_output.py` |

### Déjà câblé (sûr)
- 3 outils Axe 3 enregistrés dans `core/tool_executor.py` (loose-coupled).
- **FTS dans MemoryBus** : backend `"fts"` dans `MemoryBus.search`, propriété lazy `fts`, **opt-in strict** (actif seulement si env `JARVIS_FTS_DB` défini ET backend `"fts"` demandé). `BACKEND_ALL` inchangé → défaut byte-identique.

### Branchements opt-in RESTANTS — à faire DANS le venv avec tests (chemins chauds, non câblés à l'aveugle)
Pour chacun : flag désactivé par défaut + fail-open + diff montré + validation avant d'appliquer.
1. **Observabilité LLM** → `core/llm_factory.py` (`safe_invoke`, ~ligne 654) : envelopper l'appel dans `get_tracer().span(model, mission_id)` ; ajouter un accessor global `get_tracer()`. Flag `JARVIS_LLM_TRACE`.
2. **Mémoire auto-réorg** → `night_worker/scheduler.py` (`_loop`) : appel périodique de `memory.consolidator.consolidate(...)` sur le store.
3. **Extraction de skill en fin de mission** → `core/meta_orchestrator.py` (hook fin de mission) : `core.skills.agentskill_format.propose_skill_from_mission(...)` puis persistance via `core/skills/skill_registry.py`.
4. **Sorties typées** → `agents/agent_output.py` : remplacer le parsing JSON ad hoc par `core.structured_output.parse_structured(...)`.
5. **Endpoint webhook** → nouveau `api/routes/gateway_webhook.py` + `app.include_router(...)` dans `api/main.py` (~ligne 184+) ; handler = wrapper vers `meta_orchestrator.run_mission`, derrière auth + allowlist (`gateway.runner.GatewayRunner`).
6. **UserModel dans le prompt** → assemblage du contexte côté orchestrateur : injecter `memory.user_model.UserModel(...).summary()` (tier « context », lecture seule).

## TA MISSION
Configurer Béa pour utiliser **mon modèle « Bea v3.1 »** comme modèle de travail, **avec Codex en orchestrateur**, exactement comme c'est configuré dans mon agent **Hermes**.

Étapes attendues :
1. **Inspecte d'abord ma configuration Hermes** (installation locale de hermes-agent) pour voir précisément comment Codex y est branché comme orchestrateur (provider, `api_mode`, base_url, modèle, résolution provider→credentials). Réplique ce pattern, ne le réinvente pas.
2. **Repère les points de configuration LLM dans Béa** :
   - `config/settings.py` (`get_settings()` à la ligne ~369),
   - `core/llm_factory.py` (`class LLMFactory`),
   - `agents/agent_factory.py` (`AgentFactory.create_dynamic` → rôles director/research/builder/advisor/default),
   - `core/meta_orchestrator.py` (boucle d'orchestration).
3. **Câble** : « Bea v3.1 » comme modèle des agents de travail, et **Codex comme modèle de l'orchestrateur** (le composant qui planifie/route les missions). Garde la résolution provider/credentials hors du code (via `.env` / settings), pas de secret en dur.
4. Si l'endpoint, le nom exact du modèle, ou les credentials de « Bea v3.1 » / Codex ne sont pas trouvables dans la config → **demande-les moi**, ne devine pas.
5. Montre-moi le **diff minimal** et attends ma validation avant d'appliquer. Vérifie ensuite : `ruff check .` vert, `pytest` (au moins les tests de routing/LLM : `tests/test_llm_routing_policy.py`).

Commence par (a) `del .git\index.lock`, puis (b) l'inspection de la config Hermes et des points LLM de Béa, puis propose le plan de câblage avant de coder.
