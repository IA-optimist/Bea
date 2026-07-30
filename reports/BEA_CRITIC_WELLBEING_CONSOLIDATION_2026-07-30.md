# Consolidation canonique critic/wellbeing — 2026-07-30

Statut du document : rapport de consolidation et preuve de validation. Le
contrat et la matrice différentielle ont été créés dans le premier commit,
avant l'implémentation principale.

## Références et préflight

| Référence | SHA vérifié | Rôle |
|---|---|---|
| `origin/main` | `a2f7ec4cb7e363c5901f26087fe0deb116f49049` | base immuable |
| `recovery/july-2026-working-tree-accented-2ab7fb4f` | `0588a9284f12ae496d93662af42aee376dcf8cd0` | variante accentuée |
| `recovery/july-2026-working-tree-ascii-bb4e956e` | `dcfbce5dbe89a3ac136fd9252031215e85468fa1` | variante ASCII |
| `recovery/july-2026-affective-chain-f7647511` | `f7647511f752d97c4989b499dbe67c212b3bc382` | chaîne affective originale |

- Worktree créé proprement depuis `origin/main` :
  `C:\Users\maxen\Documents\Bea-consolidation-july-critic-wellbeing`.
- Branche : `consolidation/july-critic-wellbeing-hybrid`.
- La branche distante homonyme était absente au préflight.
- Tip d'implémentation avant le commit de ce rapport :
  `9e9ec95414caba842c2c448266522247b5d80ea5`.
- Aucun cherry-pick, merge, rebase ou force-push n'a été utilisé.

## Matrice différentielle

| Élément | `main` | Accentué `0588a928` | ASCII `dcfbce5d` | Affective `f7647511` | Décision canonique | Preuve |
|---|---|---|---|---|---|---|
| Autorité standard | `KernelEvaluator` sur `MetaOrchestrator` | critic V2 parallèle | critic V2 parallèle | chemin de main | conserver le Kernel comme autorité du chemin standard | `OutcomeMixin._handle_success_outcome` évalue avant `DONE` |
| Seuil global | critic historique `6.0`, Kernel `0.50` | `6.0` plus gates implicites `7.0/7.5` | `6.0` plus gates marginaux | `6.0` | source unique `6.0`, soit `0.60` Kernel | constante exportée et tests de frontière |
| Données invalides | validation partielle | `NaN`/infini possibles | idem | idem | score ou confiance invalide = erreur structurée | tests score/VAD invalides |
| Critic naturel | retry Kernel partiel | rerun V2 | rerun V2 | idem | rerun uniquement sur échec structuré, jamais sur PASS | policy et runtime tests |
| Critic forcé | absent | pression/viabilité pouvait forcer | distinction naturel/forcé | absent | gate serveur explicite, défaut off, PASS marginal seulement | setting et tests |
| Ressources | non reliées au retry Kernel | viabilité non réservante | pénurie pouvait déclencher | télémétrie VAD | ressources = permission, jamais déclencheur | `ResourceGuard` + slot, standard et V2 |
| Rerun | résultat parfois choisi par longueur | dernier résultat | dernier résultat | dernier résultat | naturel : candidat `ACCEPT`; forcé : `ACCEPT` et score supérieur | tests de dégradation et verdict incohérent |
| Échec critic | fallback pouvant passer | sortie conservée | sortie conservée | sortie conservée | exception terminale/score invalide ne peut pas produire `DONE` | tests lifecycle |
| VAD | absent | copie de la chaîne | absent | dynamique ordre 2, `.6/.5` | reconstruction validée, bornée, transactionnelle | tests de propriétés |
| Wellbeing | absent | tracker global et cycle nocturne | absent | homeostasis simple | télémétrie fonctionnelle éphémère par mission | aucune écriture et isolation testées |
| Persistance | métadonnées de mission | tracker et historique | improvement memory | aucune isolation | historique critic expurgé; aucune persistance affective ou d'amélioration | tests + suppression du write V2 |
| Méta-plasticité | absente | non prouvée | non prouvée | absente | explicitement désactivée | constante `False`, config immuable |
| Guidance affective | absente | injection de ton | absente | injection de ton | rejetée | aucune injection dans le diff |

