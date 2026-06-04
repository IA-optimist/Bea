"""
Tool Registry - Centralized tool management for all frameworks

Features:
- Cross-framework tool registration
- Tool discovery and validation
- Dynamic tool loading
- Tool categorization
- Tool versioning
"""

import importlib
import inspect
import os
from typing import Dict, List, Any, Optional
from loguru import logger
import json

class ToolRegistry:
    """Centralized tool registry for all frameworks"""
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.tools: Dict[str, Dict[str, Any]] = {}
        self.framework_tools: Dict[str, List[str]] = {}
        self.tool_categories: Dict[str, List[str]] = {}
        
        # Initialize with default tools
        self._register_default_tools()
    
    def _register_default_tools(self):
        """Register default tools"""
        # Web search tool
        self.register_tool('web_search', {
            'name': 'web_search',
            'description': 'Search the web for information',
            'category': 'search',
            'frameworks': ['langchain', 'autogen', 'crewai'],
            'function': self._web_search,
            'parameters': {
                'query': {'type': 'string', 'required': True, 'description': 'Search query'}
            }
        })
        
        # File operations tool
        self.register_tool('file_operations', {
            'name': 'file_operations',
            'description': 'Read, write, and manage files',
            'category': 'filesystem',
            'frameworks': ['langchain', 'autogen', 'crewai'],
            'function': self._file_operations,
            'parameters': {
                'operation': {'type': 'string', 'required': True, 'description': 'Operation: read, write, list, delete'},
                'path': {'type': 'string', 'required': True, 'description': 'File path'},
                'content': {'type': 'string', 'required': False, 'description': 'Content to write'}
            }
        })
        
        # Code execution tool
        self.register_tool('code_execution', {
            'name': 'code_execution',
            'description': 'Execute Python code safely',
            'category': 'development',
            'frameworks': ['autogen', 'crewai'],
            'function': self._code_execution,
            'parameters': {
                'code': {'type': 'string', 'required': True, 'description': 'Python code to execute'},
                'timeout': {'type': 'integer', 'required': False, 'description': 'Execution timeout in seconds'}
            }
        })
        
        # Data analysis tool
        self.register_tool('data_analysis', {
            'name': 'data_analysis',
            'description': 'Analyze data and generate insights',
            'category': 'data',
            'frameworks': ['langchain', 'crewai'],
            'function': self._data_analysis,
            'parameters': {
                'data': {'type': 'string', 'required': True, 'description': 'Data to analyze'},
                'analysis_type': {'type': 'string', 'required': False, 'description': 'Type of analysis'}
            }
        })
        
        # API integration tool
        self.register_tool('api_integration', {
            'name': 'api_integration',
            'description': 'Integrate with external APIs',
            'category': 'integration',
            'frameworks': ['langchain', 'autogen'],
            'function': self._api_integration,
            'parameters': {
                'endpoint': {'type': 'string', 'required': True, 'description': 'API endpoint URL'},
                'method': {'type': 'string', 'required': False, 'description': 'HTTP method: GET, POST, PUT, DELETE'},
                'headers': {'type': 'object', 'required': False, 'description': 'HTTP headers'},
                'data': {'type': 'object', 'required': False, 'description': 'Request data'}
            }
        })
    
    def register_tool(self, tool_name: str, tool_config: Dict[str, Any]):
        """Register a new tool"""
        logger.info(f"Registering tool: {tool_name}")
        
        # Validate tool configuration
        if not self._validate_tool_config(tool_config):
            logger.error(f"Invalid tool configuration for: {tool_name}")
            return False
        
        # Store tool
        self.tools[tool_name] = tool_config
        
        # Update framework tools
        for framework in tool_config.get('frameworks', []):
            if framework not in self.framework_tools:
                self.framework_tools[framework] = []
            self.framework_tools[framework].append(tool_name)
        
        # Update categories
        category = tool_config.get('category', 'general')
        if category not in self.tool_categories:
            self.tool_categories[category] = []
        self.tool_categories[category].append(tool_name)
        
        logger.info(f"Tool {tool_name} registered successfully")
        return True
    
    def _validate_tool_config(self, tool_config: Dict[str, Any]) -> bool:
        """Validate tool configuration"""
        required_fields = ['name', 'description', 'function', 'parameters']
        
        for field in required_fields:
            if field not in tool_config:
                logger.error(f"Missing required field: {field}")
                return False
        
        # Validate function
        if not callable(tool_config['function']):
            logger.error("Tool function must be callable")
            return False
        
        # Validate parameters
        parameters = tool_config.get('parameters', {})
        for param_name, param_config in parameters.items():
            if not isinstance(param_config, dict):
                logger.error(f"Parameter {param_name} must be a dictionary")
                return False
            
            if 'type' not in param_config:
                logger.error(f"Parameter {param_name} missing type")
                return False
        
        return True
    
    def get_tool(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """Get a specific tool"""
        return self.tools.get(tool_name)
    
    def get_tools_for_framework(self, framework: str) -> List[Dict[str, Any]]:
        """Get all tools for a specific framework"""
        tool_names = self.framework_tools.get(framework, [])
        return [self.tools[name] for name in tool_names]
    
    def get_tools_by_category(self, category: str) -> List[Dict[str, Any]]:
        """Get all tools by category"""
        tool_names = self.tool_categories.get(category, [])
        return [self.tools[name] for name in tool_names]
    
    def get_all_tools(self) -> Dict[str, Dict[str, Any]]:
        """Get all registered tools"""
        return self.tools
    
    def list_tools(self) -> List[str]:
        """List all tool names"""
        return list(self.tools.keys())
    
    def get_tool_info(self, tool_name: str) -> Dict[str, Any]:
        """Get detailed information about a tool"""
        tool = self.get_tool(tool_name)
        if not tool:
            return {'error': f'Tool not found: {tool_name}'}
        
        info = {
            'name': tool['name'],
            'description': tool['description'],
            'category': tool['category'],
            'frameworks': tool['frameworks'],
            'parameters': tool['parameters'],
            'available': True
        }
        
        return info
    
    def remove_tool(self, tool_name: str) -> bool:
        """Remove a tool from registry"""
        if tool_name not in self.tools:
            return False
        
        # Remove tool
        tool_config = self.tools.pop(tool_name)
        
        # Remove from framework tools
        for framework in tool_config.get('frameworks', []):
            if framework in self.framework_tools:
                self.framework_tools[framework].remove(tool_name)
        
        # Remove from categories
        category = tool_config.get('category', 'general')
        if category in self.tool_categories:
            self.tool_categories[category].remove(tool_name)
        
        logger.info(f"Tool {tool_name} removed from registry")
        return True
    
    def load_tools_from_module(self, module_name: str) -> int:
        """Load tools from a Python module"""
        try:
            module = importlib.import_module(module_name)
            tools_loaded = 0
            
            # Look for tool functions
            for name, obj in inspect.getmembers(module):
                if inspect.isfunction(obj) and hasattr(obj, '_tool_config'):
                    tool_config = getattr(obj, '_tool_config')
                    if self.register_tool(tool_config['name'], tool_config):
                        tools_loaded += 1
            
            logger.info(f"Loaded {tools_loaded} tools from module: {module_name}")
            return tools_loaded
            
        except Exception as e:
            logger.error(f"Failed to load tools from module {module_name}: {e}")
            return 0
    
    def load_tools_from_file(self, file_path: str) -> int:
        """Load tools from a JSON file"""
        try:
            with open(file_path, 'r') as f:
                tools_data = json.load(f)
            
            tools_loaded = 0
            
            for tool_name, tool_config in tools_data.items():
                if self.register_tool(tool_name, tool_config):
                    tools_loaded += 1
            
            logger.info(f"Loaded {tools_loaded} tools from file: {file_path}")
            return tools_loaded
            
        except Exception as e:
            logger.error(f"Failed to load tools from file {file_path}: {e}")
            return 0
    
    # Tool implementations
    def _web_search(self, query: str) -> str:
        """Web search implementation"""
        try:
            import requests
            
            # Simple web search (placeholder)
            response = requests.get(f"https://api.duckduckgo.com/?q={query}&format=json")
            data = response.json()
            
            return f"Search results for '{query}':\n{json.dumps(data, indent=2)}"
            
        except Exception as e:
            logger.error(f"Web search failed: {e}")
            return f"Web search failed: {e}"
    
    def _file_operations(self, operation: str, path: str, content: str = None) -> str:
        """File operations implementation"""
        try:
            import os
            
            if operation == 'read':
                with open(path, 'r') as f:
                    return f.read()
            
            elif operation == 'write':
                with open(path, 'w') as f:
                    f.write(content)
                return f"File written: {path}"
            
            elif operation == 'list':
                files = os.listdir(path)
                return f"Files in {path}: {files}"
            
            elif operation == 'delete':
                os.remove(path)
                return f"File deleted: {path}"
            
            else:
                return f"Unknown operation: {operation}"
                
        except Exception as e:
            logger.error(f"File operations failed: {e}")
            return f"File operations failed: {e}"
    
    def _code_execution(self, code: str, timeout: int = 10) -> str:
        """Code execution implementation"""
        try:
            import subprocess
            import tempfile
            
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(code)
                temp_file = f.name
            
            result = subprocess.run(['python', temp_file], 
                                  capture_output=True, text=True, timeout=timeout)
            
            os.unlink(temp_file)
            
            return f"Exit code: {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
            
        except Exception as e:
            logger.error(f"Code execution failed: {e}")
            return f"Code execution failed: {e}"
    
    def _data_analysis(self, data: str, analysis_type: str = 'basic') -> str:
        """Data analysis implementation"""
        try:
            import pandas as pd
            import io
            
            # Parse data
            df = pd.read_csv(io.StringIO(data))
            
            if analysis_type == 'basic':
                return f"Data shape: {df.shape}\nColumns: {list(df.columns)}\n\n{df.describe()}"
            
            elif analysis_type == 'detailed':
                return f"Data shape: {df.shape}\nColumns: {list(df.columns)}\n\n{df.describe()}\n\nMissing values:\n{df.isnull().sum()}"
            
            else:
                return f"Unknown analysis type: {analysis_type}"
                
        except Exception as e:
            logger.error(f"Data analysis failed: {e}")
            return f"Data analysis failed: {e}"
    
    def _api_integration(self, endpoint: str, method: str = 'GET', headers: Dict[str, str] = None, data: Dict[str, Any] = None) -> str:
        """API integration implementation"""
        try:
            import requests
            
            response = requests.request(method, endpoint, headers=headers, json=data)
            
            return f"Status: {response.status_code}\nResponse: {response.text}"
            
        except Exception as e:
            logger.error(f"API integration failed: {e}")
            return f"API integration failed: {e}"

# Decorator for tool registration
def tool(name: str, description: str, category: str = 'general', frameworks: List[str] = None):
    """Decorator to register a function as a tool"""
    def decorator(func):
        # Store tool configuration
        setattr(func, '_tool_config', {
            'name': name,
            'description': description,
            'category': category,
            'frameworks': frameworks or ['langchain'],
            'parameters': {}
        })
        
        # Extract parameter information
        sig = inspect.signature(func)
        for param_name, param in sig.parameters.items():
            if param_name != 'self' and param_name != 'cls':
                setattr(func, '_tool_config')['parameters'][param_name] = {
                    'type': str(param.annotation) if param.annotation != inspect.Parameter.empty else 'any',
                    'required': param.default == inspect.Parameter.empty,
                    'description': param.default if param.default != inspect.Parameter.empty else ''
                }
        
        return func
    
    return decorator