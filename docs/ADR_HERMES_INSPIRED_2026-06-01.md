# ADR — Évolution de Bea Max inspirée de Hermes Agent

_Statut : PROPOSITION (à valider avant implémentation) · 2026-06-01_

## Contexte

Hermes Agent (Nous Research) vise le même but que Bea Max : un agent autonome
auto-améliorant. Cet ADR mappe les 4 patterns Hermes demandés sur le code Bea
**existant** et propose un plan **incrémental et minimal**. Principe directeur :
**on étend l'existant, on ne reconstruit pas, on ne crée pas d'arborescence
parallèle** (Bea a déjà la plupart des briques).

### Principes Hermes transverses à adopter
- **Cœur agnostique** : une seule classe agent sert CLI / gateway / cron / API
  (chez Hermes `AIAgent`). Chez Bea : converger vers `core/meta_orchestrator`
  comme point unique, les entrées (api, cron, futur gateway) n'étant que des adaptateurs.
- **Loose coupling** : registres + `check_fn` de disponibilité, pas de dépendances dures
  (Bea a déjà `agents/registry.py`, `core/skills/skill_registry.py`, `ConnectorRegistry`).
- **Observable + interruptible** : chaque appel d'outil visible ; annulable.
- **Profile isolation** : un profil = home/config/mémoire/sessions isolés.

---

## Axe 1 — Boucle d'apprentissage & skills auto-améliorants

**Existant Bea** : `core/self_improvement/` (engine, improvement_loop,
candidate_generator, code_patcher, deployment_gate, lesson_memory, safe_executor,
human_gate…) + `core/skills/` (skill_builder, skill_registry, skill_retriever,
skill_feedback, skill_chain, skill_discovery, skill_service). Très complet côté
**amélioration du code**.

**Pattern Hermes** : la boucle agit sur les **skills** (mémoire procédurale) :
(1) créer un skill depuis une expérience réussie, (2) l'améliorer pendant l'usage,
(3) nudges périodiques pour persister, (4) format de skill **portable** (agentskills.io).

**Écart** : Bea améliore surtout son *code* ; la boucle « expérience → skill →
réutilisation → amélioration à l'usage » est moins explicite, et le format de skill
n'est pas aligné sur un standard partageable.

**Plan minimal**
1. Brancher `skill_feedback.py` sur la fin de mission (`meta_orchestrator`) : après
   une mission réussie/échouée, déclencher `skill_builder` (créer) ou
   `skill_feedback` (ajuster le score/contenu) — fermer la boucle existante.
2. Ajouter un « nudge » périodique léger (réutiliser `night_worker/` ou `cron/`) :
   scanner les missions récentes sans skill associé et proposer une extraction.
3. Adapter `skill_models.py` pour exporter/importer le format **agentskills.io**
   (un `to_agentskill()` / `from_agentskill()`), sans changer le stockage interne.

**Risques** : déclencher la création de skills en boucle (coût LLM) → gating via
`human_gate`/seuil de confiance déjà présents. **Faible** si on réutilise l'existant.

---

## Axe 2 — Mémoire inter-sessions & modèle utilisateur

**Existant Bea** : `memory/` (MemoryBus : recall/remember/search, postgres_backend,
redis_cache, decision_memory, vault_memory, embeddings) + `core/memory/` (qdrant,
vector_memory, memory_layers) + `core/memory_graph/`. Vectoriel + couches déjà là.

**Pattern Hermes** : SQLite **FTS5** pour le recall plein-texte cross-session avec
**lignage** (parent/enfant à travers les compressions), **résumé LLM** des sessions,
et **modèle dialectique de l'utilisateur** (Honcho : qui est l'utilisateur, ses
préférences, à travers les sessions).

**Écart** : Bea a le vectoriel mais (a) pas de recall plein-texte léger type FTS5
en complément, (b) pas de **user-model** explicite et persistant, (c) pas de résumé
de session systématique pour le rappel.

**Plan minimal**
1. Ajouter un backend **FTS5 SQLite** dans `memory/` comme couche de recall rapide
   (complément, pas remplacement de qdrant) — exposé via `MemoryBus.search`.
2. Introduire un `UserModel` (nouvelle classe dans `memory/`, persistée) : préférences,
   faits stables, mis à jour en fin de session via le client LLM auxiliaire.
3. Résumé de session en fin de mission (réutiliser un client LLM existant) stocké et
   réinjecté au prompt suivant (tier « context »).

