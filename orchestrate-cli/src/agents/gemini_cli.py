"""
Gemini CLI Integration - Google's AI model interaction

Features:
- Google Gemini model interaction
- Code execution and analysis
- Content generation and summarization
- Multi-turn conversations
- Tool integration with Google services
"""

import asyncio
import json
import subprocess
from typing import Dict, List, Any, Optional
from loguru import logger

try:
    from google.gemini import GeminiClient
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

class GeminiCLI:
    """Gemini CLI integration for Google AI model interaction"""
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.available = GEMINI_AVAILABLE
        self.api_key = self.config.get('api_key') or self._get_api_key()
        self.model = self.config.get('model', 'gemini-pro')
        self.client = None
        
    def _get_api_key(self) -> Optional[str]:
        """Get Gemini API key from environment"""
        import os
        return os.getenv('GOOGLE_GEMINI_API_KEY') or os.getenv('GEMINI_API_KEY')
    
    def check_availability(self) -> bool:
        """Check if Gemini CLI is available"""
        if not self.available:
            logger.error("Gemini CLI not available")
            return False
        
        if not self.api_key:
            logger.error("Gemini API key not configured")
            return False
        
        try:
            # Check if gemini command is available
            result = subprocess.run(['gemini', '--version'], 
                                  capture_output=True, text=True, timeout=10)
            return result.returncode == 0
        except Exception as e:
            logger.error(f"Gemini CLI check failed: {e}")
            return False
    
    async def initialize_client(self):
        """Initialize Gemini client"""
        if not self.check_availability():
            raise Exception("Gemini CLI not available")
        
        try:
            self.client = GeminiClient(
                api_key=self.api_key,
                model=self.model
            )
            logger.info("Gemini client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Gemini client: {e}")
            raise
    
    async def generate_content(self, prompt: str, temperature: float = 0.7) -> Dict[str, Any]:
        """Generate content using Gemini"""
        logger.info(f"Generating content with Gemini: {prompt}")
        
        if not self.client:
            await self.initialize_client()
        
        try:
            result = await self.client.generate(
                prompt=prompt,
                temperature=temperature,
                max_tokens=self.config.get('max_tokens', 4000)
            )
            
            return {
                'model': self.model,
                'prompt': prompt,
                'result': result,
                'timestamp': asyncio.get_event_loop().time()
            }
            
        except Exception as e:
            logger.error(f"Content generation failed: {e}")
            return {'error': str(e)}
    
    async def execute_code(self, code: str, language: str = 'python') -> Dict[str, Any]:
        """Execute code using Gemini"""
        logger.info(f"Executing {language} code with Gemini")
        
        try:
            prompt = f"""
            Please execute the following {language} code and provide the output:
            
            ```{language}
            {code}
            ```
            """
            
            result = await self.generate_content(prompt)
            
            return {
                'language': language,
                'code': code,
                'result': result,
                'timestamp': asyncio.get_event_loop().time()
            }
            
        except Exception as e:
            logger.error(f"Code execution failed: {e}")
            return {'error': str(e)}
    
    async def analyze_code(self, code: str, analysis_type: str = 'general') -> Dict[str, Any]:
        """Analyze code using Gemini"""
        logger.info(f"Analyzing code with Gemini: {analysis_type}")
        
        try:
            prompts = {
                'general': f"Analyze the following code and provide feedback:\n\n{code}",
                'security': f"Analyze the following code for security vulnerabilities:\n\n{code}",
                'performance': f"Analyze the following code for performance issues:\n\n{code}",
                'style': f"Analyze the following code for style and best practices:\n\n{code}"
            }
            
            prompt = prompts.get(analysis_type, prompts['general'])
            result = await self.generate_content(prompt)
            
            return {
                'analysis_type': analysis_type,
                'code': code,
                'result': result,
                'timestamp': asyncio.get_event_loop().time()
            }
            
        except Exception as e:
            logger.error(f"Code analysis failed: {e}")
            return {'error': str(e)}
    
    async def explain_code(self, code: str) -> Dict[str, Any]:
        """Explain code using Gemini"""
        logger.info("Explaining code with Gemini")
        
        try:
            prompt = f"""
            Please explain the following code step by step:
            
            {code}
            """
            
            result = await self.generate_content(prompt)
            
            return {
                'code': code,
                'explanation': result,
                'timestamp': asyncio.get_event_loop().time()
            }
            
        except Exception as e:
            logger.error(f"Code explanation failed: {e}")
            return {'error': str(e)}
    
    async def generate_tests(self, code: str, test_framework: str = 'pytest') -> Dict[str, Any]:
        """Generate tests for code using Gemini"""
        logger.info(f"Generating {test_framework} tests for code")
        
        try:
            prompt = f"""
            Generate comprehensive {test_framework} tests for the following code:
            
            {code}
            
            Include:
            - Unit tests
            - Integration tests
            - Edge cases
            - Error handling
            """
            
            result = await self.generate_content(prompt)
            
            return {
                'code': code,
                'test_framework': test_framework,
                'tests': result,
                'timestamp': asyncio.get_event_loop().time()
            }
            
        except Exception as e:
            logger.error(f"Test generation failed: {e}")
            return {'error': str(e)}
    
    async def optimize_code(self, code: str, optimization_type: str = 'performance') -> Dict[str, Any]:
        """Optimize code using Gemini"""
        logger.info(f"Optimizing code with Gemini: {optimization_type}")
        
        try:
            prompts = {
                'performance': f"""
                Optimize the following code for better performance:
                
                {code}
                
                Focus on:
                - Algorithm efficiency
                - Memory usage
                - Execution speed
                - Resource optimization
                """,
                'readability': f"""
                Improve the readability of the following code:
                
                {code}
                
                Focus on:
                - Clear variable names
                - Proper formatting
                - Comments and documentation
                - Structure and organization
                """,
                'maintenance': f"""
                Make the following code more maintainable:
                
                {code}
                
                Focus on:
                - Modularity
                - Reusability
                - Error handling
                - Documentation
                """
            }
            
            prompt = prompts.get(optimization_type, prompts['performance'])
            result = await self.generate_content(prompt)
            
            return {
                'code': code,
                'optimization_type': optimization_type,
                'optimized_code': result,
                'timestamp': asyncio.get_event_loop().time()
            }
            
        except Exception as e:
            logger.error(f"Code optimization failed: {e}")
            return {'error': str(e)}
    
    async def translate_code(self, code: str, target_language: str) -> Dict[str, Any]:
        """Translate code to another language using Gemini"""
        logger.info(f"Translating code to {target_language}")
        
        try:
            prompt = f"""
            Translate the following code from Python to {target_language}:
            
            {code}
            
            Maintain the same functionality and logic.
            """
            
            result = await self.generate_content(prompt)
            
            return {
                'original_code': code,
                'target_language': target_language,
                'translated_code': result,
                'timestamp': asyncio.get_event_loop().time()
            }
            
        except Exception as e:
            logger.error(f"Code translation failed: {e}")
            return {'error': str(e)}
    
    async def debug_code(self, code: str, error_message: str = None) -> Dict[str, Any]:
        """Debug code using Gemini"""
        logger.info("Debugging code with Gemini")
        
        try:
            if error_message:
                prompt = f"""
                Debug the following code that produces this error:
                
                Error: {error_message}
                
                Code:
                {code}
                """
            else:
                prompt = f"""
                Debug the following code and identify any issues:
                
                {code}
                """
            
            result = await self.generate_content(prompt)
            
            return {
                'code': code,
                'error': error_message,
                'debug_result': result,
                'timestamp': asyncio.get_event_loop().time()
            }
            
        except Exception as e:
            logger.error(f"Code debugging failed: {e}")
            return {'error': str(e)}
    
    async def generate_documentation(self, code: str, doc_type: str = 'readme') -> Dict[str, Any]:
        """Generate documentation for code using Gemini"""
        logger.info(f"Generating {doc_type} documentation for code")
        
        try:
            prompts = {
                'readme': f"""
                Generate a comprehensive README.md for the following code:
                
                {code}
                
                Include:
                - Project description
                - Installation instructions
                - Usage examples
                - API documentation
                - Contributing guidelines
                """,
                'api': f"""
                Generate API documentation for the following code:
                
                {code}
                
                Include:
                - Function signatures
                - Parameter descriptions
                - Return values
                - Examples
                - Error handling
                """,
                'inline': f"""
                Generate inline documentation for the following code:
                
                {code}
                
                Add detailed comments explaining:
                - What the code does
                - How it works
                - Key algorithms
                - Important considerations
                """
            }
            
            prompt = prompts.get(doc_type, prompts['readme'])
            result = await self.generate_content(prompt)
            
            return {
                'code': code,
                'doc_type': doc_type,
                'documentation': result,
                'timestamp': asyncio.get_event_loop().time()
            }
            
        except Exception as e:
            logger.error(f"Documentation generation failed: {e}")
            return {'error': str(e)}
    
    def get_version(self) -> Dict[str, Any]:
        """Get Gemini CLI version"""
        if not self.check_availability():
            return {"error": "Gemini CLI not available"}
        
        try:
            process = subprocess.run(['gemini', '--version'], 
                                  capture_output=True, text=True, timeout=10)
            
            return {
                'version': process.stdout.strip(),
                'available': True,
                'timestamp': asyncio.get_event_loop().time()
            }
            
        except Exception as e:
            return {
                'error': str(e),
                'available': False,
                'timestamp': asyncio.get_event_loop().time()
            }
    
    def install_gemini(self) -> Dict[str, Any]:
        """Install Gemini CLI"""
        logger.info("Installing Gemini CLI")
        
        try:
            # Install via pip
            process = subprocess.run(['pip', 'install', 'google-gemini-cli'], 
                                  capture_output=True, text=True, timeout=60)
            
            if process.returncode == 0:
                logger.info("Gemini CLI installed successfully")
                return {
                    'success': True,
                    'message': 'Gemini CLI installed successfully',
                    'timestamp': asyncio.get_event_loop().time()
                }
            else:
                logger.error(f"Gemini CLI installation failed: {process.stderr}")
                return {
                    'success': False,
                    'error': process.stderr,
                    'timestamp': asyncio.get_event_loop().time()
                }
                
        except Exception as e:
            logger.error(f"Gemini CLI installation failed: {e}")
            return {
                'success': False,
                'error': str(e),
                'timestamp': asyncio.get_event_loop().time()
            }
    
    def configure_api_key(self, api_key: str) -> bool:
        """Configure Gemini API key"""
        try:
            # Store API key in config
            self.config['api_key'] = api_key
            self.api_key = api_key
            
            # Set up authentication
            process = subprocess.run(['gemini', 'auth', 'login', api_key], 
                                  capture_output=True, text=True, timeout=30)
            
            if process.returncode == 0:
                logger.info("Gemini API key configured successfully")
                return True
            else:
                logger.error(f"Failed to configure Gemini API key: {process.stderr}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to configure Gemini API key: {e}")
            return False