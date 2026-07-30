# Critic et wellbeing fonctionnel

Ce document décrit le pipeline canonique de contrôle qualité et sa télémétrie
VAD. Le terme « wellbeing » désigne ici un état logiciel fonctionnel et borné.
Il ne constitue aucune revendication de conscience, de ressenti, d'émotion
subjective ou d'identité.

## Autorité et chemin runtime

`KernelEvaluator` est l'unique autorité d'évaluation du chemin standard :

```text
MetaOrchestrator
  -> exécution supervisée
  -> OutcomeMixin (REVIEW)
  -> KernelEvaluator
  -> politique critic + ResourceGuard
  -> zéro ou un rerun
  -> réévaluation
  -> DONE seulement après PASS, sinon FAILED
```

Le seuil public est `CRITIC_OVERALL_PASS_THRESHOLD = 6.0`. Comme
`KernelScore` utilise une échelle `0..1`, son seuil est dérivé à `0.60`.
Le critic historique à quatre dimensions conserve également son seuil
dimensionnel `5.0`.

Tout score ou niveau de confiance non numérique, non fini ou hors bornes
produit une erreur critic structurée. Il ne peut pas devenir un PASS implicite.

## Critic naturel

Un rerun naturel est demandé si le `KernelScore` :

- est inférieur à `0.60` ;
- n'est pas marqué `passed` ;
- ou recommande explicitement un retry.

Un PASS naturel ne déclenche aucun rerun. Le chemin canonique autorise au plus
un rerun critic par mission, en plus des retries d'exécution déjà comptabilisés.
Le critic de compatibilité conserve un budget de deux réservations atomiques,
isolées par mission, agent et tâche.

Un rerun naturel n'est permis que si ResourceGuard rapporte `NORMAL` ou
`SOFT_WARN` et si un slot peut être réservé. `SAFE`, `BLOCKED` et `UNKNOWN`
interdisent le travail supplémentaire. Une pénurie de ressources n'est jamais
un déclencheur.

## Critic forcé

Le rerun forcé est désactivé par défaut. Il exige simultanément :

- le gate serveur `BEA_CRITIC_FORCE_MARGINAL_RERUN=true` ;
- un résultat qui passe déjà le critic naturel ;
- un signal structuré explicite (`weaknesses` ou verdict `low_confidence`) ;
- une mission non triviale de plus de 80 caractères ;
- aucun rerun critic ni retry d'exécution antérieur ;
- ResourceGuard en statut `NORMAL` et un slot disponible.

Il n'existe aucun seuil secondaire `7.0` ou `7.5`. Le gate ne peut pas être
activé par une valeur d'identité fournie par un client.

Un échec du rerun forcé conserve le résultat naturellement valide. Un rerun
naturel en erreur, bloqué ou toujours insuffisant empêche `DONE`.

## Sélection du meilleur résultat

Chaque rerun est évalué avec le même `KernelEvaluator`. Il remplace l'original
uniquement si son score est strictement supérieur. La longueur du texte n'est
pas un critère d'acceptation.

Les métadonnées de mission contiennent seulement la décision, les scores avant
et après, le delta, le statut ResourceGuard et le fait que le candidat a été
retenu. La tâche et les sorties brutes ne sont pas ajoutées à une mémoire
globale par ce pipeline.

## Wellbeing et VAD

L'état VAD suit l'ordre :

1. valence ;
2. arousal ;
3. dominance.

État et cible sont finis et bornés dans `[-1, 1]`. La dynamique conservée de la
chaîne affective de juillet est :

```text
vitesse = momentum * vitesse + (1 - momentum) * (cible - état)
état = clip(état + update_rate * vitesse)
```

Les paramètres canoniques sont :

- `momentum = 0.6`, avec `0 <= momentum < 1` ;
- `update_rate = 0.5`, avec `0 < update_rate <= 1` ;
- baseline `(0.0, 0.0, 0.0)` ;
- trajectoire mémoire limitée à 64 snapshots.

La configuration est immuable. Une cible ou une configuration invalide est
rejetée avant toute mutation. La vitesse est finie et bornée dans `[-2, 2]`.

`FunctionalWellbeing` traduit un snapshot ResourceGuard en ressources et charge
normalisées, puis en une cible VAD. Une observation `UNKNOWN` ou invalide
conserve le dernier état valide et reste marquée `known=false`.

## Persistance, isolation et méta-plasticité

- L'état VAD/wellbeing est recréé pour chaque évaluation de mission.
- Il n'est pas partagé entre utilisateurs ou missions.
- Il n'écrit aucun fichier et n'est pas persisté par défaut.
- Il ne contient aucune identité client.
- `METAPLASTICITY_ENABLED` vaut `False`.
- Aucun code, modèle, paramètre ou policy ne s'auto-modifie.

Une persistance par utilisateur nécessiterait un scope serveur authentifié et
fait partie d'un chantier distinct.

## Frontières connues

Le gate couvre le handler d'outcome standard du `MetaOrchestrator`, quel que
soit le delegate standard ou budgété. Plusieurs fast paths historiques
(certaines réponses chat, creative, BeaTeam et alignment) peuvent atteindre un
état terminal avant ce handler. Ils restent inchangés dans cette consolidation
afin de ne pas mélanger les politiques produit et les chantiers exclus.

Le VAD est une télémétrie bornée. Il n'injecte aucun ton dans les prompts et ne
modifie pas la décision de sécurité ; ResourceGuard demeure l'autorité de
permission pour les reruns.
