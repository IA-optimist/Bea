"""
AutoGen Agent - Individual agent implementation for AutoGen framework

Features:
- Individual agent with specialized capabilities
- Tool usage and code execution
- Human-in-the-loop support
- Async execution
- Conversation management
"""

import asyncio
from typing import Dict, List, Any
from loguru import logger

try:
    from autogen import AssistantAgent, UserProxyAgent, ConversableAgent
    from autogen_core.models import FunctionCallingLLM  # noqa: F401
    from autogen_agentchat.agents import AssistantAgent as ChatAssistantAgent  # noqa: F401
    from autogen_agentchat.agents import UserProxyAgent as ChatUserProxyAgent  # noqa: F401
    AUTOGEN_AVAILABLE = True
except ImportError:
    AUTOGEN_AVAILABLE = False

class AutoGenAgent:
    """Individual AutoGen agent implementation"""

    def __init__(self, name: str, config: Dict[str, Any] = None):
        if not AUTOGEN_AVAILABLE:
            raise ImportError("AutoGen not available")

        self.name = name
        self.config = config or {}
        self.agent = self._create_agent()
        self.conversation_history = []

    def _create_agent(self) -> ConversableAgent:
        """Create the AutoGen agent"""
        agent_config = self.config

        # Base configuration
        config = {
            'name': self.name,
            'model': agent_config.get('model', 'deepseek/deepseek-v4-pro'),
            'temperature': agent_config.get('temperature', 0.7),
            'max_tokens': agent_config.get('max_tokens', 4000),
            'system_message': agent_config.get('system_message', f"You are {self.name}, a helpful AI assistant."),
            'human_input_mode': agent_config.get('human_input_mode', 'NEVER'),
            'max_consecutive_auto_reply': agent_config.get('max_consecutive_auto_reply', 10),
            'code_execution_config': agent_config.get('code_execution_config', {
                'work_dir': './autogen_workspace',
                'use_docker': False
            })
        }

        # Determine agent type
        if agent_config.get('agent_type') == 'user_proxy' or 'user' in self.name.lower():
            return UserProxyAgent(
                name=config['name'],
                human_input_mode=config['human_input_mode'],
                max_consecutive_auto_reply=config['max_consecutive_auto_reply'],
                code_execution_config=config['code_execution_config'],
                **{k: v for k, v in config.items() if k not in ['human_input_mode', 'max_consecutive_auto_reply', 'code_execution_config']}
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
                    "tools": agent_config.get('tools', [])
                },
                system_message=config['system_message']
            )

    async def execute(self, task: str) -> Dict[str, Any]:
        """Execute a task"""
        logger.info(f"AutoGen agent {self.name} executing task: {task}")

        try:
            # Create user proxy for this task
            user_proxy = UserProxyAgent(
                name=f"user_proxy_{self.name}",
                human_input_mode="NEVER",
                max_consecutive_auto_reply=5,
                code_execution_config={"work_dir": "./autogen_workspace"}
            )

            # Start conversation
            self.conversation_history.append({
                'role': 'user',
                'content': task,
                'timestamp': asyncio.get_event_loop().time()
            })

            # Execute task
            response = await user_proxy.a_initiate_chat(
                self.agent,
                message=task,
                max_turns=3,
                summary_method="last_msg"
            )

            # Store response
            self.conversation_history.append({
                'role': 'assistant',
                'content': str(response),
                'timestamp': asyncio.get_event_loop().time()
            })

            return {
                "agent": self.name,
                "task": task,
                "result": str(response),
                "conversation_history": self.conversation_history,
                "timestamp": asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"AutoGen agent {self.name} execution failed: {e}")
            return {
                "agent": self.name,
                "task": task,
                "error": str(e),
                "conversation_history": self.conversation_history,
                "timestamp": asyncio.get_event_loop().time()
            }

    def get_conversation_history(self) -> List[Dict[str, Any]]:
        """Get conversation history"""
        return self.conversation_history

    def clear_conversation_history(self):
        """Clear conversation history"""
        self.conversation_history = []

    def add_tool(self, tool: Dict[str, Any]):
        """Add a tool to the agent"""
        if 'tools' not in self.config:
            self.config['tools'] = []
        self.config['tools'].append(tool)
        self.agent = self._create_agent()

    def configure_code_execution(self, config: Dict[str, Any]):
        """Configure code execution"""
        self.config['code_execution_config'] = config
        self.agent = self._create_agent()