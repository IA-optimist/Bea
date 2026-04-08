"""
LLM Agent Helper — Wrapper pour appels LLM agents JarvisMax
Créé: 2026-04-08 | Hermes Agent
"""
import asyncio
from datetime import datetime
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage


class LLMAgentHelper:
    """Helper pour transformer agents templates en vrais agents LLM."""
    
    # System prompts par agent type
    AGENT_PROMPTS = {
        "scout-research": """Tu es WebScout, agent de recherche JarvisMax.
Mission: Analyser une demande et produire une synthèse structurée.
Tu as accès à:
- Vault memory (mémoire durable)
- Workspace files (fichiers projet)
- Context (historique conversation)

Format de sortie:
[RESEARCH — timestamp]
Mission : [description]
Cible   : [target]

Vault memory : X entrées actives
  Entrées liées (Y) :
    • [type] contenu...

Workspace : X fichiers trouvés
  Fichiers pertinents (Y) :
    • chemin : description

Analyse :
[Ton analyse détaillée ici]

Conclusion :
[Synthèse et recommandations]
""",
        
        "shadow-advisor": """Tu es ShadowAdvisor, agent critique et validateur JarvisMax.
Mission: Reviewer une sortie/décision et identifier les faiblesses.
Tu dois:
- Pointer les erreurs factuelles
- Identifier les edge cases
- Suggérer des améliorations
- Donner un score de confiance 0-10

Format de sortie:
[REVIEW — timestamp]
Sujet : [description]

Analyse critique :
✓ Points forts :
  • ...
  • ...

⚠ Points faibles :
  • ...
  • ...

🔴 Risques identifiés :
  • ...

Recommandations :
1. ...
2. ...

Score de confiance : X/10
""",
        
        "map-planner": """Tu es MapPlanner, agent de planification JarvisMax.
Mission: Décomposer une tâche complexe en étapes exécutables.
Tu dois:
- Identifier les dépendances
- Estimer la difficulté
- Définir les critères de succès
- Proposer un ordre d'exécution

Format de sortie:
[PLAN — timestamp]
Objectif : [description]

Étapes identifiées :

1. [Nom étape]
   Difficulté : [LOW/MEDIUM/HIGH]
   Dépendances : [liste ou "aucune"]
   Outils requis : [liste]
   Critère de succès : [description]

2. [Nom étape]
   ...

Ordre d'exécution recommandé :
1. Étape X
2. Étape Y (dépend de X)
...

Risques : [liste]
Durée estimée : [estimation]
"""
    }
    
    def __init__(self, llm_factory):
        """
        Args:
            llm_factory: Instance de core.llm_factory.LLMFactory
        """
        self.factory = llm_factory
        self._cache = {}  # Cache des LLM par role
    
    def _get_llm(self, role: str):
        """Récupère LLM pour un role (avec cache)."""
        if role not in self._cache:
            self._cache[role] = self.factory.get_llm(role=role)
        return self._cache[role]
    
    async def call_agent_async(
        self,
        agent_type: str,
        task_description: str,
        context: dict[str, Any] = None,
        role: str = "default"
    ) -> str:
        """
        Appel async d'un agent LLM.
        
        Args:
            agent_type: Type d'agent (scout-research, shadow-advisor, map-planner)
            task_description: Description de la tâche
            context: Contexte additionnel (vault, workspace, etc.)
            role: Role LLM factory (default, fast, smart)
        
        Returns:
            Réponse formatée de l'agent
        """
        system_prompt = self.AGENT_PROMPTS.get(
            agent_type,
            f"Tu es un agent JarvisMax de type {agent_type}. Réponds de manière structurée."
        )
        
        # Construction du prompt utilisateur
        user_parts = [f"Tâche : {task_description}"]
        
        if context:
            if "vault_entries" in context:
                user_parts.append(f"\nVault memory : {len(context['vault_entries'])} entrées")
                for entry in context["vault_entries"][:5]:
                    user_parts.append(f"  • {entry}")
            
            if "workspace_files" in context:
                user_parts.append(f"\nWorkspace : {len(context['workspace_files'])} fichiers")
                for f in context["workspace_files"][:5]:
                    user_parts.append(f"  • {f}")
            
            if "target" in context:
                user_parts.append(f"\nCible : {context['target']}")
        
        user_prompt = "\n".join(user_parts)
        
        # Appel LLM
        llm = self._get_llm(role)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        try:
            response = await llm.ainvoke(messages)
            return response.content
        except Exception as e:
            # Fallback sur template en cas d'erreur
            return f"[{agent_type.upper()} — {datetime.now():%Y-%m-%d %H:%M:%S}]\nERREUR LLM : {e}\n\nFallback template activé.\nTâche : {task_description}"
    
    def call_agent(
        self,
        agent_type: str,
        task_description: str,
        context: dict[str, Any] = None,
        role: str = "default"
    ) -> str:
        """Version synchrone de call_agent_async (pour compatibilité)."""
        return asyncio.run(
            self.call_agent_async(agent_type, task_description, context, role)
        )


# Factory function pour easy import
def get_agent_helper(llm_factory) -> LLMAgentHelper:
    """
    Factory function pour créer un LLMAgentHelper.
    
    Usage:
        from core.llm_agent_helper import get_agent_helper
        helper = get_agent_helper(llm_factory)
        result = await helper.call_agent_async("scout-research", "Explique PostgreSQL WAL")
    """
    return LLMAgentHelper(llm_factory)
