# Béa — Feuille de route « capacités » (réaliste, sans promesse d'AGI)

_2026-06-01 · Principe : l'intelligence est dans le **modèle**, Béa est le **harnais**.
Ces axes rendent Béa plus capable, mesurable et fiable — ils ne « fabriquent » pas
d'AGI (problème de recherche non résolu). Objectif : être le meilleur harnais possible
autour de modèles toujours meilleurs._

## Pré-requis (déjà identifiés)
Avant tout : `pytest` complet vert (venv 3.12 + services), retirer `.git\index.lock`,
activer les branchements opt-in (tracer LLM, mémoire FTS, connecteurs, etc.).
Sans mesure fiable, « progresser en capacité » n'est pas vérifiable.

---

## C1 — Évaluation (le socle : on n'améliore que ce qu'on mesure)
**Pourquoi** : sans benchmark reproductible, « plus intelligent » est une impression.
- Constituer un **jeu de missions de référence** (succès/échec attendus) par domaine
  (code, recherche, business, outils). Base existante : `core/self_improvement/benchmark_suite.py`.
- Score par run : taux de succès, coût (via `core/observability/llm_tracer.py`),
  latence, nb d'étapes, taux d'intervention humaine.
- **Suivi de régression** dans le temps + comparaison entre modèles (Bea v3.1 vs Codex vs autres).
- Livrable : `bea eval` (CLI) qui produit un rapport chiffré.

## C2 — Calibration & incertitude (« savoir ce qu'on ne sait pas »)
**Pourquoi** : un agent autonome fiable doit refuser/escalader quand il n'est pas sûr.
- Faire produire au modèle une **confiance calibrée** par décision (et la mesurer
  contre la réalité : courbe de calibration).
- Politique : si confiance < seuil → demander approbation / déléguer / s'arrêter
  (s'appuie sur `governance` + modes d'approbation existants).
- Réduire les hallucinations sur les chemins d'action (vérification avant d'agir).

## C3 — Boucle d'apprentissage qui « tient » (mémoire procédurale)
**Pourquoi** : capitaliser sur l'expérience sans réentraîner le modèle.
- Fermer la boucle : mission réussie → `propose_skill_from_mission` →
  validation → `skill_registry` → réutilisation → `skill_feedback` (amélioration à l'usage).
- Nudges périodiques d'extraction (`night_worker`).
- **Mesurer** que la boucle aide vraiment (C1) : taux de succès qui monte sur les
  missions répétées. _Note : c'est de l'apprentissage **par mémoire/skills**, pas
  une mise à jour des poids — la vraie limite vers l'AGI._

## C4 — Mémoire & modèle du monde
**Pourquoi** : meilleur contexte = meilleures décisions.
- Recall hybride : vectoriel (Qdrant) + plein-texte (FTS5, déjà posé) + résumés de session.
- `UserModel` (déjà posé) injecté en contexte (préférences, faits stables).
- **Auto-réorganisation** (`memory/consolidator.py`, déjà posé) : synthèse des vieux
  souvenirs, mémoire bornée. _Limite honnête : ça reste une mémoire externe, pas un
  world-model causal — frontière de recherche._

## C5 — Robustesse de la boucle autonome (long-horizon)
**Pourquoi** : tenir une mission longue sans dériver ni s'emballer.
- Budgets explicites (temps/tokens/coût) par mission + **kill-switch**.
- Circuit-breaker sur panne provider, retries+backoff (briques présentes), reprise après erreur.
- Auto-critique/replanification (`self_critic`, `evaluator`) déclenchées sur signaux d'échec.
- **Mesurer** la dérive : taux de complétion sur missions multi-étapes (C1).

## C6 — Observabilité & sécurité au niveau d'autonomie
**Pourquoi** : plus c'est autonome, plus il faut voir et borner.
- Traçage LLM (coût/erreurs/qualité, posé) + traces de mission exploitables.
- Garde-fous d'exécution (sandbox durci, policy, capacités) — déjà solides.
- Tests adversariaux : injection de prompt, évasion sandbox, actions dangereuses.

## C7 — Élargir l'action dans le monde (utilité réelle)
**Pourquoi** : une intelligence utile agit, pas seulement raisonne.
- Connecteurs (lot posé : email/Slack/Telegram/Discord/Notion + **auto-extension** par spec).
- Multi-plateforme (gateway posé) + PWA de supervision (posée).
- Chaque nouvelle action = sous garde-fou + évaluée (C1/C6).

---

## Ce qui reste hors de portée d'un harnais (recherche, pas du code applicatif)
- Apprentissage continu **dans les poids**, en ligne, à partir de l'expérience.
- Généralisation hors-distribution / raisonnement causal robuste.
- Abstraction & compositionnalité de niveau humain, efficacité en données.
Ces points dépendent du **modèle** et de la recherche frontière — Béa les *consomme*,
ne les *résout* pas.

## Ordre conseillé
**C1 (évals) d'abord** — c'est ce qui rend tout le reste mesurable — puis C2/C5
(fiabilité), C3/C4 (apprentissage & mémoire), C6/C7 en continu. Brancher des modèles
meilleurs reste le plus gros levier de capacité brute.