## Contrat fonctionnel canonique

### Critic naturel

- Le handler standard passe de `RUNNING` à `REVIEW`, puis appelle
  `KernelEvaluator`.
- `CRITIC_OVERALL_PASS_THRESHOLD = 6.0`; l'échelle Kernel dérivée vaut `0.60`.
- Un `KernelScore` passant ne déclenche aucun rerun naturel.
- Un score sous le seuil, `passed=false` ou `retry_recommended=true` demande au
  plus un rerun canonique, si les ressources et le budget le permettent.
- Le rerun est réévalué. Il remplace l'original insuffisant seulement si sa
  décision est `ACCEPT`, même si le score incohérent de l'original était
  numériquement supérieur.

### Critic forcé

- Il exige `BEA_CRITIC_FORCE_MARGINAL_RERUN=true`, désactivé par défaut.
- Il exige un résultat naturellement passant, un signal structuré explicite,
  une mission de plus de 80 caractères, aucun rerun/retry antérieur et
  `ResourceGuard=NORMAL`.
- Un candidat forcé ne remplace l'original que s'il est `ACCEPT` et strictement
  mieux noté. Toute erreur ou insuffisance conserve le PASS original.
- Aucune identité fournie par un client n'active le gate ou ne sert
  d'autorisation.

### Bornes, ressources et absence de boucle

- Le chemin canonique effectue zéro ou un rerun.
- Le suffixe interne, le drapeau du `MissionContext`, `asyncio.wait_for` et le
  slot `ResourceGuard` empêchent récursion et travail non borné.
- `NORMAL` et `SOFT_WARN` permettent un rerun naturel; `SAFE`, `BLOCKED` et
  `UNKNOWN` le refusent. Le forcé exige `NORMAL`.
- Le chemin de compatibilité V2 garde son budget de deux réservations
  atomiques, mais exige également `ResourceGuard` en `NORMAL`/`SOFT_WARN` et un
  slot disponible. Il ne décide pas le statut terminal canonique.

### Wellbeing et VAD

- « Wellbeing » décrit uniquement un état logiciel fonctionnel. Il ne prétend
  ni conscience, ni émotion ressentie, ni intériorité.
- L'ordre VAD est valence, arousal, dominance.
- État/cible sont finis dans `[-1,1]`; vitesse finie dans `[-2,2]`.
- Dynamique : `vitesse = .6 * vitesse + .4 * (cible - état)`, puis
  `état = clip(état + .5 * vitesse)`.
- Momentum `0.6`, taux `0.5`, baseline `(0,0,0)` et trajectoire maximale `64`
  sont explicites et immuables.
- Les constructeurs publics et les mises à jour rejettent types, shapes,
  `NaN`, infinis et valeurs hors bornes avant mutation.
- `NORMAL`/`SOFT_WARN` donnent une observation connue. `UNKNOWN`, `SAFE`,
  `BLOCKED` ou données invalides restent `known=false` et ne sont jamais
  présentés comme un état sain.

### Persistance, isolation et échecs

- VAD/wellbeing est recréé pour chaque évaluation et reste en mémoire.
- L'historique du singleton critic de compatibilité est borné et expurgé des
  tâches, sorties, feedbacks, suggestions et identifiants de session bruts.
- Le scope de session sert de corrélation interne, jamais d'identité de
  sécurité. L'accès applicatif doit rester authentifié en amont.
- Le chemin V2 ne persiste plus tâche/feedback/score dans
  `improvement_memory`.
- Une exception terminale de l'évaluateur, un verdict invalide ou un rerun
  naturel toujours insuffisant place la mission standard en `FAILED`; le
  circuit breaker n'enregistre pas un faux succès.

## Décisions hybrides et provenance

Aucun fichier source n'a été cherry-pické. Les sources ont fourni des preuves
de comportement; l'implémentation a été reconstruite manuellement sur la base
`main`.

