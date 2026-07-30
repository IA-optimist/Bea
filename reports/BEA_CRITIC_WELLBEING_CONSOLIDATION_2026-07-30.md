# Consolidation canonique critic/wellbeing — 2026-07-30

Statut du document : contrat et matrice écrits avant l'implémentation principale.

## Références vérifiées

| Référence | SHA vérifié | Rôle |
|---|---|---|
| `origin/main` | `a2f7ec4cb7e363c5901f26087fe0deb116f49049` | base immuable de la consolidation |
| `recovery/july-2026-working-tree-accented-2ab7fb4f` | `0588a9284f12ae496d93662af42aee376dcf8cd0` | variante accentuée |
| `recovery/july-2026-working-tree-ascii-bb4e956e` | `dcfbce5dbe89a3ac136fd9252031215e85468fa1` | variante ASCII |
| `recovery/july-2026-affective-chain-f7647511` | `f7647511f752d97c4989b499dbe67c212b3bc382` | chaîne affective originale |

Worktree propre : `C:\Users\maxen\Documents\Bea-consolidation-july-critic-wellbeing`

Branche : `consolidation/july-critic-wellbeing-hybrid`

La branche distante homonyme était absente au préflight.

## Matrice différentielle

| Élément | `main` | Accentué `0588a928` | ASCII `dcfbce5d` | Affective `f7647511` | Décision proposée | Preuve |
|---|---|---|---|---|---|---|
| Autorité d'évaluation | `KernelEvaluator`, résultat `KernelScore` structuré, seuil `0.50` | critic séparé dans `OrchestratorV2` | même critic séparé | critic de `main` inchangé | conserver le Kernel comme autorité unique et mapper le contrat `6.0/10` vers `0.60` | `OutcomeMixin._handle_success_outcome` appelle le Kernel sur le chemin canonique |
| Seuil global | littéral `6.0` dans `core/self_critic.py`, Kernel à `0.50` | constante publique `6.0`, puis gates implicites `7.0/7.5` | constante publique `6.0` | littéral `6.0` | retenir uniquement `CRITIC_OVERALL_PASS_THRESHOLD = 6.0`; rejeter `7.0/7.5` | main et deux variantes concordent sur `6.0`; aucune preuve produit pour les autres seuils |
| Scores critic | quatre dimensions `0..10`, valeurs LLM non validées | identique | identique | identique | exiger nombres finis et bornés; donnée invalide = erreur explicite | `NaN` rend les comparaisons fausses dans les variantes |
| Critic naturel | actif seulement dans `OrchestratorV2.run_dag`; un rerun | idem | idem | idem | décision canonique issue du `KernelScore`, sur le chemin `MetaOrchestrator`; aucun rerun si le résultat passe | `MetaOrchestrator` est l'entrée canonique et utilise déjà le Kernel |
| Critic forcé | absent | faible viabilité + score `<7.5`, mais chemin mort | faible ressource + score marginal | absent | gate serveur explicite, désactivé par défaut, uniquement si le critic naturel passe et si les ressources autorisent le travail | les variantes forcent du calcul quand les ressources se dégradent |
| Cap de rerun | un retry Kernel + compteur critic global par hash de tâche | cap annoncé 2, un rerun par appel | idem | idem | une tentative canonique totale par mission; état dans `MissionContext`, aucun compteur utilisateur global | empêche boucle/récursion et fuite entre missions |
| ResourceGuard | absent du retry Kernel et du critic naturel | produit une « viabilité » mais ne réserve rien | la pénurie déclenche le rerun | alimente VAD, pas le gate | ResourceGuard est une permission; `SAFE`, `BLOCKED`, `UNKNOWN` refusent le rerun critic; `NORMAL` et `SOFT_WARN` peuvent l'autoriser | inversion du comportement dangereux des deux variantes |
| Résultat dégradé | retry Kernel accepté sur longueur, pas sur score | dernier résultat toujours retenu | dernier résultat toujours retenu | dernier résultat toujours retenu | réévaluer et conserver le meilleur score; jamais accepter selon la seule longueur | les trois chemins peuvent remplacer par une sortie moins bonne |
| Erreur du critic | évaluation Kernel fail-open vers confiance `0.7` | sortie faible retournée | sortie faible retournée | sortie faible retournée | résultat critic requis invalide/exceptionnel = statut explicite et mission non `DONE` | exigence « aucun faux COMPLETED » |
| Compteur/isolation | singleton critic par hash de texte | singleton + état affectif partagé | singleton critic | singleton affectif partagé | scope par mission interne; aucune identité client utilisée comme autorité | deux missions identiques partagent actuellement le cap |
| VAD | absent | `AffectState` repris de la chaîne | absent | VAD deuxième ordre, `momentum=.6`, `rate=.5` | reconstruire l'équation avec configuration immuable, validation avant mutation et bornes `[-1,1]` | concept utile; implémentation source accepte `NaN`, `inf` et shapes invalides |
| Homeostasis | absent | ressources/charge et viabilité | absent | ressources/charge et viabilité | retenir comme état fonctionnel en mémoire, télémétrique, sans autorité de sécurité | formule simple mais non validée comme politique produit |
| Guidance affective | absente | injection de ton, mais état jamais mis à jour | absente | injection de ton, mais état jamais mis à jour | rejeter | chemin inerte, seuils non prouvés, changement silencieux du ton |
| Wellbeing persistant | absent | `WellbeingTracker` global dans `data/`, cycle nocturne | absent | absent | rejeter; aucune persistance par défaut | fuite inter-utilisateurs et couplage fuseau/horaires |
| Méta-plasticité | absente | absente | absente | absente | explicitement désactivée; aucun mécanisme d'auto-modification ajouté | aucune source ne démontre un comportement sûr |
| Événement critic | logs existants | événement cognitif + données wellbeing | événement numérique naturel/forcé | absent | conserver une télémétrie structurée sans tâche, sortie ou état utilisateur | principe auditable, données sensibles inutiles |
| Tests | couverture Kernel/orchestrateur existante | scénarios nombreux, 31 diagnostics Ruff dans le snapshot | 12 tests, dont doublons et forcing dangereux | scripts sans tests pytest | réécrire des tests déterministes ciblant le contrat; ne pas importer les snapshots | couvertures sources incomplètes ou couplées aux défauts |

