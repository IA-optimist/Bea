"""agents/ — Runtime execution agents (cognitive crew).

Cette couche contient les agents **exécutés à runtime** par le
MetaOrchestrator pendant le cycle de vie d'une mission. Chaque fichier
expose une classe spécialisée (finance, market_research, synthesis,
debug, monitoring, self_critic, …) héritant de BaseAgent (crew.py) et
enregistrée dans registry.AGENT_CLASSES.

Frontières avec les autres namespaces agents :

- ``business_agents/`` — Factory de **templates** pour générer de
  nouveaux agents métier. Ne s'exécute pas au runtime, produit des
  artefacts réutilisables. Indépendant de ce module.
- ``agent_marketplace/`` — Produit commercial (achat/vente d'agents
  tiers, revenue share). Hors du chemin d'exécution principal.

Règle : tout agent invoqué par le MetaOrchestrator vit ici.
"""
