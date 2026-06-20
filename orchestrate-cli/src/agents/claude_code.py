"""
Claude Code Integration - Anthropic's AI coding assistant

Features:
- Claude model interaction for code generation
- Code execution and analysis
- Code refactoring and optimization
- Multi-file project management
- Code review and suggestions
"""

import asyncio
import subprocess
from typing import Dict, List, Any, Optional
from loguru import logger

try:
    from anthropic import Anthropic
    CLAUDE_AVAILABLE = True
except ImportError:
    CLAUDE_AVAILABLE = False

class ClaudeCode:
    """Claude Code integration for Anthropic's AI coding assistant"""

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.available = CLAUDE_AVAILABLE
        self.api_key = self.config.get('api_key') or self._get_api_key()
        self.model = self.config.get('model', 'claude-3-sonnet-20240229')
        self.client = None

    def _get_api_key(self) -> Optional[str]:
        """Get Anthropic API key from environment"""
        import os
        return os.getenv('ANTHROPIC_API_KEY') or os.getenv('CLAUDE_API_KEY')

    def check_availability(self) -> bool:
        """Check if Claude Code is available"""
        if not self.available:
            logger.error("Claude Code not available")
            return False

        if not self.api_key:
            logger.error("Anthropic API key not configured")
            return False

        try:
            # Check if claude command is available
            result = subprocess.run(['claude', '--version'],
                                  capture_output=True, text=True, timeout=10)
            return result.returncode == 0
        except Exception as e:
            logger.error(f"Claude Code check failed: {e}")
            return False

    async def initialize_client(self):
        """Initialize Anthropic client"""
        if not self.check_availability():
            raise Exception("Claude Code not available")

        try:
            self.client = Anthropic(api_key=self.api_key)
            logger.info("Claude client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Claude client: {e}")
            raise

    async def generate_code(self, prompt: str, language: str = 'python', temperature: float = 0.7) -> Dict[str, Any]:
        """Generate code using Claude"""
        logger.info(f"Generating {language} code with Claude: {prompt}")

        if not self.client:
            await self.initialize_client()

        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=self.config.get('max_tokens', 4000),
                temperature=temperature,
                messages=[
                    {
                        "role": "system",
                        "content": f"You are an expert {language} programmer. Generate clean, efficient, and well-documented code following best practices."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            )

            generated_code = response.content[0].text

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

    async def analyze_code(self, code: str, analysis_type: str = 'comprehensive') -> Dict[str, Any]:
        """Analyze code using Claude"""
        logger.info(f"Analyzing code with Claude: {analysis_type}")

        try:
            prompts = {
                'comprehensive': f"""
                Analyze the following code comprehensively:
                
                {code}
                
                Provide feedback on:
                - Code quality and readability
                - Performance optimization opportunities
                - Security considerations
                - Best practices adherence
                - Maintainability and scalability
                """,
                'security': f"""
                Analyze the following code for security vulnerabilities:
                
                {code}
                
                Focus on:
                - Input validation
                - Authentication and authorization
                - Data protection
                - Common security patterns
                - Potential attack vectors
                """,
                'performance': f"""
                Analyze the following code for performance issues:
                
                {code}
                
                Focus on:
                - Algorithm efficiency
                - Memory usage
                - Execution speed
                - Bottlenecks
                - Optimization opportunities
                """,
                'architecture': f"""
                Analyze the following code architecture:
                
                {code}
                
                Focus on:
                - Design patterns
                - Code organization
                - Modularity
                - Dependency management
                - Scalability considerations
                """
            }

            prompt = prompts.get(analysis_type, prompts['comprehensive'])
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

    async def refactor_code(self, code: str, refactoring_goals: List[str] = None) -> Dict[str, Any]:
        """Refactor code using Claude"""
        logger.info(f"Refactoring code with Claude")

        try:
            goals = refactoring_goals or ['improve_readability', 'enhance_performance', 'add_error_handling']

            prompt = f"""
            Refactor the following code to achieve the following goals: {', '.join(goals)}
            
            Code:
            {code}
            
            Focus on:
            - Code structure and organization
            - Performance optimization
            - Error handling
            - Documentation and comments
            - Best practices adherence
            """

            response = await self.generate_code(prompt, 'python')

            return {
                'original_code': code,
                'refactoring_goals': goals,
                'refactored_code': response.get('generated_code', ''),
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Code refactoring failed: {e}")
            return {'error': str(e)}

    async def generate_tests(self, code: str, test_framework: str = 'pytest', coverage: str = 'comprehensive') -> Dict[str, Any]:
        """Generate tests for code using Claude"""
        logger.info(f"Generating {test_framework} tests for code")

        try:
            prompt = f"""
            Generate {test_framework} tests for the following code with {coverage} coverage:
            
            {code}
            
            Include:
            - Unit tests for all functions and methods
            - Integration tests for complex workflows
            - Edge cases and boundary conditions
            - Error handling tests
            - Performance tests where applicable
            - Mocking and fixtures as needed
            """

            response = await self.generate_code(prompt, 'python')

            return {
                'code': code,
                'test_framework': test_framework,
                'coverage': coverage,
                'generated_tests': response.get('generated_code', ''),
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Test generation failed: {e}")
            return {'error': str(e)}

    async def optimize_code(self, code: str, optimization_type: str = 'performance') -> Dict[str, Any]:
        """Optimize code using Claude"""
        logger.info(f"Optimizing code with Claude: {optimization_type}")

        try:
            prompts = {
                'performance': f"""
                Optimize the following code for performance:
                
                {code}
                
                Focus on:
                - Algorithm efficiency
                - Memory usage optimization
                - Execution speed improvements
                - Resource management
                - Caching strategies
                """,
                'memory': f"""
                Optimize the following code for memory efficiency:
                
                {code}
                
                Focus on:
                - Memory usage analysis
                - Data structure optimization
                - Garbage collection improvements
                - Memory leak prevention
                - Efficient data handling
                """,
                'scalability': f"""
                Optimize the following code for scalability:
                
                {code}
                
                Focus on:
                - Horizontal scaling considerations
                - Load balancing
                - Distributed processing
                - Concurrency optimization
                - Resource pooling
                """
            }

            prompt = prompts.get(optimization_type, prompts['performance'])
            response = await self.generate_code(prompt, 'python')

            return {
                'original_code': code,
                'optimization_type': optimization_type,
                'optimized_code': response.get('generated_code', ''),
                'optimization_explanation': self._extract_optimization_notes(response.get('generated_code', '')),
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Code optimization failed: {e}")
            return {'error': str(e)}

    def _extract_optimization_notes(self, code: str) -> str:
        """Extract optimization notes from generated code"""
        try:
            # Look for optimization comments and explanations
            lines = code.split('\n')
            notes = []

            for line in lines:
                if any(keyword in line.lower() for keyword in ['optimization', 'performance', 'improvement', 'efficiency']):
                    notes.append(line.strip())

            return '\n'.join(notes) if notes else "No specific optimization notes found"

        except Exception:
            return "Unable to extract optimization notes"

    async def review_pr(self, pr_url: str, review_focus: List[str] = None) -> Dict[str, Any]:
        """Review a pull request using Claude"""
        logger.info(f"Reviewing PR with Claude: {pr_url}")

        try:
            focus = review_focus or ['code_quality', 'security', 'performance', 'tests']

            prompt = f"""
            Review the following pull request with focus on: {', '.join(focus)}
            
            PR URL: {pr_url}
            
            Provide detailed feedback on:
            - Code quality and readability
            - Security considerations
            - Performance implications
            - Test coverage and quality
            - Documentation completeness
            - Integration with existing codebase
            """

            response = await self.generate_code(prompt, 'python')

            return {
                'pr_url': pr_url,
                'review_focus': focus,
                'review_result': response.get('generated_code', ''),
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"PR review failed: {e}")
            return {'error': str(e)}

    async def generate_documentation(self, code: str, doc_type: str = 'comprehensive') -> Dict[str, Any]:
        """Generate documentation for code using Claude"""
        logger.info(f"Generating {doc_type} documentation with Claude")

        try:
            prompts = {
                'comprehensive': f"""
                Generate comprehensive documentation for the following code:
                
                {code}
                
                Include:
                - Project overview and purpose
                - Installation and setup instructions
                - API documentation with examples
                - Usage examples and tutorials
                - Contributing guidelines
                - License information
                """,
                'api': f"""
                Generate API documentation for the following code:
                
                {code}
                
                Include:
                - Function and method signatures
                - Parameter descriptions and types
                - Return value documentation
                - Exception handling
                - Usage examples
                - Best practices
                """,
                'inline': f"""
                Generate inline documentation for the following code:
                
                {code}
                
                Add detailed comments explaining:
                - What the code does
                - How it works
                - Key algorithms and data structures
                - Important considerations
                - Potential edge cases
                """
            }

            prompt = prompts.get(doc_type, prompts['comprehensive'])
            response = await self.generate_code(prompt, 'python')

            return {
                'code': code,
                'doc_type': doc_type,
                'documentation': response.get('generated_code', ''),
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Documentation generation failed: {e}")
            return {'error': str(e)}

    async def debug_code(self, code: str, error_info: Dict[str, Any] = None) -> Dict[str, Any]:
        """Debug code using Claude"""
        logger.info("Debugging code with Claude")

        try:
            error_context = ""
            if error_info:
                error_context = f"""
                Error Information:
                - Type: {error_info.get('type', 'Unknown')}
                - Message: {error_info.get('message', 'No message')}
                - Stack Trace: {error_info.get('stack_trace', 'No stack trace')}
                """

            prompt = f"""
            Debug the following code{error_context}:
            
            Code:
            {code}
            
            Provide:
            - Root cause analysis
            - Step-by-step debugging process
            - Solutions to fix the issues
            - Prevention strategies
            """

            response = await self.generate_code(prompt, 'python')

            return {
                'code': code,
                'error_info': error_info,
                'debug_result': response.get('generated_code', ''),
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Code debugging failed: {e}")
            return {'error': str(e)}

    async def migrate_code(self, code: str, target_version: str, framework: str = None) -> Dict[str, Any]:
        """Migrate code to a new version or framework using Claude"""
        logger.info(f"Migrating code to {target_version}")

        try:
            framework_context = f" using {framework}" if framework else ""

            prompt = f"""
            Migrate the following code to {target_version}{framework_context}:
            
            {code}
            
            Include:
                - Version-specific updates
                - Breaking changes handling
                - Deprecation management
                - Backward compatibility where possible
                - Migration testing strategy
            """

            response = await self.generate_code(prompt, 'python')

            return {
                'original_code': code,
                'target_version': target_version,
                'framework': framework,
                'migrated_code': response.get('generated_code', ''),
                'migration_notes': self._extract_migration_notes(response.get('generated_code', '')),
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Code migration failed: {e}")
            return {'error': str(e)}

    def _extract_migration_notes(self, code: str) -> str:
        """Extract migration notes from generated code"""
        try:
            # Look for migration-specific comments
            lines = code.split('\n')
            notes = []

            for line in lines:
                if any(keyword in line.lower() for keyword in ['migration', 'deprecated', 'breaking', 'upgrade', 'version']):
                    notes.append(line.strip())

            return '\n'.join(notes) if notes else "No specific migration notes found"

        except Exception:
            return "Unable to extract migration notes"

    async def create_module_structure(self, project_description: str, language: str = 'python') -> Dict[str, Any]:
        """Create module structure for a project using Claude"""
        logger.info(f"Creating module structure for project: {project_description}")

        try:
            prompt = f"""
            Create a comprehensive module structure for the following project:
            
            {project_description}
            
            Language: {language}
            
            Include:
            - Main application structure
            - Organized directory layout
            - Core modules and their responsibilities
            - Configuration files
            - Tests directory structure
            - Documentation structure
            - Build and deployment files
            """

            response = await self.generate_code(prompt, language)

            return {
                'project_description': project_description,
                'language': language,
                'module_structure': response.get('generated_code', ''),
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Module structure creation failed: {e}")
            return {'error': str(e)}

    def get_version(self) -> Dict[str, Any]:
        """Get Claude Code version"""
        if not self.check_availability():
            return {"error": "Claude Code not available"}

        try:
            process = subprocess.run(['claude', '--version'],
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

    def install_claude(self) -> Dict[str, Any]:
        """Install Claude Code"""
        logger.info("Installing Claude Code")

        try:
            # Install via pip
            process = subprocess.run(['pip', 'install', 'anthropic'],
                                  capture_output=True, text=True, timeout=60)

            if process.returncode == 0:
                logger.info("Claude Code installed successfully")
                return {
                    'success': True,
                    'message': 'Claude Code installed successfully',
                    'timestamp': asyncio.get_event_loop().time()
                }
            else:
                logger.error(f"Claude Code installation failed: {process.stderr}")
                return {
                    'success': False,
                    'error': process.stderr,
                    'timestamp': asyncio.get_event_loop().time()
                }

        except Exception as e:
            logger.error(f"Claude Code installation failed: {e}")
            return {
                'success': False,
                'error': str(e),
                'timestamp': asyncio.get_event_loop().time()
            }

    def configure_api_key(self, api_key: str) -> bool:
        """Configure Anthropic API key"""
        try:
            # Store API key in config
            self.config['api_key'] = api_key
            self.api_key = api_key

            # Set up authentication
            process = subprocess.run(['claude', 'auth', 'login', api_key],
                                  capture_output=True, text=True, timeout=30)

            if process.returncode == 0:
                logger.info("Anthropic API key configured successfully")
                return True
            else:
                logger.error(f"Failed to configure Anthropic API key: {process.stderr}")
                return False

        except Exception as e:
            logger.error(f"Failed to configure Anthropic API key: {e}")
            return False