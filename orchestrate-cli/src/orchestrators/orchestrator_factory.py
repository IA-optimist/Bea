"""
Orchestrator Factory - Creates framework-specific orchestrators

Supports:
- LangChain: Multi-LLM orchestration
- AutoGen: Multi-agent collaboration
- CrewAI: Agent team orchestration
- LlamaIndex: RAG and document processing
- Haystack: Search and retrieval
- Gemini CLI: Google AI model interaction
- Codex CLI: OpenAI code generation
- Claude Code: Anthropic coding assistant
- GitHub Copilot CLI: AI-powered coding assistance
- Aider CLI: Pair programming assistant
- OpenCode CLI: Collaborative coding
- OpenHands CLI: Development tools
- Cursor CLI: AI code review
"""

import asyncio
from typing import Dict, List, Any, Optional
from loguru import logger

# Import all orchestrators
from src.frameworks.langchain_orchestrator import LangChainOrchestrator
from src.frameworks.autogen_orchestrator import AutoGenOrchestrator
from src.frameworks.crewai_orchestrator import CrewAIOrchestrator
from src.frameworks.llamaindex_orchestrator import LlamaIndexOrchestrator
from src.frameworks.haystack_orchestrator import HaystackOrchestrator

# Import all CLI agents
from src.agents.gemini_cli import GeminiCLI
from src.agents.codex_cli import CodexCLI
from src.agents.claude_code import ClaudeCode
from src.agents.github_copilot_cli import GitHubCopilotCLI
from src.agents.aider_cli import AiderCLI
from src.agents.opencode_cli import OpenCodeCLI
from src.agents.openhands_cli import OpenHandsCLI
from src.agents.cursor_cli import CursorCLI

