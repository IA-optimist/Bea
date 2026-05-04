"""
LangChain Orchestrator - Multi-LLM orchestration with LangChain

Features:
- Multi-LLM support (OpenRouter, Anthropic, OpenAI)
- Tool integration and registry
- Memory management
- Agent creation and management
- Streaming support
"""

import asyncio
import json
from typing import Dict, List, Any, Optional
from loguru import logger

try:
    from langchain.agents import create_agent, Tool
    from langchain_community.chat_models import ChatOpenRouter, ChatAnthropic, ChatOpenAI
    from langchain_openai import ChatOpenAI as LangChainOpenAI
    from langchain.memory import ConversationBufferMemory, ConversationSummaryMemory
    from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
    from langchain_core.messages import SystemMessage
    from langchain_core.runnables import RunnablePassthrough
    from langchain_core.output_parsers import StrOutputParser
    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False

from src.orchestrators.orchestrator_factory import BaseOrchestrator
from src.agents.langchain_agent import LangChainAgent
from src.utils.tool_registry import ToolRegistry

class LangChainOrchestrator(BaseOrchestrator):
    """LangChain orchestrator for multi-LLM agent orchestration"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.framework_name = 'langchain'
        
        if not LANGCHAIN_AVAILABLE:
            raise ImportError("LangChain not available. Install with: pip install langchain langchain-community")
        
        self.tool_registry = ToolRegistry(config)
        self.agents: Dict[str, LangChainAgent] = {}
        self.llm_configs = self._load_llm_configs()
        
    def _load_llm_configs(self) -> Dict[str, Dict[str, Any]]:
        """Load LLM configurations"""
        return self.framework_config.get('providers', {})
    
    def _get_llm(self, provider: str = 'default', model: str = None):
        """Get configured LLM"""
        provider_config = self.llm_configs.get(provider, {})
        
        if model is None:
            model = provider_config.get('default_model', 'deepseek/deepseek-v4-pro')
        
        if 'openrouter' in provider.lower():
            return ChatOpenRouter(
                model=model,
                temperature=provider_config.get('temperature', 0.7),
                max_tokens=provider_config.get('max_tokens', 4000),
                openrouter_api_key=provider_config.get('api_key')
            )
        elif 'anthropic' in provider.lower():
            return ChatAnthropic(
                model=model,
                temperature=provider_config.get('temperature', 0.7),
                max_tokens=provider_config.get('max_tokens', 4000),
                anthropic_api_key=provider_config.get('api_key')
            )
        elif 'openai' in provider.lower():
            return LangChainOpenAI(
                model=model,
                temperature=provider_config.get('temperature', 0.7),
                max_tokens=provider_config.get('max_tokens', 4000),
                openai_api_key=provider_config.get('api_key')
            )
        else:
            # Default to OpenRouter
            return ChatOpenRouter(
                model=model,
                temperature=provider_config.get('temperature', 0.7),
                max_tokens=provider_config.get('max_tokens', 4000),
                openrouter_api_key=provider_config.get('api_key', '')
            )
    
    async def execute_task(self, task: str, agents: Optional[List[str]] = None) -> Dict[str, Any]:
        """Execute a task with specified LangChain agents"""
        logger.info(f"Executing task with LangChain: {task}")
        
        if not agents:
            agents = ['general_agent']
        
        results = {}
        
        for agent_name in agents:
            if agent_name not in self.agents:
                self.agents[agent_name] = self._create_agent(agent_name)
            
            agent = self.agents[agent_name]
            try:
                result = await agent.execute(task)
                results[agent_name] = result
                logger.info(f"Agent {agent_name} completed task")
            except Exception as e:
                logger.error(f"Agent {agent_name} failed: {e}")
                results[agent_name] = {'error': str(e)}
        
        return {
            'framework': 'langchain',
            'task': task,
            'agents': agents,
            'results': results,
            'timestamp': asyncio.get_event_loop().time()
        }
    
    def _create_agent(self, agent_name: str) -> LangChainAgent:
        """Create a LangChain agent"""
        # Get agent configuration
        agent_config = self.framework_config.get('agents', {}).get(agent_name, {})
        
        # Get tools for this agent
        tools = self.tool_registry.get_tools_for_agent(agent_name)
        
        # Get LLM
        llm_provider = agent_config.get('provider', 'default')
        llm_model = agent_config.get('model')
        llm = self._get_llm(llm_provider, llm_model)
        
        # Create agent
        return LangChainAgent(
            name=agent_name,
            llm=llm,
            tools=tools,
            config=agent_config
        )
    
    def configure(self) -> None:
        """Configure LangChain framework"""
        logger.info("Configuring LangChain framework")
        
        # Validate API keys
        required_keys = ['OPENROUTER_API_KEY', 'ANTHROPIC_API_KEY']
        for key in required_keys:
            if not self.config.get('env', {}).get(key):
                logger.warning(f"Missing environment variable: {key}")
        
        # Register tools
        self.tool_registry.register_default_tools()
        
        # Create default agents
        default_agents = self.framework_config.get('default_agents', ['general_agent'])
        for agent_name in default_agents:
            if agent_name not in self.agents:
                self.agents[agent_name] = self._create_agent(agent_name)
        
        logger.info("LangChain configuration completed")
    
    def get_status(self) -> Dict[str, Any]:
        """Get LangChain status"""
        status = super().get_status()
        
        # Check API keys
        missing_keys = []
        required_keys = ['OPENROUTER_API_KEY', 'ANTHROPIC_API_KEY']
        
        for key in required_keys:
            if not self.config.get('env', {}).get(key):
                missing_keys.append(key)
        
        status.update({
            'api_keys_ok': len(missing_keys) == 0,
            'missing_api_keys': missing_keys,
            'agents_count': len(self.agents),
            'tools_count': len(self.tool_registry.get_all_tools())
        })
        
        return status
    
    def validate_config(self) -> bool:
        """Validate LangChain configuration"""
        required_keys = ['frameworks', 'frameworks.langchain']
        
        for key in required_keys:
            if not self._check_nested_key(self.config, key):
                logger.error(f"Missing required config key: {key}")
                return False
        
        # Validate providers
        providers = self.framework_config.get('providers', {})
        for provider_name, provider_config in providers.items():
            if 'api_key' not in provider_config:
                logger.warning(f"Missing api_key for provider: {provider_name}")
        
        return True
    
    def _check_nested_key(self, config: Dict[str, Any], key_path: str) -> bool:
        """Check if a nested key exists in config"""
        keys = key_path.split('.')
        current = config
        
        for key in keys:
            if key not in current:
                return False
            current = current[key]
        
        return True