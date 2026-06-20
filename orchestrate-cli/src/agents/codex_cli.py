"""
Codex CLI Integration - OpenAI's code generation and execution

Features:
- OpenAI Codex model interaction
- Code generation in multiple languages
- Code execution and testing
- Natural language to code translation
- Code completion and suggestions
"""

import asyncio
import subprocess
from typing import Dict, Any, Optional
from loguru import logger

try:
    from openai import OpenAI
    CODEX_AVAILABLE = True
except ImportError:
    CODEX_AVAILABLE = False

class CodexCLI:
    """Codex CLI integration for OpenAI code generation and execution"""

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.available = CODEX_AVAILABLE
        self.api_key = self.config.get('api_key') or self._get_api_key()
        self.model = self.config.get('model', 'gpt-4')
        self.client = None

    def _get_api_key(self) -> Optional[str]:
        """Get OpenAI API key from environment"""
        import os
        return os.getenv('OPENAI_API_KEY') or os.getenv('CODEX_API_KEY')

    def check_availability(self) -> bool:
        """Check if Codex CLI is available"""
        if not self.available:
            logger.error("Codex CLI not available")
            return False

        if not self.api_key:
            logger.error("OpenAI API key not configured")
            return False

        try:
            # Check if openai command is available
            result = subprocess.run(['openai', '--version'],
                                  capture_output=True, text=True, timeout=10)
            return result.returncode == 0
        except Exception as e:
            logger.error(f"Codex CLI check failed: {e}")
            return False

    async def initialize_client(self):
        """Initialize OpenAI client"""
        if not self.check_availability():
            raise Exception("Codex CLI not available")

        try:
            self.client = OpenAI(api_key=self.api_key)
            logger.info("OpenAI client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI client: {e}")
            raise

    async def generate_code(self, prompt: str, language: str = 'python', temperature: float = 0.7) -> Dict[str, Any]:
        """Generate code using Codex"""
        logger.info(f"Generating {language} code with Codex: {prompt}")

        if not self.client:
            await self.initialize_client()

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": f"You are a {language} programming expert. Generate clean, efficient, and well-documented code."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=temperature,
                max_tokens=self.config.get('max_tokens', 4000)
            )

            generated_code = response.choices[0].message.content

            return {
                'model': self.model,
                'prompt': prompt,
                'language': language,
                'generated_code': generated_code,
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Code generation failed: {e}")
            return {'error': str(e)}

    async def complete_code(self, code: str, language: str = 'python') -> Dict[str, Any]:
        """Complete code using Codex"""
        logger.info(f"Completing {language} code")

        try:
            prompt = f"""
            Complete the following {language} code:
            
            ```{language}
            {code}
            ```
            """

            response = await self.generate_code(prompt, language)

            return {
                'original_code': code,
                'completed_code': response.get('generated_code', ''),
                'language': language,
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Code completion failed: {e}")
            return {'error': str(e)}

    async def execute_code(self, code: str, language: str = 'python') -> Dict[str, Any]:
        """Execute code using Codex"""
        logger.info(f"Executing {language} code")

        try:
            prompt = f"""
            Execute the following {language} code and provide the output:
            
            ```{language}
            {code}
            ```
            """

            response = await self.generate_code(prompt, language)

            return {
                'language': language,
                'code': code,
                'execution_result': response.get('generated_code', ''),
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Code execution failed: {e}")
            return {'error': str(e)}

    async def analyze_code(self, code: str, analysis_type: str = 'general') -> Dict[str, Any]:
        """Analyze code using Codex"""
        logger.info(f"Analyzing code with Codex: {analysis_type}")

        try:
            prompts = {
                'general': f"Analyze the following code and provide feedback:\n\n{code}",
                'security': f"Analyze the following code for security vulnerabilities:\n\n{code}",
                'performance': f"Analyze the following code for performance issues:\n\n{code}",
                'style': f"Analyze the following code for style and best practices:\n\n{code}",
                'complexity': f"Analyze the following code for complexity and maintainability:\n\n{code}"
            }

            prompt = prompts.get(analysis_type, prompts['general'])
            response = await self.generate_code(prompt, 'python')

            return {
                'analysis_type': analysis_type,
                'code': code,
                'analysis_result': response.get('generated_code', ''),
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Code analysis failed: {e}")
            return {'error': str(e)}

    async def refactor_code(self, code: str, refactoring_type: str = 'improve') -> Dict[str, Any]:
        """Refactor code using Codex"""
        logger.info(f"Refactoring code with Codex: {refactoring_type}")

        try:
            prompts = {
                'improve': f"Improve the following code by making it more efficient and readable:\n\n{code}",
                'modernize': f"Modernize the following code using current best practices:\n\n{code}",
                'optimize': f"Optimize the following code for better performance:\n\n{code}",
                'simplify': f"Simplify the following code while maintaining functionality:\n\n{code}",
                'document': f"Add comprehensive documentation to the following code:\n\n{code}"
            }

            prompt = prompts.get(refactoring_type, prompts['improve'])
            response = await self.generate_code(prompt, 'python')

            return {
                'original_code': code,
                'refactoring_type': refactoring_type,
                'refactored_code': response.get('generated_code', ''),
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Code refactoring failed: {e}")
            return {'error': str(e)}

    async def generate_tests(self, code: str, test_framework: str = 'pytest') -> Dict[str, Any]:
        """Generate tests for code using Codex"""
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
            - Mocking where necessary
            """

            response = await self.generate_code(prompt, 'python')

            return {
                'code': code,
                'test_framework': test_framework,
                'generated_tests': response.get('generated_code', ''),
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Test generation failed: {e}")
            return {'error': str(e)}

    async def translate_code(self, code: str, target_language: str) -> Dict[str, Any]:
        """Translate code to another language using Codex"""
        logger.info(f"Translating code to {target_language}")

        try:
            prompt = f"""
            Translate the following Python code to {target_language}:
            
            {code}
            
            Maintain the same functionality and logic.
            """

            response = await self.generate_code(prompt, target_language)

            return {
                'original_code': code,
                'target_language': target_language,
                'translated_code': response.get('generated_code', ''),
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Code translation failed: {e}")
            return {'error': str(e)}

    async def debug_code(self, code: str, error_message: str = None) -> Dict[str, Any]:
        """Debug code using Codex"""
        logger.info("Debugging code with Codex")

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

            response = await self.generate_code(prompt, 'python')

            return {
                'code': code,
                'error': error_message,
                'debug_result': response.get('generated_code', ''),
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Code debugging failed: {e}")
            return {'error': str(e)}

    async def convert_to_function(self, code: str, function_name: str = None) -> Dict[str, Any]:
        """Convert code snippet to a function using Codex"""
        logger.info("Converting code snippet to function")

        try:
            prompt = f"""
            Convert the following code snippet into a properly structured function:
            
            {code}
            
            Function name: {function_name or 'custom_function'}
            
            Include:
            - Proper function signature
            - Parameters and return values
            - Error handling
            - Documentation
            """

            response = await self.generate_code(prompt, 'python')

            return {
                'original_code': code,
                'function_name': function_name,
                'function_code': response.get('generated_code', ''),
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Function conversion failed: {e}")
            return {'error': str(e)}

    async def generate_api(self, code: str, api_type: str = 'rest') -> Dict[str, Any]:
        """Generate API interface for code using Codex"""
        logger.info(f"Generating {api_type} API for code")

        try:
            prompts = {
                'rest': f"""
                Generate a REST API interface for the following code:
                
                {code}
                
                Include:
                - FastAPI endpoints
                - Request/response models
                - Error handling
                - Documentation
                """,
                'graphql': f"""
                Generate a GraphQL API interface for the following code:
                
                {code}
                
                Include:
                - GraphQL schema
                - Resolvers
                - Mutations and queries
                - Error handling
                """,
                'grpc': f"""
                Generate a gRPC API interface for the following code:
                
                {code}
                
                Include:
                - Protocol Buffers definition
                - gRPC service
                - Server implementation
                - Client code
                """
            }

            prompt = prompts.get(api_type, prompts['rest'])
            response = await self.generate_code(prompt, 'python')

            return {
                'original_code': code,
                'api_type': api_type,
                'api_code': response.get('generated_code', ''),
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"API generation failed: {e}")
            return {'error': str(e)}

    async def optimize_for_framework(self, code: str, framework: str) -> Dict[str, Any]:
        """Optimize code for a specific framework using Codex"""
        logger.info(f"Optimizing code for {framework} framework")

        try:
            prompt = f"""
            Optimize the following code for {framework} framework:
            
            {code}
            
            Follow:
            - Framework best practices
            - Performance optimization
            - Code organization
            - Error handling patterns
            """

            response = await self.generate_code(prompt, 'python')

            return {
                'original_code': code,
                'framework': framework,
                'optimized_code': response.get('generated_code', ''),
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Framework optimization failed: {e}")
            return {'error': str(e)}

    def get_version(self) -> Dict[str, Any]:
        """Get Codex CLI version"""
        if not self.check_availability():
            return {"error": "Codex CLI not available"}

        try:
            process = subprocess.run(['openai', '--version'],
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

    def install_codex(self) -> Dict[str, Any]:
        """Install Codex CLI"""
        logger.info("Installing Codex CLI")

        try:
            # Install via pip
            process = subprocess.run(['pip', 'install', 'openai'],
                                  capture_output=True, text=True, timeout=60)

            if process.returncode == 0:
                logger.info("Codex CLI installed successfully")
                return {
                    'success': True,
                    'message': 'Codex CLI installed successfully',
                    'timestamp': asyncio.get_event_loop().time()
                }
            else:
                logger.error(f"Codex CLI installation failed: {process.stderr}")
                return {
                    'success': False,
                    'error': process.stderr,
                    'timestamp': asyncio.get_event_loop().time()
                }

        except Exception as e:
            logger.error(f"Codex CLI installation failed: {e}")
            return {
                'success': False,
                'error': str(e),
                'timestamp': asyncio.get_event_loop().time()
            }

    def configure_api_key(self, api_key: str) -> bool:
        """Configure OpenAI API key"""
        try:
            # Store API key in config
            self.config['api_key'] = api_key
            self.api_key = api_key

            # Set up authentication
            process = subprocess.run(['openai', 'login', api_key],
                                  capture_output=True, text=True, timeout=30)

            if process.returncode == 0:
                logger.info("OpenAI API key configured successfully")
                return True
            else:
                logger.error(f"Failed to configure OpenAI API key: {process.stderr}")
                return False

        except Exception as e:
            logger.error(f"Failed to configure OpenAI API key: {e}")
            return False