class OrchestratorFactory:
    """Factory for creating framework-specific orchestrators"""
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.orchestrators = {}
        self.cli_agents = {}
        self._initialize_orchestrators()
        self._initialize_cli_agents()
    
    def _initialize_orchestrators(self):
        """Initialize all framework orchestrators"""
        self.orchestrators = {
            'langchain': LangChainOrchestrator(self.config),
            'autogen': AutoGenOrchestrator(self.config),
            'crewai': CrewAIOrchestrator(self.config),
            'llamaindex': LlamaIndexOrchestrator(self.config),
            'haystack': HaystackOrchestrator(self.config)
        }
        
        logger.info(f"Initialized {len(self.orchestrators)} orchestrators")
    
    def _initialize_cli_agents(self):
        """Initialize all CLI agents"""
        self.cli_agents = {
            'gemini': GeminiCLI(self.config.get('agents', {}).get('gemini', {})),
            'codex': CodexCLI(self.config.get('agents', {}).get('codex', {})),
            'claude': ClaudeCode(self.config.get('agents', {}).get('claude', {})),
            'github_copilot': GitHubCopilotCLI(self.config.get('agents', {}).get('github_copilot', {})),
            'aider': AiderCLI(self.config.get('agents', {}).get('aider', {})),
            'opencode': OpenCodeCLI(self.config.get('agents', {}).get('opencode', {})),
            'openhands': OpenHandsCLI(self.config.get('agents', {}).get('openhands', {})),
            'cursor': CursorCLI(self.config.get('agents', {}).get('cursor', {}))
        }
        
        logger.info(f"Initialized {len(self.cli_agents)} CLI agents")
    
    def create(self, framework: str, config: Dict[str, Any] = None) -> Optional[Any]:
        """Create an orchestrator for the specified framework"""
        framework_config = config or {}
        
        if framework not in self.orchestrators:
            logger.error(f"Framework '{framework}' not supported")
            return None
        
        try:
            orchestrator = self.orchestrators[framework]
            orchestrator.load_config(framework_config)
            logger.info(f"Created orchestrator for framework: {framework}")
            return orchestrator
        except Exception as e:
            logger.error(f"Failed to create orchestrator for {framework}: {e}")
            return None
    
    def get_cli_agent(self, agent_name: str) -> Optional[Any]:
        """Get a CLI agent by name"""
        if agent_name not in self.cli_agents:
            logger.error(f"CLI agent '{agent_name}' not found")
            return None
        
        return self.cli_agents[agent_name]
    
    def list_available_frameworks(self) -> List[str]:
        """List all available frameworks"""
        return list(self.orchestrators.keys())
    
    def list_available_cli_agents(self) -> List[str]:
        """List all available CLI agents"""
        return list(self.cli_agents.keys())
    
    def get_available_agents(self, framework: str, config: Dict[str, Any] = None) -> Dict[str, Any]:
        """Get all available agents for a framework"""
        
        if framework == 'langchain':
            return {
                'general_agent': {
                    'type': 'langchain',
                    'enabled': True,
                    'description': 'General purpose LangChain agent'
                },
                'research_agent': {
                    'type': 'langchain',
                    'enabled': True,
                    'description': 'Research and analysis agent'
                },
                'coding_agent': {
                    'type': 'langchain',
                    'enabled': True,
                    'description': 'Code generation and analysis agent'
                }
            }
        
        elif framework == 'autogen':
            return {
                'assistant': {
                    'type': 'autogen',
                    'enabled': True,
                    'description': 'AI assistant agent'
                },
                'user_proxy': {
                    'type': 'autogen',
                    'enabled': True,
                    'description': 'User proxy agent'
                }
            }
        
        elif framework == 'crewai':
            return {
                'research_agent': {
                    'type': 'crewai',
                    'enabled': True,
                    'description': 'Research specialist agent'
                },
                'code_agent': {
                    'type': 'crewai',
                    'enabled': True,
                    'description': 'Code specialist agent'
                },
                'planning_agent': {
                    'type': 'crewai',
                    'enabled': True,
                    'description': 'Planning and coordination agent'
                }
            }
        
        elif framework == 'llamaindex':
            return {
                'document_analyzer': {
                    'type': 'llamaindex',
                    'enabled': True,
                    'description': 'Document analysis agent'
                },
                'query_engine': {
                    'type': 'llamaindex',
                    'enabled': True,
                    'description': 'Query processing agent'
                }
            }
        
        elif framework == 'haystack':
            return {
                'search_agent': {
                    'type': 'haystack',
                    'enabled': True,
                    'description': 'Search and retrieval agent'
                },
                'document_processor': {
                    'type': 'haystack',
                    'enabled': True,
                    'description': 'Document processing agent'
                }
            }
        
        else:
            return {}
    
    async def run_cli_command(self, agent_name: str, command: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Run a command using a specific CLI agent"""
        agent = self.get_cli_agent(agent_name)
        
        if not agent:
            return {'error': f'CLI agent {agent_name} not available'}
        
        if not hasattr(agent, command):
            return {'error': f'Command {command} not available for agent {agent_name}'}
        
        try:
            method = getattr(agent, command)
            if asyncio.iscoroutinefunction(method):
                if params:
                    result = await method(**params)
                else:
                    result = await method()
            else:
                if params:
                    result = method(**params)
                else:
                    result = method()
            
            return {
                'agent': agent_name,
                'command': command,
                'result': result,
                'timestamp': asyncio.get_event_loop().time()
            }
            
        except Exception as e:
            logger.error(f"CLI command failed: {agent_name}.{command} - {e}")
            return {'error': str(e)}
    
    async def run_multi_agent_task(self, framework: str, task: str, agents: List[str], config: Dict[str, Any] = None) -> Dict[str, Any]:
        """Run a task using multiple agents from the same framework"""
        orchestrator = self.create(framework, config)
        
        if not orchestrator:
            return {'error': f'Framework {framework} not available'}
        
        try:
            result = await orchestrator.execute(task, agents)
            return result
        except Exception as e:
            logger.error(f"Multi-agent task failed: {e}")
            return {'error': str(e)}
    
    async def run_cross_framework_task(self, task: str, framework_mapping: Dict[str, str], config: Dict[str, Any] = None) -> Dict[str, Any]:
        """Run a task using multiple frameworks"""
        results = {}
        
        for agent_name, framework in framework_mapping.items():
            if framework in self.orchestrators:
                try:
                    orchestrator = self.create(framework, config)
                    if orchestrator:
                        result = await orchestrator.execute(task, [agent_name])
                        results[agent_name] = result
                except Exception as e:
                    logger.error(f"Cross-framework task failed for {agent_name}: {e}")
                    results[agent_name] = {'error': str(e)}
        
        return {
            'task': task,
            'results': results,
            'timestamp': asyncio.get_event_loop().time()
        }
    
    async def test_all_agents(self, framework: str = None) -> Dict[str, Any]:
        """Test all agents or agents from a specific framework"""
        test_results = {}
        
        if framework:
            agents = self.get_available_agents(framework, self.config)
            for agent_name, agent_info in agents.items():
                if agent_info.get('enabled', True):
                    test_results[agent_name] = await self._test_agent(agent_name, framework)
        else:
            # Test all CLI agents
            for agent_name in self.cli_agents.keys():
                test_results[agent_name] = await self._test_cli_agent(agent_name)
            
            # Test framework agents
            for framework_name in self.orchestrators.keys():
                agents = self.get_available_agents(framework_name, self.config)
                for agent_name, agent_info in agents.items():
                    if agent_info.get('enabled', True):
                        test_results[f"{framework_name}_{agent_name}"] = await self._test_agent(agent_name, framework_name)
        
        return test_results
    
    async def _test_agent(self, agent_name: str, framework: str) -> Dict[str, Any]:
        """Test a specific agent"""
        try:
            orchestrator = self.create(framework, self.config)
            if orchestrator:
                result = await orchestrator.test_agents([agent_name])
                return {
                    'agent': agent_name,
                    'framework': framework,
                    'success': True,
                    'result': result,
                    'timestamp': asyncio.get_event_loop().time()
                }
            else:
                return {
                    'agent': agent_name,
                    'framework': framework,
                    'success': False,
                    'error': 'Orchestrator not available',
                    'timestamp': asyncio.get_event_loop().time()
                }
        except Exception as e:
            return {
                'agent': agent_name,
                'framework': framework,
                'success': False,
                'error': str(e),
                'timestamp': asyncio.get_event_loop().time()
            }
    
    async def _test_cli_agent(self, agent_name: str) -> Dict[str, Any]:
        """Test a specific CLI agent"""
        agent = self.get_cli_agent(agent_name)
        
        if not agent:
            return {
                'agent': agent_name,
                'success': False,
                'error': 'Agent not available',
                'timestamp': asyncio.get_event_loop().time()
            }
        
        try:
            # Check availability
            if hasattr(agent, 'check_availability'):
                available = agent.check_availability()
                if not available:
                    return {
                        'agent': agent_name,
                        'success': False,
                        'error': 'Agent not available',
                        'timestamp': asyncio.get_event_loop().time()
                    }
            
            # Test version if available
            if hasattr(agent, 'get_version'):
                version_result = agent.get_version()
                return {
                    'agent': agent_name,
                    'success': True,
                    'version': version_result,
                    'timestamp': asyncio.get_event_loop().time()
                }
            else:
                return {
                    'agent': agent_name,
                    'success': True,
                    'timestamp': asyncio.get_event_loop().time()
                }
                
        except Exception as e:
            return {
                'agent': agent_name,
                'success': False,
                'error': str(e),
                'timestamp': asyncio.get_event_loop().time()
            }
    
    def get_framework_status(self) -> Dict[str, Any]:
        """Get status of all frameworks"""
        status = {}
        
        for framework_name, orchestrator in self.orchestrators.items():
            try:
                status[framework_name] = {
                    'enabled': True,
                    'loaded': True,
                    'agents': len(self.get_available_agents(framework_name, self.config))
                }
            except Exception as e:
                status[framework_name] = {
                    'enabled': False,
                    'loaded': False,
                    'error': str(e)
                }
        
        return status
    
    def get_cli_agents_status(self) -> Dict[str, Any]:
        """Get status of all CLI agents"""
        status = {}
        
        for agent_name, agent in self.cli_agents.items():
            try:
                available = agent.check_availability() if hasattr(agent, 'check_availability') else False
                status[agent_name] = {
                    'available': available,
                    'loaded': True
                }
                
                if available and hasattr(agent, 'get_version'):
                    version = agent.get_version()
                    status[agent_name]['version'] = version
                
            except Exception as e:
                status[agent_name] = {
                    'available': False,
                    'loaded': False,
                    'error': str(e)
                }
        
        return status