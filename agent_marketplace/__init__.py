"""agent_marketplace/ — Produit commercial (place de marché d'agents).

Module indépendant exposant la logique de marketplace (listing d'agents,
workflows, revenue share via Stripe Connect, analytics). N'invoque pas
le MetaOrchestrator ; n'est pas invoqué par lui.

Frontières avec les autres namespaces agents :

- ``agents/`` — Agents runtime de la crew cognitive.
- ``business_agents/`` — Factory de templates réutilisables.

Règle : tout ce qui concerne l'économie du produit (achat/vente, abonnements,
commissions) vit ici, séparé du chemin d'exécution des missions.
"""
