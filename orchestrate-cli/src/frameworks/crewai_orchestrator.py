"""
CrewAI Orchestrator - Agent team orchestration with CrewAI

Features:
- Role-based agent teams
- Sequential and parallel workflows
- Task delegation and coordination
- Performance tracking
- Multi-agent collaboration patterns
"""

import asyncio
from typing import Dict, List, Any, Optional
from loguru import logger

try:
    from crewai import Agent, Task, Crew, Process
    from crewai.tools import BaseTool  # noqa: F401
    from crewai.tools import tool
    from crewai.memory import SharedMemories  # noqa: F401
    CREWAI_AVAILABLE = True
except ImportError:
    CREWAI_AVAILABLE = False

from src.orchestrators.orchestrator_factory import BaseOrchestrator

class CrewAIOrchestrator(BaseOrchestrator):
    """CrewAI orchestrator for agent team coordination"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.framework_name = 'crewai'
        
        if not CREWAI_AVAILABLE:
            raise ImportError("CrewAI not available. Install with: pip install crewai")
        
        self.agents: Dict[str, Agent] = {}
        self.tasks: Dict[str, Task] = {}
        self.crews: Dict[str, Crew] = {}
        self.team_configs = self._load_team_configs()
        
    def _load_team_configs(self) -> Dict[str, Dict[str, Any]]:
        """Load team configurations"""
        return self.framework_config.get('teams', {})
    
    async def execute_task(self, task: str, agents: Optional[List[str]] = None) -> Dict[str, Any]:
        """Execute a task with CrewAI agent teams"""
        logger.info(f"Executing task with CrewAI: {task}")
        
        if not agents:
            agents = ['research_agent', 'code_agent', 'review_agent']
        
        results = {}
        
        # Create crew if not exists
        crew_name = f"crew_{hash(task) % 1000}"  # Unique crew name
        if crew_name not in self.crews:
            self.crews[crew_name] = self._create_crew(agents)
        
        crew = self.crews[crew_name]
        
        try:
            # Create task
            task_obj = Task(
                description=task,
                agent=self.agents.get(agents[0], self._create_agent(agents[0])),
                expected_output="Comprehensive and well-structured response"
            )
            
            # Execute task
            result = crew.kickoff(tasks=[task_obj])
            
            results[crew_name] = {
                'result': result,
                'task': task,
                'agents': agents,
                'crew_name': crew_name
            }
            
            logger.info(f"Crew {crew_name} completed task")
            
        except Exception as e:
            logger.error(f"CrewAI execution failed: {e}")
            results[crew_name] = {'error': str(e)}
        
        return {
            'framework': 'crewai',
            'task': task,
            'agents': agents,
            'results': results,
            'timestamp': asyncio.get_event_loop().time()
        }
    
    def _create_crew(self, agent_names: List[str]) -> Crew:
        """Create a CrewAI team"""
        crew_agents = []
        
        for agent_name in agent_names:
            if agent_name not in self.agents:
                self.agents[agent_name] = self._create_agent(agent_name)
            
            crew_agents.append(self.agents[agent_name])
        
        # Create crew configuration
        crew_config = self.team_configs.get('default', {})
        
        crew = Crew(
            agents=crew_agents,
            tasks=[],  # Tasks added dynamically
            process=Process.sequential,  # Can be parallel or hierarchical
            verbose=True,
            memory=True,
            planning=crew_config.get('planning', True),
            function_calling=True,
            max_rpm=crew_config.get('max_rpm', 100),
            share_crew=crew_config.get('share_crew', False)
        )
        
        return crew
    
    def _create_agent(self, agent_name: str) -> Agent:
        """Create a CrewAI agent"""
        agent_config = self.framework_config.get('agents', {}).get(agent_name, {})
        
        # Default configuration
        config = {
            'name': agent_name,
            'role': agent_config.get('role', f'{agent_name.title()} Specialist'),
            'goal': agent_config.get('goal', f'Complete tasks as {agent_name}'),
            'backstory': agent_config.get('backstory', f'I am {agent_name}, an AI expert specializing in my domain.'),
            'verbose': agent_config.get('verbose', True),
            'allow_delegation': agent_config.get('allow_delegation', True),
            'max_iter': agent_config.get('max_iter', 15),
            'memory': True,
            'tools': agent_config.get('tools', [])
        }
        
        return Agent(
            name=config['name'],
            role=config['role'],
            goal=config['goal'],
            backstory=config['backstory'],
            verbose=config['verbose'],
            allow_delegation=config['allow_delegation'],
            max_iter=config['max_iter'],
            memory=config['memory'],
            tools=config['tools']
        )
    
    def configure(self) -> None:
        """Configure CrewAI framework"""
        logger.info("Configuring CrewAI framework")
        
        # Validate configuration
        if not self.validate_config():
            raise ValueError("Invalid CrewAI configuration")
        
        # Create default agents
        default_agents = self.framework_config.get('default_agents', [
            'research_agent',
            'code_agent', 
            'review_agent',
            'planning_agent'
        ])
        
        for agent_name in default_agents:
            if agent_name not in self.agents:
                self.agents[agent_name] = self._create_agent(agent_name)
        
        # Create default crew
        default_crew = self.framework_config.get('default_crew', 'main_crew')
        if default_crew not in self.crews:
            crew_agents = self.team_configs.get(default_crew, {}).get('agents', default_agents)
            self.crews[default_crew] = self._create_crew(crew_agents)
        
        # Register custom tools
        self._register_custom_tools()
        
        logger.info("CrewAI configuration completed")
    
    def _register_custom_tools(self):
        """Register custom tools for CrewAI agents"""
        custom_tools = self.framework_config.get('tools', {})
        
        for tool_name, tool_config in custom_tools.items():
            try:
                # Create tool class dynamically
                tool_class = self._create_tool_class(tool_name, tool_config)
                globals()[tool_name] = tool_class
                logger.info(f"Registered tool: {tool_name}")
            except Exception as e:
                logger.error(f"Failed to register tool {tool_name}: {e}")
    
    def _create_tool_class(self, tool_name: str, tool_config: Dict[str, Any]):
        """Create a CrewAI tool class dynamically"""
        
        @tool(tool_name)
        class DynamicTool:
            def __init__(self, config):
                self.name = config['name']
                self.description = config['description']
                self.config = config
            
            def _run(self, query: str) -> str:
                # Implement tool logic here
                return f"Tool {self.name} executed with query: {query}"
            
            def _arun(self, query: str) -> str:
                # Async implementation
                return self._run(query)
        
        return DynamicTool
    
    def get_status(self) -> Dict[str, Any]:
        """Get CrewAI status"""
        status = super().get_status()
        
        # Check agent configurations
        missing_configs = []
        for agent_name in self.agents:
            if agent_name not in self.framework_config.get('agents', {}):
                missing_configs.append(agent_name)
        
        status.update({
            'agents_count': len(self.agents),
            'tasks_count': len(self.tasks),
            'crews_count': len(self.crews),
            'missing_configs': missing_configs,
            'tools_count': len(self.framework_config.get('tools', {}))
        })
        
        return status
    
    def validate_config(self) -> bool:
        """Validate CrewAI configuration"""
        required_keys = ['frameworks', 'frameworks.crewai']
        
        for key in required_keys:
            if not self._check_nested_key(self.config, key):
                logger.error(f"Missing required config key: {key}")
                return False
        
        # Validate agent configurations
        agents = self.framework_config.get('agents', {})
        for agent_name, agent_config in agents.items():
            if 'role' not in agent_config or 'goal' not in agent_config:
                logger.error(f"Missing role or goal for agent: {agent_name}")
                return False
        
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