"""
LangChain Agent - Individual agent implementation for LangChain framework

Features:
- Individual agent execution
- Tool integration
- Memory management
- Streaming responses
- Error handling
"""

import asyncio
from typing import Dict, List, Any
from loguru import logger

try:
    from langchain.agents import create_agent, Tool
    from langchain_community.chat_models import ChatOpenRouter, ChatAnthropic, ChatOpenAI  # noqa: F401
    from langchain_openai import ChatOpenAI as LangChainOpenAI  # noqa: F401
    from langchain.memory import ConversationBufferMemory, ConversationSummaryMemory
    from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder  # noqa: F401
    from langchain_core.messages import SystemMessage, HumanMessage, AIMessage  # noqa: F401
    from langchain_core.runnables import RunnablePassthrough  # noqa: F401
    from langchain_core.output_parsers import StrOutputParser  # noqa: F401
    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False


class LangChainAgent:
    """Individual LangChain agent implementation"""
    
    def __init__(self, name: str, llm, tools: List[Tool] = None, config: Dict[str, Any] = None):
        if not LANGCHAIN_AVAILABLE:
            raise ImportError("LangChain not available")
        
        self.name = name
        self.llm = llm
        self.tools = tools or []
        self.config = config or {}
        self.memory = self._create_memory()
        self.agent = self._create_agent()
        
    def _create_memory(self):
        """Create memory for the agent"""
        memory_type = self.config.get('memory_type', 'buffer')
        
        if memory_type == 'buffer':
            return ConversationBufferMemory(
                memory_key="chat_history",
                return_messages=True,
                input_key="input"
            )
        elif memory_type == 'summary':
            return ConversationSummaryMemory(
                llm=self.llm,
                memory_key="chat_history",
                return_messages=True,
                input_key="input"
            )
        else:
            return None
    
    def _create_agent(self):
        """Create the LangChain agent"""
        # Create prompt template
        system_prompt = self.config.get('system_prompt', f"You are {self.name}, a helpful AI assistant.")
        
        # Create agent
        agent = create_agent(
            model=self.llm,
            tools=self.tools,
            system_prompt=system_prompt,
            debug=self.config.get('debug', False)
        )
        
        return agent
    
    async def execute(self, task: str) -> Dict[str, Any]:
        """Execute a task"""
        logger.info(f"LangChain agent {self.name} executing task: {task}")
        
        try:
            # Prepare input
            input_data = {
                "input": task,
                "chat_history": self.memory.load_memory_variables({})["chat_history"] if self.memory else []
            }
            
            # Execute task
            result = self.agent.invoke(input_data)
            
            # Update memory
            if self.memory:
                self.memory.save_context(
                    {"input": task},
                    {"output": str(result)}
                )
            
            return {
                "agent": self.name,
                "task": task,
                "result": str(result),
                "timestamp": asyncio.get_event_loop().time()
            }
            
        except Exception as e:
            logger.error(f"LangChain agent {self.name} execution failed: {e}")
            return {
                "agent": self.name,
                "task": task,
                "error": str(e),
                "timestamp": asyncio.get_event_loop().time()
            }
    
    def get_memory(self) -> List[Dict[str, str]]:
        """Get conversation memory"""
        if self.memory:
            return self.memory.load_memory_variables({})
        return []
    
    def clear_memory(self):
        """Clear conversation memory"""
        if self.memory:
            self.memory.clear()
    
    def update_tools(self, tools: List[Tool]):
        """Update agent tools"""
        self.tools = tools
        self.agent = self._create_agent()