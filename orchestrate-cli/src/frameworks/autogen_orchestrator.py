"""
AutoGen Orchestrator - Multi-agent collaboration with AutoGen

Features:
- Multi-agent conversations and collaboration
- Human-in-the-loop support
- Tool usage across agents
- Code execution capability
- Advanced agent workflows
"""

import asyncio
from typing import Dict, List, Any, Optional
from loguru import logger

try:
    from autogen import AssistantAgent, UserProxyAgent, ConversableAgent
    from autogen_core.models import FunctionCallingLLM  # noqa: F401
    from autogen_agentchat.agents import AssistantAgent as ChatAssistantAgent  # noqa: F401
    from autogen_agentchat.agents import UserProxyAgent as ChatUserProxyAgent  # noqa: F401
    from autogen_agentchat.teams import RoundRobinGroupChat
    AUTOGEN_AVAILABLE = True
except ImportError:
    AUTOGEN_AVAILABLE = False

from src.orchestrators.orchestrator_factory import BaseOrchestrator

class AutoGenOrchestrator(BaseOrchestrator):
    """AutoGen orchestrator for multi-agent collaboration"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.framework_name = 'autogen'
        
        if not AUTOGEN_AVAILABLE:
            raise ImportError("AutoGen not available. Install with: pip install pyautogen")
        
        self.agents: Dict[str, ConversableAgent] = {}
        self.teams: Dict[str, RoundRobinGroupChat] = {}
        self.agent_configs = self._load_agent_configs()
        
    def _load_agent_configs(self) -> Dict[str, Dict[str, Any]]:
        """Load agent configurations"""
        return self.framework_config.get('agents', {})
    
    async def execute_task(self, task: str, agents: Optional[List[str]] = None) -> Dict[str, Any]:
        """Execute a task with AutoGen agents"""
        logger.info(f"Executing task with AutoGen: {task}")
        
        if not agents:
            agents = ['assistant', 'user_proxy']
        
        results = {}
        
        # Create team if not exists
        team_name = f"team_{hash(task) % 1000}"  # Unique team name
        if team_name not in self.teams:
            self.teams[team_name] = self._create_team(agents)
        
        team = self.teams[team_name]
        
        try:
            # Execute task with streaming
            messages = []
            async for message in team.run_stream(task):
                messages.append(message)
                logger.info(f"Team message: {message}")
            
            results[team_name] = {
                'messages': messages,
                'task': task,
                'agents': agents
            }
            
        except Exception as e:
            logger.error(f"AutoGen team execution failed: {e}")
            results[team_name] = {'error': str(e)}
        
        return {
            'framework': 'autogen',
            'task': task,
            'agents': agents,
            'results': results,
            'timestamp': asyncio.get_event_loop().time()
        }
    
    def _create_team(self, agent_names: List[str]) -> RoundRobinGroupChat:
        """Create an AutoGen team"""
        agents = []
        
        for agent_name in agent_names:
            if agent_name not in self.agents:
                self.agents[agent_name] = self._create_agent(agent_name)
            
            agents.append(self.agents[agent_name])
        
        # Create round-robin team
        team = RoundRobinGroupChat(agents)
        return team
    
    def _create_agent(self, agent_name: str) -> ConversableAgent:
        """Create an AutoGen agent"""
        agent_config = self.agent_configs.get(agent_name, {})
        
        # Default configuration
        config = {
            'name': agent_name,
            'model': agent_config.get('model', 'deepseek/deepseek-v4-pro'),
            'temperature': agent_config.get('temperature', 0.7),
            'max_tokens': agent_config.get('max_tokens', 4000),
            'tools': agent_config.get('tools', []),
            'system_message': agent_config.get('system_message', f"You are {agent_name}, a helpful AI assistant.")
        }
        
        # Create appropriate agent type
        if agent_name == 'user_proxy':
            return UserProxyAgent(
                name=config['name'],
                human_input_mode="NEVER",
                max_consecutive_auto_reply=10,
                code_execution_config={"work_dir": "./autogen_workspace"},
                **config
            )
        else:
            return AssistantAgent(
                name=config['name'],
                llm_config={
                    "config_list": [{
                        "model": config['model'],
                        "temperature": config['temperature'],
                        "max_tokens": config['max_tokens']
                    }],
                    "tools": config['tools']
                },
                system_message=config['system_message']
            )
    
    def configure(self) -> None:
        """Configure AutoGen framework"""
        logger.info("Configuring AutoGen framework")
        
        # Validate configuration
        if not self.validate_config():
            raise ValueError("Invalid AutoGen configuration")
        
        # Create default agents
        default_agents = self.framework_config.get('default_agents', ['assistant', 'user_proxy'])
        for agent_name in default_agents:
            if agent_name not in self.agents:
                self.agents[agent_name] = self._create_agent(agent_name)
        
        # Create default team
        default_team = self.framework_config.get('default_team', 'main_team')
        if default_team not in self.teams:
            team_agents = self.framework_config.get('teams', {}).get(default_team, {}).get('agents', default_agents)
            self.teams[default_team] = self._create_team(team_agents)
        
        logger.info("AutoGen configuration completed")
    
    def get_status(self) -> Dict[str, Any]:
        """Get AutoGen status"""
        status = super().get_status()
        
        # Check agent configurations
        missing_configs = []
        for agent_name in self.agents:
            if agent_name not in self.agent_configs:
                missing_configs.append(agent_name)
        
        status.update({
            'agents_count': len(self.agents),
            'teams_count': len(self.teams),
            'missing_configs': missing_configs,
            'workspace_ready': self._check_workspace()
        })
        
        return status
    
    def validate_config(self) -> bool:
        """Validate AutoGen configuration"""
        required_keys = ['frameworks', 'frameworks.autogen']
        
        for key in required_keys:
            if not self._check_nested_key(self.config, key):
                logger.error(f"Missing required config key: {key}")
                return False
        
        # Validate model configurations
        models = self.framework_config.get('models', {})
        for model_name, model_config in models.items():
            if 'model' not in model_config:
                logger.error(f"Missing model name for: {model_name}")
                return False
        
        return True
    
    def _check_workspace(self) -> bool:
        """Check if autogen workspace is ready"""
        import os
        workspace_path = "./autogen_workspace"
        return os.path.exists(workspace_path) and os.path.isdir(workspace_path)
    
    def _check_nested_key(self, config: Dict[str, Any], key_path: str) -> bool:
        """Check if a nested key exists in config"""
        keys = key_path.split('.')
        current = config
        
        for key in keys:
            if key not in current:
                return False
            current = current[key]
        
        return True