| Composant | Source retenue | Modification | Tests | Statut |
|---|---|---|---|---|
| seuil `6.0` | main + accentué + ASCII | constante unique et échelle `0.60` | frontières et invalides | PASS |
| distinction naturel/forcé | concept ASCII | policy déterministe, gate serveur off | toutes décisions/ressources | PASS |
| télémétrie critic | concept ASCII | payload mission minimal | runtime | PASS |
| VAD ordre 2 | chaîne affective | reconstruction bornée `.6/.5` | propriétés et invalides | PASS |
| homeostasis | chaîne affective + accentué | état éphémère sans autorité sécurité | ressources/charge/status | PASS |
| ResourceGuard | reconstruction minimale | permission + réservation standard/V2 | statuts et slot | PASS |
| sélection résultat | reconstruction minimale | PASS prioritaire; forcé strictement meilleur | dégradation/verdict FAIL | PASS |
| isolation critic | reconstruction minimale | historique expurgé et registres bornés | deux sessions/cardinalité | PASS |
| `7.0`/`7.5` | rejet des variantes | aucun port | absence dans policy | PASS |
| tracker nocturne | rejet accentué | aucun port | aucune écriture | PASS |
| guidance de ton | rejet affectif/accentué | aucun port | aucune injection | PASS |
| méta-plasticité | rejet des trois | hard-disabled | immutabilité | PASS |

## Matrice finale par fichier

| Fichier | Source/provenance | Rôle retenu |
|---|---|---|
| `.env.example`, `config/settings.py` | reconstruction | gate forcé serveur, défaut désactivé |
| `kernel/evaluation/scorer.py` | main + seuil concordant | seuil unique, validation finie, erreur structurée |
| `kernel/runtime/kernel.py` | reconstruction | exception evaluator = échec, jamais PASS implicite |
| `core/orchestration/critic_policy.py` | concept ASCII, reconstruction | décision naturel/forcé/bloqué/erreur |
| `core/orchestration/outcome_mixin.py` | main, reconstruction ciblée | gate lifecycle, ResourceGuard, réévaluation, meilleur résultat valide |
| `core/orchestrator_v2.py` | main, compatibilité corrigée | réservation atomique, ResourceGuard, meilleur score, aucune persistance globale |
| `core/self_critic.py` | main + seuil concordant | scores bornés, compteurs isolés, historique expurgé |
| `core/affect_state.py` | équation affective, reconstruction | VAD borné et transactionnel |
| `core/wellbeing.py` | homeostasis affective, reconstruction | télémétrie éphémère et statuts prudents |
| `tests/test_canonical_critic_contract.py` | nouveau | seuils, policy, isolation, concurrence |
| `tests/test_canonical_critic_runtime.py` | nouveau | lifecycle, reruns, erreurs, faux `DONE` |
| `tests/test_functional_wellbeing.py` | nouveau | VAD/wellbeing/invariants/persistance |
| `tests/test_orchestrator_v2_runtime.py` | main étendu | compatibilité, meilleur résultat, ResourceGuard |
| `docs/CRITIC_WELLBEING.md` | nouveau | claims fonctionnels, limites et exploitation |
| `reports/BEA_CRITIC_WELLBEING_CONSOLIDATION_2026-07-30.md` | nouveau | contrat, provenance et preuves |

## Éléments explicitement rejetés

- `core/wellbeing_tracker.py` accentué : état global, fichiers runtime et cycle
  nocturne.
- Guidance/injection de ton de `core/affect_state.py` et des orchestrateurs
  récupérés : politique non prouvée et état inerte.
- Seuils secondaires `RIGOR_FLOOR=7.0` et `7.5`.
- Pression de ressources comme déclencheur de rerun.
- `tests/core/analyze_critic_forcing.py` et tests de forcing des snapshots :
  mécanisme dangereux ou couplé à l'architecture récupérée.
- Characterization scripts et audits de recherche historiques : preuves
  consultées, mais non portées comme runtime canonique.
- Snapshots complets de `core/meta_orchestrator.py`, `core/orchestrator_v2.py`,
  `core/self_critic.py` et `core/affect_state.py`.
- Telegram, cancellation, identity/principal/approval/auth, SessionStore,
  Beta Doctor, private readiness, Cyber Foundation, Verifier complet et APK.

## Commits d'implémentation

