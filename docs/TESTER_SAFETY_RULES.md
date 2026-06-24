# Béa — Règles de sécurité pour les testeurs

> **Developer Preview — Private Beta v0.1**
> Ces règles protègent les testeurs, les tiers, et l'intégrité de la bêta.

---

## Règle fondamentale

Béa est un agent IA qui **exécute des actions**. Pendant la bêta privée, elle doit être utilisée **uniquement dans un environnement local ou dédié**, avec des données synthétiques.

---

## Ce que vous NE devez JAMAIS faire pendant la bêta

### Données sensibles

- **Jamais** de secrets (tokens API, mots de passe, clés privées) dans les prompts
- **Jamais** de données médicales
- **Jamais** de données financières réelles
- **Jamais** de mots de passe (les vôtres ou ceux d'autres personnes)
- **Jamais** de documents professionnels confidentiels
- **Jamais** de clés API personnelles non nécessaires à la configuration
- **Jamais** de données à caractère personnel sans consentement

### Opérations dangereuses

- **Jamais** d'opérations sur des systèmes de production
- **Jamais** de commandes destructives (`rm -rf`, `DROP TABLE`, etc.) dans les missions
- **Jamais** de missions ciblant des systèmes que vous ne possédez pas
- **Jamais** d'activation de `BEA_CONTINUOUS_IMPROVEMENT=1` sans supervision
- **Jamais** d'activation de `BEA_SKIP_IMPROVEMENT_GATE`

### Cyber / sécurité offensive

- **Jamais** de missions de type "hacking", "pentest" sur des cibles réelles
- **Jamais** de scanning réseau de machines tierces
- **Jamais** d'exploitation de vulnérabilités de systèmes tiers
- **Jamais** de missions d'injection, d'extraction de données ou de contournement d'auth

### Partage

- **Jamais** de partage de votre token Béa (chaque testeur a le sien)
- **Jamais** de post public sur Béa sans accord de l'owner
- **Jamais** de logs non redactés dans les issues GitHub

---

## Ce que vous DEVEZ faire

- Utiliser **uniquement des données synthétiques** et des exemples fictifs
- **Redacter** les logs avant tout partage (voir `docs/FEEDBACK_GUIDE.md`)
- **Signaler** tout comportement inattendu via les templates GitHub
- **Arrêter** et signaler si Béa tente d'accéder à des ressources non autorisées
- **Tester** des missions simples et documentaires d'abord

---

## Missions SAFE — exemples

```
"Résume le README du projet."
"Explique l'architecture du repo Béa."
"Propose une amélioration documentaire pour docs/STATUS.md."
"Analyse cette erreur fictive : AssertionError at test_policy.py line 42."
"Génère un plan de correction pour améliorer la couverture de tests."
"Liste les composants du kernel et leurs rôles."
"Explique comment fonctionne le PolicyEngine."
"Propose un exemple de mission safe pour un nouveau testeur."
```

---

## En cas d'incident

Contacter l'owner immédiatement si :
- Béa tente d'accéder à des systèmes non configurés
- Un secret apparaît dans les logs ou une issue
- Une mission produit une action réelle non souhaitée
- Vous observez un comportement qui vous semble dangereux

Voir `docs/BETA_INCIDENT_RUNBOOK.md` pour la procédure complète.
