"""business_agents/ — Factory de templates d'agents métier.

Système **template-driven** pour générer, tester et opérer des agents
réutilisables (factory.py, template_registry.py, templates/). Produit
des artefacts consommés par le runtime ; ne s'exécute pas lui-même
pendant une mission.

Frontières avec les autres namespaces agents :

- ``agents/`` — Agents **runtime** invoqués par le MetaOrchestrator
  pendant l'exécution d'une mission. C'est là que vivent les classes
  BaseAgent spécialisées (crew, finance, market_research, …).
- ``agent_marketplace/`` — Marketplace commerciale (achat/vente,
  revenue share). Hors du chemin d'exécution principal.

Règle : tout ce qui produit / enregistre / teste des templates vit ici.
"""
