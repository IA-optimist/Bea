"""
GitHub Copilot CLI Integration - AI-powered coding assistance

Features:
- GitHub Copilot integration
- Code completion and suggestions
- Code generation from natural language
- Inline code assistance
- Multi-language support
- GitHub repository integration
"""

import asyncio
import json
import subprocess
from typing import Dict, List, Any, Optional
from loguru import logger

try:
    import github
    COPILOT_AVAILABLE = True
except ImportError:
    COPILOT_AVAILABLE = False

class GitHubCopilotCLI:
    """GitHub Copilot CLI integration for AI-powered coding assistance"""
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.available = COPILOT_AVAILABLE
        self.token = self.config.get('token') or self._get_token()
        self.model = self.config.get('model', 'gpt-4')
        self.github_client = None
        
    def _get_token(self) -> Optional[str]:
        """Get GitHub token from environment"""
        import os
        return os.getenv('GITHUB_TOKEN') or os.getenv('GH_TOKEN')
    
    def check_availability(self) -> bool:
        """Check if GitHub Copilot CLI is available"""
        if not self.available:
            logger.error("GitHub Copilot CLI not available")
            return False
        
        if not self.token:
            logger.error("GitHub token not configured")
            return False
        
        try:
            # Check if gh command is available
            result = subprocess.run(['gh', '--version'], 
                                  capture_output=True, text=True, timeout=10)
            return result.returncode == 0
        except Exception as e:
            logger.error(f"GitHub Copilot CLI check failed: {e}")
            return False
    
    async def initialize_client(self):
        """Initialize GitHub client"""
        if not self.check_availability():
            raise Exception("GitHub Copilot CLI not available")
        
        try:
            self.github_client = github.Github(self.token)
            logger.info("GitHub client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize GitHub client: {e}")
            raise
    
    async def suggest_code(self, code: str, language: str = 'python') -> Dict[str, Any]:
        """Get code suggestions from Copilot"""
        logger.info(f"Getting code suggestions for {language} code")
        
        try:
            # Use GitHub Copilot CLI for suggestions
            cmd = [
                'gh', 'copilot', 'suggest',
                '--language', language,
                '--', code
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.config.get('working_directory', './')
            )
            
            stdout, stderr = await process.communicate()
            
            return {
                'original_code': code,
                'language': language,
                'suggestions': stdout.decode(),
                'exit_code': process.returncode,
                'timestamp': asyncio.get_event_loop().time()
            }
            
        except Exception as e:
            logger.error(f"Code suggestion failed: {e}")
            return {'error': str(e)}
    
    async def explain_code(self, code: str) -> Dict[str, Any]:
        """Explain code using Copilot"""
        logger.info("Explaining code with Copilot")
        
        try:
            # Use GitHub Copilot CLI for explanation
            cmd = [
                'gh', 'copilot', 'explain',
                '--', code
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.config.get('working_directory', './')
            )
            
            stdout, stderr = await process.communicate()
            
            return {
                'code': code,
                'explanation': stdout.decode(),
                'exit_code': process.returncode,
                'timestamp': asyncio.get_event_loop().time()
            }
            
        except Exception as e:
            logger.error(f"Code explanation failed: {e}")
            return {'error': str(e)}
    
    async def generate_code(self, prompt: str, language: str = 'python') -> Dict[str, Any]:
        """Generate code using Copilot"""
        logger.info(f"Generating {language} code with Copilot")
        
        try:
            # Use GitHub Copilot CLI for code generation
            cmd = [
                'gh', 'copilot', 'generate',
                '--language', language,
                '--', prompt
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.config.get('working_directory', './')
            )
            
            stdout, stderr = await process.communicate()
            
            return {
                'prompt': prompt,
                'language': language,
                'generated_code': stdout.decode(),
                'exit_code': process.returncode,
                'timestamp': asyncio.get_event_loop().time()
            }
            
        except Exception as e:
            logger.error(f"Code generation failed: {e}")
            return {'error': str(e)}
    
    async def complete_function(self, function_signature: str, language: str = 'python') -> Dict[str, Any]:
        """Complete function implementation using Copilot"""
        logger.info(f"Completing function implementation for {language}")
        
        try:
            # Use GitHub Copilot CLI for function completion
            cmd = [
                'gh', 'copilot', 'complete',
                '--language', language,
                '--function', function_signature
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.config.get('working_directory', './')
            )
            
            stdout, stderr = await process.communicate()
            
            return {
                'function_signature': function_signature,
                'language': language,
                'completed_function': stdout.decode(),
                'exit_code': process.returncode,
                'timestamp': asyncio.get_event_loop().time()
            }
            
        except Exception as e:
            logger.error(f"Function completion failed: {e}")
            return {'error': str(e)}
    
    async def test_code(self, code: str, test_framework: str = 'pytest') -> Dict[str, Any]:
        """Generate tests for code using Copilot"""
        logger.info(f"Generating {test_framework} tests with Copilot")
        
        try:
            # Use GitHub Copilot CLI for test generation
            cmd = [
                'gh', 'copilot', 'test',
                '--language', 'python',
                '--framework', test_framework,
                '--', code
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.config.get('working_directory', './')
            )
            
            stdout, stderr = await process.communicate()
            
            return {
                'code': code,
                'test_framework': test_framework,
                'generated_tests': stdout.decode(),
                'exit_code': process.returncode,
                'timestamp': asyncio.get_event_loop().time()
            }
            
        except Exception as e:
            logger.error(f"Test generation failed: {e}")
            return {'error': str(e)}
    
    async def optimize_code(self, code: str, optimization_type: str = 'performance') -> Dict[str, Any]:
        """Optimize code using Copilot"""
        logger.info(f"Optimizing code with Copilot: {optimization_type}")
        
        try:
            # Use GitHub Copilot CLI for code optimization
            cmd = [
                'gh', 'copilot', 'optimize',
                '--language', 'python',
                '--type', optimization_type,
                '--', code
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.config.get('working_directory', './')
            )
            
            stdout, stderr = await process.communicate()
            
            return {
                'original_code': code,
                'optimization_type': optimization_type,
                'optimized_code': stdout.decode(),
                'exit_code': process.returncode,
                'timestamp': asyncio.get_event_loop().time()
            }
            
        except Exception as e:
            logger.error(f"Code optimization failed: {e}")
            return {'error': str(e)}
    
    async def refactor_code(self, code: str, refactoring_type: str = 'improve') -> Dict[str, Any]:
        """Refactor code using Copilot"""
        logger.info(f"Refactoring code with Copilot: {refactoring_type}")
        
        try:
            # Use GitHub Copilot CLI for code refactoring
            cmd = [
                'gh', 'copilot', 'refactor',
                '--language', 'python',
                '--type', refactoring_type,
                '--', code
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.config.get('working_directory', './')
            )
            
            stdout, stderr = await process.communicate()
            
            return {
                'original_code': code,
                'refactoring_type': refactoring_type,
                'refactored_code': stdout.decode(),
                'exit_code': process.returncode,
                'timestamp': asyncio.get_event_loop().time()
            }
            
        except Exception as e:
            logger.error(f"Code refactoring failed: {e}")
            return {'error': str(e)}
    
    async def generate_pr_description(self, changes: str) -> Dict[str, Any]:
        """Generate pull request description using Copilot"""
        logger.info("Generating PR description with Copilot")
        
        try:
            # Use GitHub Copilot CLI for PR description generation
            cmd = [
                'gh', 'copilot', 'pr',
                '--changes', changes
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.config.get('working_directory', './')
            )
            
            stdout, stderr = await process.communicate()
            
            return {
                'changes': changes,
                'pr_description': stdout.decode(),
                'exit_code': process.returncode,
                'timestamp': asyncio.get_event_loop().time()
            }
            
        except Exception as e:
            logger.error(f"PR description generation failed: {e}")
            return {'error': str(e)}
    
    async def review_pr(self, pr_number: int, repo: str = None) -> Dict[str, Any]:
        """Review pull request using Copilot"""
        logger.info(f"Reviewing PR #{pr_number} with Copilot")
        
        try:
            # Use GitHub Copilot CLI for PR review
            cmd = [
                'gh', 'copilot', 'review',
                '--pr', str(pr_number)
            ]
            
            if repo:
                cmd.extend(['--repo', repo])
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.config.get('working_directory', './')
            )
            
            stdout, stderr = await process.communicate()
            
            return {
                'pr_number': pr_number,
                'repo': repo,
                'review': stdout.decode(),
                'exit_code': process.returncode,
                'timestamp': asyncio.get_event_loop().time()
            }
            
        except Exception as e:
            logger.error(f"PR review failed: {e}")
            return {'error': str(e)}
    
    async def generate_commit_message(self, changes: str) -> Dict[str, Any]:
        """Generate commit message using Copilot"""
        logger.info("Generating commit message with Copilot")
        
        try:
            # Use GitHub Copilot CLI for commit message generation
            cmd = [
                'gh', 'copilot', 'commit',
                '--changes', changes
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.config.get('working_directory', './')
            )
            
            stdout, stderr = await process.communicate()
            
            return {
                'changes': changes,
                'commit_message': stdout.decode(),
                'exit_code': process.returncode,
                'timestamp': asyncio.get_event_loop().time()
            }
            
        except Exception as e:
            logger.error(f"Commit message generation failed: {e}")
            return {'error': str(e)}
    
    async def analyze_repository(self, repo_url: str) -> Dict[str, Any]:
        """Analyze repository using Copilot"""
        logger.info(f"Analyzing repository with Copilot: {repo_url}")
        
        try:
            # Use GitHub Copilot CLI for repository analysis
            cmd = [
                'gh', 'copilot', 'analyze',
                '--repo', repo_url
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.config.get('working_directory', './')
            )
            
            stdout, stderr = await process.communicate()
            
            return {
                'repo_url': repo_url,
                'analysis': stdout.decode(),
                'exit_code': process.returncode,
                'timestamp': asyncio.get_event_loop().time()
            }
            
        except Exception as e:
            logger.error(f"Repository analysis failed: {e}")
            return {'error': str(e)}
    
    async def generate_readme(self, project_info: Dict[str, Any]) -> Dict[str, Any]:
        """Generate README for project using Copilot"""
        logger.info("Generating README with Copilot")
        
        try:
            # Convert project info to string
            project_str = json.dumps(project_info, indent=2)
            
            # Use GitHub Copilot CLI for README generation
            cmd = [
                'gh', 'copilot', 'readme',
                '--info', project_str
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.config.get('working_directory', './')
            )
            
            stdout, stderr = await process.communicate()
            
            return {
                'project_info': project_info,
                'readme': stdout.decode(),
                'exit_code': process.returncode,
                'timestamp': asyncio.get_event_loop().time()
            }
            
        except Exception as e:
            logger.error(f"README generation failed: {e}")
            return {'error': str(e)}
    
    async def get_suggestions(self, context: str = None) -> Dict[str, Any]:
        """Get general coding suggestions from Copilot"""
        logger.info("Getting coding suggestions from Copilot")
        
        try:
            # Use GitHub Copilot CLI for general suggestions
            cmd = ['gh', 'copilot', 'suggest']
            
            if context:
                cmd.extend(['--context', context])
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.config.get('working_directory', './')
            )
            
            stdout, stderr = await process.communicate()
            
            return {
                'context': context,
                'suggestions': stdout.decode(),
                'exit_code': process.returncode,
                'timestamp': asyncio.get_event_loop().time()
            }
            
        except Exception as e:
            logger.error(f"Suggestion retrieval failed: {e}")
            return {'error': str(e)}
    
    def get_version(self) -> Dict[str, Any]:
        """Get GitHub Copilot CLI version"""
        if not self.check_availability():
            return {"error": "GitHub Copilot CLI not available"}
        
        try:
            process = subprocess.run(['gh', '--version'], 
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
    
    def install_copilot(self) -> Dict[str, Any]:
        """Install GitHub Copilot CLI"""
        logger.info("Installing GitHub Copilot CLI")
        
        try:
            # Install via GitHub CLI
            process = subprocess.run(['gh', 'extension', 'install', 'github/copilot'], 
                                  capture_output=True, text=True, timeout=60)
            
            if process.returncode == 0:
                logger.info("GitHub Copilot CLI installed successfully")
                return {
                    'success': True,
                    'message': 'GitHub Copilot CLI installed successfully',
                    'timestamp': asyncio.get_event_loop().time()
                }
            else:
                logger.error(f"GitHub Copilot CLI installation failed: {process.stderr}")
                return {
                    'success': False,
                    'error': process.stderr,
                    'timestamp': asyncio.get_event_loop().time()
                }
                
        except Exception as e:
            logger.error(f"GitHub Copilot CLI installation failed: {e}")
            return {
                'success': False,
                'error': str(e),
                'timestamp': asyncio.get_event_loop().time()
            }
    
    def configure_token(self, token: str) -> bool:
        """Configure GitHub token"""
        try:
            # Store token in config
            self.config['token'] = token
            self.token = token
            
            # Set up authentication
            process = subprocess.run(['gh', 'auth', 'login', '--token', token], 
                                  capture_output=True, text=True, timeout=30)
            
            if process.returncode == 0:
                logger.info("GitHub token configured successfully")
                return True
            else:
                logger.error(f"Failed to configure GitHub token: {process.stderr}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to configure GitHub token: {e}")
            return False