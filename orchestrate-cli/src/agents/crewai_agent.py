"""
CrewAI Agent - Individual agent implementation for CrewAI framework

Features:
- Role-based individual agents
- Task execution with delegation support
- Memory and tools integration
- Performance tracking
- Specialized capabilities
"""

import asyncio
from typing import Dict, List, Any
from loguru import logger

try:
    from crewai import Agent, Task, Crew, Process
    from crewai.tools import BaseTool, tool  # noqa: F401
    from crewai.memory import SharedMemories  # noqa: F401
    CREWAI_AVAILABLE = True
except ImportError:
    CREWAI_AVAILABLE = False

class CrewAIAgent:
    """Individual CrewAI agent implementation"""

    def __init__(self, name: str, config: Dict[str, Any] = None):
        if not CREWAI_AVAILABLE:
            raise ImportError("CrewAI not available")

        self.name = name
        self.config = config or {}
        self.agent = self._create_agent()
        self.completed_tasks = []
        self.performance_metrics = {
            'tasks_completed': 0,
            'avg_completion_time': 0,
            'success_rate': 1.0
        }

    def _create_agent(self) -> Agent:
        """Create the CrewAI agent"""
        agent_config = self.config

        # Default configuration
        config = {
            'name': self.name,
            'role': agent_config.get('role', f'{self.name.title()} Specialist'),
            'goal': agent_config.get('goal', f'Complete tasks as {self.name}'),
            'backstory': agent_config.get('backstory', f'I am {self.name}, an AI expert specializing in my domain.'),
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

    async def execute(self, task: str) -> Dict[str, Any]:
        """Execute a task"""
        logger.info(f"CrewAI agent {self.name} executing task: {task}")

        try:
            start_time = asyncio.get_event_loop().time()

            # Create task
            task_obj = Task(
                description=task,
                agent=self.agent,
                expected_output="Comprehensive and well-structured response"
            )

            # Create temporary crew for this task
            crew = Crew(
                agents=[self.agent],
                tasks=[task_obj],
                process=Process.sequential,
                verbose=True,
                memory=True,
                planning=False,
                function_calling=True,
                max_rpm=100,
                share_crew=False
            )

            # Execute task
            result = crew.kickoff()

            end_time = asyncio.get_event_loop().time()
            completion_time = end_time - start_time

            # Update performance metrics
            self._update_performance_metrics(completion_time, True)

            # Store completed task
            self.completed_tasks.append({
                'task': task,
                'result': str(result),
                'completion_time': completion_time,
                'timestamp': end_time,
                'status': 'completed'
            })

            return {
                "agent": self.name,
                "task": task,
                "result": str(result),
                "completion_time": completion_time,
                "performance_metrics": self.performance_metrics,
                "timestamp": end_time
            }

        except Exception as e:
            end_time = asyncio.get_event_loop().time()
            completion_time = end_time - start_time

            # Update performance metrics
            self._update_performance_metrics(completion_time, False)

            logger.error(f"CrewAI agent {self.name} execution failed: {e}")

            return {
                "agent": self.name,
                "task": task,
                "error": str(e),
                "completion_time": completion_time,
                "performance_metrics": self.performance_metrics,
                "timestamp": end_time
            }

    def _update_performance_metrics(self, completion_time: float, success: bool):
        """Update performance metrics"""
        self.performance_metrics['tasks_completed'] += 1

        # Update average completion time
        current_avg = self.performance_metrics['avg_completion_time']
        total_tasks = self.performance_metrics['tasks_completed']
        self.performance_metrics['avg_completion_time'] = (
            (current_avg * (total_tasks - 1) + completion_time) / total_tasks
        )

        # Update success rate
        if success:
            self.performance_metrics['success_rate'] = (
                (self.performance_metrics['success_rate'] * (total_tasks - 1) + 1) / total_tasks
            )
        else:
            self.performance_metrics['success_rate'] = (
                (self.performance_metrics['success_rate'] * (total_tasks - 1)) / total_tasks
            )

    def get_performance_metrics(self) -> Dict[str, Any]:
        """Get performance metrics"""
        return self.performance_metrics

    def get_completed_tasks(self) -> List[Dict[str, Any]]:
        """Get completed tasks"""
        return self.completed_tasks

    def add_tool(self, tool: Any):
        """Add a tool to the agent"""
        if 'tools' not in self.config:
            self.config['tools'] = []
        self.config['tools'].append(tool)
        self.agent = self._create_agent()

    def set_role(self, role: str, goal: str, backstory: str):
        """Set agent role and configuration"""
        self.config.update({
            'role': role,
            'goal': goal,
            'backstory': backstory
        })
        self.agent = self._create_agent()

    def enable_delegation(self, enabled: bool):
        """Enable or disable delegation"""
        self.config['allow_delegation'] = enabled
        self.agent = self._create_agent()

    def set_max_iterations(self, max_iter: int):
        """Set maximum iterations"""
        self.config['max_iter'] = max_iter
        self.agent = self._create_agent()