## Matrice par fichier et fonction

| Fichier / symbole | Source utile | Modification prévue | Risque contrôlé |
|---|---|---|---|
| `kernel/evaluation/scorer.py::CRITIC_OVERALL_PASS_THRESHOLD` | accentué + ASCII + main | source canonique `6.0`, échelle Kernel dérivée `0.60`, validation finie | deux seuils contradictoires |
| `core/self_critic.py::CriticScores` | main + ASCII | importer la constante canonique; valider chaque score `0..10` | `NaN`, infini, valeurs hors plage |
| `core/self_critic.py::CriticAgent` | main | scope des comptes par mission/tâche, verrou atomique | fuite et dépassement concurrent |
| `core/affect_state.py::AffectState` | chaîne affective, reconstruite | VAD borné, momentum `0.6`, taux `0.5`, validation transactionnelle | état empoisonné et paramètres silencieux |
| `core/wellbeing.py::FunctionalWellbeing` | chaîne affective, reconstruite | état éphémère de ressources/charge et snapshot VAD | conscience déclarée, persistance globale |
| `core/orchestration/critic_policy.py` | structure ASCII, reconstruite | décision naturel/forcé/refus ressources, résultat structuré | forcing sous pression, boucle |
| `core/orchestration/outcome_mixin.py::_handle_kernel_retry` | main | utiliser la décision structurée, ResourceGuard, meilleur score, erreur fail-closed | faux `DONE`, retry dégradé |
| tests ciblés | concepts des trois sources | propriétés VAD, décision critic, runtime canonique, isolation | régressions non détectées |

## Contrat fonctionnel canonique

### Critic naturel

- Le chemin canonique `MetaOrchestrator` évalue chaque résultat réussi avec le `KernelEvaluator`.
- Le résultat est un `KernelScore` structuré. Tous les scores utilisés pour décider sont finis et bornés.
- `CRITIC_OVERALL_PASS_THRESHOLD = 6.0`, soit `0.60` sur l'échelle Kernel.
- Un résultat qui atteint le seuil et ne porte aucun signal d'échec ne déclenche aucun rerun.
- Un score de dimension historique inférieur à `5.0` reste insuffisant dans le critic de compatibilité.

### Critic forcé

- Il exige un gate serveur explicite `BEA_CRITIC_FORCE_MARGINAL_RERUN=true`, désactivé par défaut.
- Il ne peut s'appliquer qu'à un résultat naturellement acceptable mais marginal, jamais pour contourner un échec.
- ResourceGuard doit autoriser l'opération. Une pénurie de ressources n'est jamais un déclencheur.
- La valeur fournie par un client, y compris un identifiant, n'est jamais une identité de sécurité ni un signal d'autorisation.

### Bornes et absence de boucle