**Risques** : cohérence vectoriel ↔ FTS5 ↔ user-model. **Modéré** — garder FTS5 en
couche additive et le user-model en lecture seule au prompt.

---

## Axe 3 — Subagents & Programmatic Tool Calling

**Existant Bea** : `agents/parallel_executor.py` (`ParallelExecutor`,
`run_python_script`), `executor/` (execution_engine, supervised_executor,
capability_dispatch, task_queue, **desktop_env sandbox** déjà durci).

**Pattern Hermes** : deux outils exposés **au modèle** — `delegate_tool` (spawn d'un
subagent isolé pour un workstream parallèle) et `execute_code` (le modèle écrit du
code qui orchestre plusieurs appels d'outils en **une seule inférence**, au lieu d'un
aller-retour par outil).

**Écart** : Bea a la mécanique d'exécution parallèle + sandbox, mais **pas d'outils
`delegate`/`execute_code` exposés au LLM** dans le set d'outils.

**Plan minimal**
1. `delegate` : wrapper outil au-dessus de `ParallelExecutor` + `agent_factory`,
   exposé dans le registre d'outils, avec budget (temps/tokens) et isolation.
2. `execute_code` : wrapper outil au-dessus du **sandbox `executor/desktop_env`**
   (déjà `network=none`, `read_only`, caps drop) exposant une API tools-as-functions
   au code généré. Réutiliser le timeout-guard existant de `core/tool_executor`.
3. Garde-fous : approval/`safety_boundary` déjà présents → les réutiliser.

**Risques** : `execute_code` = surface d'exécution de code → **élevé** si mal isolé,
mais le sandbox durci existe déjà. Exiger : sandbox obligatoire, budgets, audit log.

---

## Axe 4 — Gateway de messagerie unifié

**Existant Bea** : `connectors/` ne fait que `http_connector` (webhook/notif) +
`filesystem`/`github` ; `interfaces/kernel_adapter.py`. **Aucun adaptateur de
plateforme de messagerie.** C'est l'axe le plus neuf.

**Pattern Hermes** : `gateway/run.py` (`GatewayRunner`) + `gateway/platforms/`
(un adaptateur par plateforme, interface commune `on_message → MessageEvent`),
routage de session unifié, autorisation (allowlist + pairing), dispatch de commandes,
livraison sortante. Le cœur agent est réutilisé tel quel.

**Écart** : tout le gateway est à créer — mais **sur le cœur existant**
(`meta_orchestrator`) et le pattern `ConnectorRegistry`.

**Plan minimal (MVP 1 plateforme d'abord)**
1. Créer `gateway/` : `runner.py` (boucle de dispatch), `session.py` (mapping
   plateforme↔mission, réutiliser `api/mission_store`), `platforms/base.py`
   (ABC `PlatformAdapter` : `on_message`/`send`), `platforms/telegram.py` (MVP).
2. Réutiliser le cœur : un message entrant → `meta_orchestrator.run_mission(...)` →
   réponse livrée via l'adaptateur. **Zéro logique agent dupliquée.**
3. Autorisation : allowlist d'IDs + pairing, calquée sur `api/auth`.

**Risques** : sécurité (exposition externe), secrets de tokens. **Modéré/élevé** →
réutiliser `core/security` + `.env` + le durcissement existant. Commencer par 1
plateforme derrière allowlist.

---

## Séquencement proposé (dépendances)

1. **Axe 3 (`execute_code`/`delegate`)** — fort effet de levier, s'appuie sur le
   sandbox déjà durci, autonome.
2. **Axe 2 (mémoire FTS5 + user-model)** — améliore tout le reste (meilleur contexte).
3. **Axe 1 (boucle skills)** — bénéficie de la mémoire améliorée.
4. **Axe 4 (gateway)** — dernier : dépend d'un cœur agent stable et réutilisé.

**Pré-requis bloquant à tous** : la suite `pytest` doit être verte (P1) avant
d'ajouter ces surfaces — sinon on construit sur du non-validé.

## Ce qu'on NE fait PAS
- Pas de réécriture des systèmes existants (self_improvement, memory, executor).
- Pas de nouvelle arborescence parallèle ni de duplication.
- Pas d'implémentation avant validation de cet ADR + tests verts.

## Prochaine étape
Tu valides l'ADR (et l'ordre), je commence par l'axe choisi en mode **minimal +
testable**, un module à la fois, diff montré et validé à chaque étape.