| SHA court | Commit |
|---|---|
| `fe4a8fc` | `docs(affect): define canonical critic and wellbeing contract` |
| `bbd14a5` | `test(critic): define canonical critic and rerun behavior` |
| `bbe2a75` | `test(wellbeing): define VAD and functional state invariants` |
| `972a688` | `feat(critic): implement bounded natural and forced critic policy` |
| `9d9f431` | `feat(wellbeing): implement bounded mission-scoped affect state` |
| `ce7b910` | `test(orchestration): define canonical critic lifecycle gate` |
| `a6f251f` | `feat(orchestration): wire critic and wellbeing into canonical runtime` |
| `0b75a65` | `docs(affect): document functional claims and runtime limits` |
| `3acd617` | `fix(quality): resolve touched critic and wellbeing diagnostics` |
| `d2d8bc4` | `fix(orchestration): retain only valid critic rerun results` |
| `5822500` | `fix(critic): isolate and bound compatibility state` |
| `3b779a8` | `fix(wellbeing): enforce public state and resource invariants` |
| `3ad4251` | `docs(affect): clarify rerun and restricted-resource semantics` |
| `2ff0c95` | `fix(critic): remove global improvement persistence` |
| `9e9ec95` | `fix(critic): resource-gate compatibility reruns` |

## Validation et qualité

| Contrôle | Commande/résultat | Statut |
|---|---|---|
| Compilation | `py_compile` des 13 fichiers Python touchés | PASS |
| Ruff touché | `ruff check` sur tous les Python touchés, 0 diagnostic | PASS |
| Tests ciblés | 218 réussis, 2 ignorés, 1 avertissement | PASS |
| Tests critic/V2 après revue | 171 puis 17 puis 4 réussis sur les correctifs successifs | PASS |
| Gate rapide | `scripts/validate_local.py --quick`; 149 tests critiques; MyPy `864 <= 870` | PASS |
| Vérité documentaire | `DOCS_TRUTH_SYNC: true` | PASS |
| Suite complète finale | `PENDING_FINAL_FULL_SUITE` | EN COURS |
| Gitleaks stagé | avant chaque commit, config dépôt + ignore + `--redact=100` | PASS |
| Gitleaks plage finale | `PENDING_FINAL_RANGE_SCAN` | EN COURS |

Les avertissements observés sont des dépréciations existantes
`python_multipart`, `httpx` et `datetime.utcnow`; aucun contournement de test ou
abaissement de gate n'a été ajouté.

## Revue de sécurité et périmètre

- Aucun secret, `.env`, token, clé, credential, base locale, cache ou état
  runtime n'est inclus.
- Le répertoire non suivi `MagicMock/`, créé par la suite de tests, est un
  artefact runtime exclu; il sera déplacé hors du worktree avant publication.
- Aucun appel outil direct, identité cliente de sécurité, boucle non bornée,
  état VAD global, auto-amélioration activée ou revendication de conscience
  n'est ajouté.
- Le gate forcé est serveur, désactivé par défaut.
- Le diff ne contient aucun fichier Telegram, cancellation, approval/auth,
  SessionStore, Beta Doctor, Cyber, APK ou chantier privé.
- Aucun fichier versionné n'est supprimé.

## Limites et risques restants

- Le gate lifecycle couvre le handler standard `MetaOrchestrator`.
  Les fast paths historiques chat, creative, BeaTeam et alignment peuvent
  terminer avant ce handler; ils restent explicitement hors périmètre.
- `OrchestratorV2.run_dag` reste un chemin de compatibilité à scores
  historiques `0..10`; il est borné et resource-gated, mais ne remplace pas
  l'autorité Kernel du chemin standard.
- Les métadonnées `kernel_score` historiques peuvent contenir des faiblesses
  textuelles déjà produites par le Kernel. Ce chantier n'ajoute aucune sortie
  brute à une persistance globale.
- Une future persistance wellbeing par utilisateur ou toute méta-plasticité
  exige un chantier séparé, un scope serveur authentifié et un opt-in explicite.

## Publication

Le push non destructif, la vérification du SHA distant et la PR brouillon sont
effectués seulement après la suite complète finale, le scan Gitleaks exact et
la propreté du worktree. Le SHA distant et l'URL de PR sont consignés dans le
handoff final, car ils sont produits après le commit de ce rapport.