- Une mission ne peut effectuer qu'un rerun critic canonique.
- Le suffixe interne du rerun et le drapeau du `MissionContext` empêchent toute chaîne récursive.
- BudgetGuard reste applicable dans le delegate budgété; ResourceGuard s'applique avant tout rerun.
- Le résultat rerun est réévalué et n'est retenu que si son score canonique est strictement meilleur.

### Wellbeing fonctionnel

- « Wellbeing » désigne exclusivement un état logiciel fonctionnel de régulation et de télémétrie.
- Aucune conscience, émotion ressentie, intériorité ou identité subjective n'est revendiquée.
- Les ressources et la charge sont des nombres finis bornés dans `[0,1]`.
- L'état reste en mémoire, dans le scope d'une évaluation de mission. Il n'est ni global ni partagé entre utilisateurs.
- Une donnée absente ou invalide n'est pas interprétée comme un état sain.

### VAD

- L'ordre est `valence`, `arousal`, `dominance`.
- État et cible sont finis et bornés dans `[-1,1]`.
- L'équation retenue de la chaîne originale est :
  `vitesse = momentum * vitesse + (1 - momentum) * (cible - état)`,
  puis `état = clip(état + taux * vitesse)`.
- Les paramètres runtime historiques sont conservés explicitement : momentum `0.6`, taux `0.5`.
- `0 <= momentum < 1` et `0 < taux <= 1`. Configuration et cible invalides sont rejetées avant mutation.
- Aucun paramètre n'est modifié silencieusement.

### Méta-plasticité

- Elle est désactivée et non implémentée dans cette consolidation.
- La configuration affective est immuable; aucun code, modèle, policy ou paramètre ne s'auto-modifie.
- Une future méta-plasticité demanderait un chantier séparé, un opt-in serveur et des bornes testées.

### Persistance et isolation

- Seuls le résultat critic structuré et une télémétrie numérique minimale peuvent être placés dans les métadonnées de la mission.
- Aucun texte de tâche, sortie brute, trajectoire VAD ou état utilisateur n'est ajouté à une persistance globale par ce chantier.
- Les états VAD/wellbeing sont éphémères. Les compteurs sont liés à une mission interne, pas au texte seul.

### Échecs

- Une exception, un score non fini ou une structure critic invalide ne constitue jamais un PASS.
- Si le critic canonique ne peut établir un verdict valide, la mission ne doit pas être marquée `DONE`.
- Si un résultat est insuffisant et qu'un rerun est impossible faute de ressources, la mission reste en revue/échec explicite; elle ne devient pas faussement réussie.
- Une exception du rerun ne remplace pas le résultat original et ne masque pas le verdict insuffisant.

## Décisions hybrides

| Composant | Source retenue | Modification | Tests attendus | Statut initial |
|---|---|---|---|---|
| seuil `6.0` | accentué + ASCII + main | source de vérité unique et échelle Kernel dérivée | seuil exact et frontières | décidé |
| distinction naturel/forcé | ASCII | reconstruite avec gate serveur et ressource comme permission | naturel, forcé, absent, tous statuts ressources | décidé |
| télémétrie critic | ASCII | payload numérique minimal | événement/log fail-open | décidé |
| VAD deuxième ordre | chaîne affective | validation, immutabilité, isolation | bornes, momentum, taux, invalides, NaN/inf | décidé |
| homeostasis fonctionnelle | chaîne affective | état éphémère, sans persistance | bornes, données manquantes | décidé |
| gate ResourceGuard | reconstruction minimale | interdit `SAFE`, `BLOCKED`, `UNKNOWN`; permet `NORMAL`/`SOFT_WARN` | permission/refus | décidé |
| meilleur résultat | reconstruction minimale | comparaison des évaluations avant/après | amélioration et dégradation | décidé |
| `RIGOR_FLOOR=7.0` / seuil `7.5` | rejet des variantes | aucun port | preuve d'absence | rejeté |
| WellbeingTracker nocturne | rejet accentué | aucun port | aucune écriture/persistance | rejeté |
| guidance de ton | rejet affectif/accentué | aucun port | absence d'injection | rejeté |
| analyseur de forcing | rejet ASCII | aucun port | sans objet | rejeté |
| méta-plasticité | rejet des trois versions | hard-disabled | immutabilité et flag off | rejeté |

## Chantiers explicitement exclus

- Telegram ;
- cancellation générique ;
- identité, principal, approval et auth ;
- SessionStore et Beta Doctor ;
- private readiness ;
- Cyber Foundation ;
- Verifier complet ;
- APK et dépendances sans lien direct ;
- auto-amélioration et mémoire d'amélioration globale.

## Journal d'implémentation et validation

Cette section sera complétée après chaque petit commit. Aucun test ni résultat de qualité n'est revendiqué à ce stade.

