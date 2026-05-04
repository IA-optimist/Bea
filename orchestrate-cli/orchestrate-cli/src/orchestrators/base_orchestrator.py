"""
Base Orchestrator - Abstract base class for framework orchestrators

This class provides the common interface and functionality for all framework orchestrators.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional
from loguru import logger

class BaseOrchestrator(ABC):
    """Base class for all framework orchestrators"""
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.name = self.__class__.__name__
        self.enabled = self.config.get('enabled', True)
        self.agents = {}
        self.initialized = False
        
    @abstractmethod
    async def initialize(self):
        """Initialize the orchestrator"""
        pass
    
    @abstractmethod
    async def execute(self, task: str, agents: List[str] = None) -> Dict[str, Any]:
        """Execute a task using the orchestrator"""
        pass
    
    @abstractmethod
    async def test_agents(self, agents: List[str]) -> Dict[str, Any]:
        """Test specific agents"""
        pass
    
    @abstractmethod
    def get_available_agents(self) -> Dict[str, Any]:
        """Get list of available agents"""
        pass
    
    def load_config(self, config: Dict[str, Any]):
        """Load configuration"""
        self.config = config
        self.enabled = config.get('enabled', True)
        logger.info(f"Loaded config for {self.name}: enabled={self.enabled}")
    
    def is_initialized(self) -> bool:
        """Check if orchestrator is initialized"""
        return self.initialized
    
    def get_name(self) -> str:
        """Get orchestrator name"""
        return self.name
    
    def is_enabled(self) -> bool:
        """Check if orchestrator is enabled"""
        return self.enabled
    
    async def validate_config(self) -> bool:
        """Validate configuration"""
        try:
            # Basic validation
            if not self.config:
                logger.error(f"No configuration provided for {self.name}")
                return False
            
            if not self.enabled:
                logger.warning(f"Orchestrator {self.name} is disabled")
                return False
            
            # Framework-specific validation should be implemented in subclasses
            return await self._validate_framework_config()
            
        except Exception as e:
            logger.error(f"Configuration validation failed for {self.name}: {e}")
            return False
    
    @abstractmethod
    async def _validate_framework_config(self) -> bool:
        """Validate framework-specific configuration"""
        pass
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check"""
        try:
            return {
                'name': self.name,
                'enabled': self.enabled,
                'initialized': self.initialized,
                'status': 'healthy' if self.enabled and self.initialized else 'unhealthy'
            }
        except Exception as e:
            logger.error(f"Health check failed for {self.name}: {e}")
            return {
                'name': self.name,
                'enabled': self.enabled,
                'initialized': self.initialized,
                'status': 'error',
                'error': str(e)
            }