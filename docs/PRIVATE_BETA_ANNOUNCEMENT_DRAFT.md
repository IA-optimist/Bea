# Béa — Private Beta Announcement Drafts

> Brouillons à adapter par Max. Ne pas publier tels quels sans relecture.
> Ne jamais écrire : "production ready", "stable", "autonome en prod", "remplace Claude/Codex", "sécurité garantie".

---

## Version 1 — Message privé pour inviter un testeur technique

Objet : Invitation bêta privée — Béa (agent IA Python, developer preview)

---

Salut [Prénom],

Je travaille sur Béa, un agent IA multi-agent en Python (FastAPI + Docker). J'arrive à un stade où j'ai besoin de testeurs techniques pour casser le système proprement avant d'aller plus loin.

C'est une bêta privée, pas grand public :
- **Ce que c'est** : un runtime d'agent IA avec policy engine, approval gates, et un pipeline de mission complet
- **Ce que ce n'est pas** : stable, production-ready, ou autonome sans supervision
- **Ce qu'on cherche** : des gens qui vont tester des cas nominaux et des cas limites, lire des logs, et écrire des rapports utiles

Ce que tu peux tester : soumettre des missions via l'API REST, observer le comportement du PolicyEngine, tester les providers LLM (OpenRouter, Ollama), vérifier la cohérence des logs.

Ce que tu ne peux pas faire : données réelles, systèmes de prod, cyber offensif.

Si tu es partant, je t'envoie un token d'accès et le guide de démarrage. Prévoir ~1h pour l'installation et les premiers tests.

Des questions ?

Max

---

## Version 2 — Mini post LinkedIn (uniquement si GO)

> Utiliser seulement si PRIVATE_BETA_READY: true et si Max décide de communiquer publiquement.

---

Je lance la bêta privée de Béa — developer preview, 5 à 10 testeurs max.

Béa est un runtime d'agent IA que je développe depuis plusieurs mois : pipeline de missions, policy engine, approval gates, mémoire vectorielle, providers LLM multiples. Ce n'est pas encore une bêta publique — c'est une developer preview.

Je cherche quelques testeurs techniques qui veulent :
- explorer le comportement d'un agent sur des missions structurées
- tester les limites du système (logs, erreurs, edge cases)
- écrire des rapports de feedback utiles

L'objectif : casser proprement le système avant d'ouvrir plus large. Les bugs documentés maintenant valent mieux que les bugs découverts en prod.

Stack : Python 3.11, FastAPI, Docker, OpenRouter. Pas besoin de GPU.

Intéressé·e ? Envoie-moi un message privé. Je réponds à 5–10 personnes maximum.

---

*Note : Béa n'est pas production-ready. Elle n'est pas autonome sans supervision. Elle ne remplace pas Claude, Codex, ou tout autre service commercial. C'est un projet de recherche/apprentissage en cours.*
