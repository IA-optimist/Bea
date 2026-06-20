"""
Aider CLI Integration - AI-powered pair programming assistant

Features:
- Aider AI integration for pair programming
- Multi-file code editing
- Code review and suggestions
- Automated refactoring
- Git integration
- Context-aware assistance
"""

import asyncio
import subprocess
from typing import Dict, List, Any, Optional
from loguru import logger

try:
    import aider
    AIDER_AVAILABLE = True
except ImportError:
    AIDER_AVAILABLE = False

class AiderCLI:
    """Aider CLI integration for AI-powered pair programming"""

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.available = AIDER_AVAILABLE
        self.api_key = self.config.get('api_key') or self._get_api_key()
        self.model = self.config.get('model', 'gpt-4')
        self.aider = None

    def _get_api_key(self) -> Optional[str]:
        """Get API key from environment"""
        import os
        return os.getenv('OPENAI_API_KEY') or os.getenv('AIDER_API_KEY')

    def check_availability(self) -> bool:
        """Check if Aider CLI is available"""
        if not self.available:
            logger.error("Aider CLI not available")
            return False

        if not self.api_key:
            logger.error("API key not configured")
            return False

        try:
            # Check if aider command is available
            result = subprocess.run(['aider', '--version'],
                                  capture_output=True, text=True, timeout=10)
            return result.returncode == 0
        except Exception as e:
            logger.error(f"Aider CLI check failed: {e}")
            return False

    async def initialize_aider(self):
        """Initialize Aider"""
        if not self.check_availability():
            raise Exception("Aider CLI not available")

        try:
            self.aider = aider.Aider(
                api_key=self.api_key,
                model=self.model
            )
            logger.info("Aider initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Aider: {e}")
            raise

    async def edit_files(self, edits: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Edit multiple files using Aider"""
        logger.info(f"Editing files with Aider: {len(edits)} files")

        try:
            if not self.aider:
                await self.initialize_aider()

            results = []
            for edit in edits:
                result = await self.aider.edit_file(
                    edit['file_path'],
                    edit['instructions'],
                    edit['changes']
                )
                results.append(result)

            return {
                'edits': edits,
                'results': results,
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"File editing failed: {e}")
            return {'error': str(e)}

    async def refactor_code(self, file_path: str, refactoring_type: str) -> Dict[str, Any]:
        """Refactor code using Aider"""
        logger.info(f"Refactoring code with Aider: {refactoring_type}")

        try:
            refactoring_instructions = {
                'extract_method': "Extract a method from the selected code",
                'extract_variable': "Extract a variable from the selected code",
                'inline_method': "Inline the selected method",
                'rename_variable': "Rename the selected variable",
                'simplify_condition': "Simplify the selected conditional statement",
                'remove_duplication': "Remove code duplication",
                'improve_naming': "Improve variable and method names",
                'add_error_handling': "Add proper error handling",
                'optimize_performance': "Optimize for performance"
            }

            instructions = refactoring_instructions.get(refactoring_type,
                                                       f"Refactor the code for {refactoring_type}")

            result = await self.aider.edit_file(
                file_path,
                instructions
            )

            return {
                'file_path': file_path,
                'refactoring_type': refactoring_type,
                'result': result,
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Code refactoring failed: {e}")
            return {'error': str(e)}

    async def add_tests(self, file_path: str, test_framework: str = 'pytest') -> Dict[str, Any]:
        """Add tests to code using Aider"""
        logger.info(f"Adding {test_framework} tests to {file_path}")

        try:
            instructions = f"""
            Add comprehensive {test_framework} tests for the following code:
            
            - Include unit tests for all functions and methods
            - Add integration tests for complex workflows
            - Include edge cases and boundary conditions
            - Add proper mocking where needed
            - Follow {test_framework} best practices
            """

            result = await self.aider.edit_file(
                file_path,
                instructions
            )

            return {
                'file_path': file_path,
                'test_framework': test_framework,
                'result': result,
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Test addition failed: {e}")
            return {'error': str(e)}

    async def fix_bugs(self, file_path: str, error_description: str = None) -> Dict[str, Any]:
        """Fix bugs in code using Aider"""
        logger.info(f"Fixing bugs in {file_path}")

        try:
            instructions = "Fix the following bugs in the code:"

            if error_description:
                instructions += f"\n\nError description: {error_description}"

            result = await self.aider.edit_file(
                file_path,
                instructions
            )

            return {
                'file_path': file_path,
                'error_description': error_description,
                'result': result,
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Bug fixing failed: {e}")
            return {'error': str(e)}

    async def improve_code(self, file_path: str, focus_areas: List[str] = None) -> Dict[str, Any]:
        """Improve code quality using Aider"""
        logger.info(f"Improving code quality in {file_path}")

        try:
            areas = focus_areas or ['readability', 'performance', 'maintainability']
            instructions = f"""
            Improve the following code with focus on: {', '.join(areas)}
            
            Include:
            - Better variable and function names
            - Improved code structure
            - Enhanced error handling
            - Performance optimizations
            - Documentation and comments
            - Best practices adherence
            """

            result = await self.aider.edit_file(
                file_path,
                instructions
            )

            return {
                'file_path': file_path,
                'focus_areas': areas,
                'result': result,
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Code improvement failed: {e}")
            return {'error': str(e)}

    async def generate_documentation(self, file_path: str, doc_type: str = 'inline') -> Dict[str, Any]:
        """Generate documentation using Aider"""
        logger.info(f"Generating {doc_type} documentation in {file_path}")

        try:
            instructions = {
                'inline': "Add comprehensive inline documentation including comments and docstrings",
                'readme': "Generate a README.md file for the project",
                'api': "Generate API documentation for all public interfaces",
                'tutorial': "Generate a tutorial file explaining how to use the code"
            }

            instruction = instructions.get(doc_type, instructions['inline'])

            result = await self.aider.edit_file(
                file_path,
                instruction
            )

            return {
                'file_path': file_path,
                'doc_type': doc_type,
                'result': result,
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Documentation generation failed: {e}")
            return {'error': str(e)}

    async def analyze_code(self, file_path: str, analysis_type: str = 'comprehensive') -> Dict[str, Any]:
        """Analyze code using Aider"""
        logger.info(f"Analyzing code with Aider: {analysis_type}")

        try:
            instructions = {
                'comprehensive': "Perform a comprehensive code analysis including quality, performance, security, and maintainability",
                'security': "Analyze the code for security vulnerabilities and potential issues",
                'performance': "Analyze the code for performance bottlenecks and optimization opportunities",
                'architecture': "Analyze the code architecture and design patterns",
                'complexity': "Analyze code complexity and suggest improvements"
            }

            instruction = instructions.get(analysis_type, instructions['comprehensive'])

            result = await self.aider.edit_file(
                file_path,
                instruction
            )

            return {
                'file_path': file_path,
                'analysis_type': analysis_type,
                'result': result,
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Code analysis failed: {e}")
            return {'error': str(e)}

    async def create_feature(self, feature_description: str, file_paths: List[str]) -> Dict[str, Any]:
        """Create a new feature using Aider"""
        logger.info(f"Creating feature: {feature_description}")

        try:
            instructions = f"""
            Implement the following feature:
            
            {feature_description}
            
            Make the following changes to the files:
            """

            for i, file_path in enumerate(file_paths):
                instructions += f"\n- File {i+1}: {file_path}"

            result = await self.aider.edit_files(
                file_paths,
                instructions
            )

            return {
                'feature_description': feature_description,
                'file_paths': file_paths,
                'result': result,
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Feature creation failed: {e}")
            return {'error': str(e)}

    async def review_code(self, file_path: str, review_focus: List[str] = None) -> Dict[str, Any]:
        """Review code using Aider"""
        logger.info(f"Reviewing code in {file_path}")

        try:
            focus = review_focus or ['quality', 'performance', 'security', 'best_practices']
            instructions = f"""
            Review the following code with focus on: {', '.join(focus)}
            
            Provide detailed feedback including:
            - Code quality assessment
            - Performance considerations
            - Security issues
            - Best practices adherence
            - Suggested improvements
            - Potential bugs
            """

            result = await self.aider.edit_file(
                file_path,
                instructions
            )

            return {
                'file_path': file_path,
                'review_focus': focus,
                'result': result,
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Code review failed: {e}")
            return {'error': str(e)}

    async def migrate_code(self, file_path: str, target_framework: str, version: str = None) -> Dict[str, Any]:
        """Migrate code to a new framework using Aider"""
        logger.info(f"Migrating code to {target_framework}")

        try:
            instructions = f"""
            Migrate the following code to {target_framework}"
            
            Include:
            - Framework-specific optimizations
            - Breaking changes handling
            - Performance improvements
            - Best practices for the new framework
            """

            if version:
                instructions += f"\nTarget version: {version}"

            result = await self.aider.edit_file(
                file_path,
                instructions
            )

            return {
                'file_path': file_path,
                'target_framework': target_framework,
                'version': version,
                'result': result,
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Code migration failed: {e}")
            return {'error': str(e)}

    async def batch_edit(self, edit_requests: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Perform batch edits using Aider"""
        logger.info(f"Performing batch edits: {len(edit_requests)} requests")

        try:
            if not self.aider:
                await self.initialize_aider()

            results = []
            for request in edit_requests:
                result = await self.aider.edit_file(
                    request['file_path'],
                    request['instructions'],
                    request.get('changes')
                )
                results.append(result)

            return {
                'edit_requests': edit_requests,
                'results': results,
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Batch editing failed: {e}")
            return {'error': str(e)}

    async def create_project_structure(self, project_description: str, language: str = 'python') -> Dict[str, Any]:
        """Create project structure using Aider"""
        logger.info(f"Creating project structure: {project_description}")

        try:
            instructions = f"""
            Create a comprehensive project structure for:
            
            {project_description}
            
            Language: {language}
            
            Include:
            - Proper directory structure
            - Core modules and files
            - Configuration files
            - Setup and deployment files
            - Documentation structure
            - Test structure
            """

            # Create a temporary file to work with
            temp_file = f"{language}_project_structure.py"
            result = await self.aider.edit_file(
                temp_file,
                instructions
            )

            return {
                'project_description': project_description,
                'language': language,
                'result': result,
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Project structure creation failed: {e}")
            return {'error': str(e)}

    def get_version(self) -> Dict[str, Any]:
        """Get Aider CLI version"""
        if not self.check_availability():
            return {"error": "Aider CLI not available"}

        try:
            process = subprocess.run(['aider', '--version'],
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

    def install_aider(self) -> Dict[str, Any]:
        """Install Aider CLI"""
        logger.info("Installing Aider CLI")

        try:
            # Install via pip
            process = subprocess.run(['pip', 'install', 'aider-chat'],
                                  capture_output=True, text=True, timeout=60)

            if process.returncode == 0:
                logger.info("Aider CLI installed successfully")
                return {
                    'success': True,
                    'message': 'Aider CLI installed successfully',
                    'timestamp': asyncio.get_event_loop().time()
                }
            else:
                logger.error(f"Aider CLI installation failed: {process.stderr}")
                return {
                    'success': False,
                    'error': process.stderr,
                    'timestamp': asyncio.get_event_loop().time()
                }

        except Exception as e:
            logger.error(f"Aider CLI installation failed: {e}")
            return {
                'success': False,
                'error': str(e),
                'timestamp': asyncio.get_event_loop().time()
            }

    def configure_api_key(self, api_key: str) -> bool:
        """Configure API key"""
        try:
            # Store API key in config
            self.config['api_key'] = api_key
            self.api_key = api_key

            # Set up authentication
            process = subprocess.run(['aider', 'auth', 'login', api_key],
                                  capture_output=True, text=True, timeout=30)

            if process.returncode == 0:
                logger.info("API key configured successfully")
                return True
            else:
                logger.error(f"Failed to configure API key: {process.stderr}")
                return False

        except Exception as e:
            logger.error(f"Failed to configure API key: {e}")
            return False