"""
Cursor CLI Integration - AI-powered code review and assistance

Features:
- Intelligent code review with AI suggestions
- Code refactoring assistance
- Bug detection and fixing
- Performance optimization
- Security analysis
- Best practice recommendations
"""

import asyncio
import json
import subprocess
from typing import Dict, List, Any, Optional
from loguru import logger

try:
    import requests
    import pydantic
    from cursor import Cursor
    CURSOR_AVAILABLE = True
except ImportError:
    CURSOR_AVAILABLE = False

class CursorCLI:
    """Cursor CLI integration for AI-powered code review and assistance"""
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.available = CURSOR_AVAILABLE
        self.api_key = self.config.get('api_key') or self._get_api_key()
        self.base_url = self.config.get('base_url', 'https://api.cursor.sh')
        
    def _get_api_key(self) -> Optional[str]:
        """Get Cursor API key from environment or config"""
        import os
        return os.getenv('CURSOR_API_KEY') or self.config.get('api_key')
    
    def check_availability(self) -> bool:
        """Check if Cursor CLI is available"""
        if not self.available:
            logger.error("Cursor CLI not available")
            return False
        
        if not self.api_key:
            logger.error("Cursor API key not configured")
            return False
        
        try:
            # Check if cursor command is available
            result = subprocess.run(['cursor', '--version'], 
                                  capture_output=True, text=True, timeout=10)
            return result.returncode == 0
        except Exception as e:
            logger.error(f"Cursor CLI check failed: {e}")
            return False
    
    async def review_code(self, file_path: str, review_type: str = 'standard') -> Dict[str, Any]:
        """Review code using Cursor AI"""
        logger.info(f"Starting code review for: {file_path}")
        
        if not self.check_availability():
            return {"error": "Cursor CLI not available"}
        
        try:
            # Prepare review command
            cmd = [
                'cursor', 'review',
                '--file', file_path,
                '--type', review_type,
                '--api-key', self.api_key
            ]
            
            if self.config.get('verbose', False):
                cmd.append('--verbose')
            
            if self.config.get('include_suggestions', True):
                cmd.append('--suggestions')
            
            if self.config.get('include_security', True):
                cmd.append('--security')
            
            if self.config.get('include_performance', True):
                cmd.append('--performance')
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.config.get('working_directory', './')
            )
            
            stdout, stderr = await process.communicate()
            
            return {
                'file_path': file_path,
                'review_type': review_type,
                'exit_code': process.returncode,
                'stdout': stdout.decode(),
                'stderr': stderr.decode(),
                'timestamp': asyncio.get_event_loop().time()
            }
            
        except Exception as e:
            logger.error(f"Code review failed: {e}")
            return {'error': str(e)}
    
    async def review_multiple_files(self, file_paths: List[str], review_type: str = 'standard') -> Dict[str, Any]:
        """Review multiple files using Cursor AI"""
        logger.info(f"Starting code review for {len(file_paths)} files")
        
        if not self.check_availability():
            return {"error": "Cursor CLI not available"}
        
        try:
            # Prepare review command for multiple files
            cmd = [
                'cursor', 'review',
                '--files', ','.join(file_paths),
                '--type', review_type,
                '--api-key', self.api_key,
                '--batch'
            ]
            
            if self.config.get('verbose', False):
                cmd.append('--verbose')
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.config.get('working_directory', './')
            )
            
            stdout, stderr = await process.communicate()
            
            return {
                'file_paths': file_paths,
                'review_type': review_type,
                'exit_code': process.returncode,
                'stdout': stdout.decode(),
                'stderr': stderr.decode(),
                'timestamp': asyncio.get_event_loop().time()
            }
            
        except Exception as e:
            logger.error(f"Multiple file review failed: {e}")
            return {'error': str(e)}
    
    async def suggest_improvements(self, file_path: str) -> Dict[str, Any]:
        """Suggest code improvements"""
        logger.info(f"Generating suggestions for: {file_path}")
        
        if not self.check_availability():
            return {"error": "Cursor CLI not available"}
        
        try:
            # Prepare suggestions command
            cmd = [
                'cursor', 'suggest',
                '--file', file_path,
                '--api-key', self.api_key,
                '--comprehensive'
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.config.get('working_directory', './')
            )
            
            stdout, stderr = await process.communicate()
            
            return {
                'file_path': file_path,
                'exit_code': process.returncode,
                'stdout': stdout.decode(),
                'stderr': stderr.decode(),
                'timestamp': asyncio.get_event_loop().time()
            }
            
        except Exception as e:
            logger.error(f"Suggestions generation failed: {e}")
            return {'error': str(e)}
    
    async def refactor_code(self, file_path: str, refactoring_type: str) -> Dict[str, Any]:
        """Refactor code using Cursor AI"""
        logger.info(f"Refactoring {file_path} with type: {refactoring_type}")
        
        if not self.check_availability():
            return {"error": "Cursor CLI not available"}
        
        try:
            # Prepare refactoring command
            cmd = [
                'cursor', 'refactor',
                '--file', file_path,
                '--type', refactoring_type,
                '--api-key', self.api_key
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.config.get('working_directory', './')
            )
            
            stdout, stderr = await process.communicate()
            
            return {
                'file_path': file_path,
                'refactoring_type': refactoring_type,
                'exit_code': process.returncode,
                'stdout': stdout.decode(),
                'stderr': stderr.decode(),
                'timestamp': asyncio.get_event_loop().time()
            }
            
        except Exception as e:
            logger.error(f"Code refactoring failed: {e}")
            return {'error': str(e)}
    
    async def detect_bugs(self, file_path: str) -> Dict[str, Any]:
        """Detect bugs in code"""
        logger.info(f"Detecting bugs in: {file_path}")
        
        if not self.check_availability():
            return {"error": "Cursor CLI not available"}
        
        try:
            # Prepare bug detection command
            cmd = [
                'cursor', 'bugs',
                '--file', file_path,
                '--api-key', self.api_key,
                '--severity', 'all'
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.config.get('working_directory', './')
            )
            
            stdout, stderr = await process.communicate()
            
            return {
                'file_path': file_path,
                'exit_code': process.returncode,
                'stdout': stdout.decode(),
                'stderr': stderr.decode(),
                'timestamp': asyncio.get_event_loop().time()
            }
            
        except Exception as e:
            logger.error(f"Bug detection failed: {e}")
            return {'error': str(e)}
    
    async def optimize_performance(self, file_path: str) -> Dict[str, Any]:
        """Optimize code performance"""
        logger.info(f"Optimizing performance for: {file_path}")
        
        if not self.check_availability():
            return {"error": "Cursor CLI not available"}
        
        try:
            # Prepare performance optimization command
            cmd = [
                'cursor', 'optimize',
                '--file', file_path,
                '--api-key', self.api_key,
                '--focus', 'performance'
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.config.get('working_directory', './')
            )
            
            stdout, stderr = await process.communicate()
            
            return {
                'file_path': file_path,
                'optimization_type': 'performance',
                'exit_code': process.returncode,
                'stdout': stdout.decode(),
                'stderr': stderr.decode(),
                'timestamp': asyncio.get_event_loop().time()
            }
            
        except Exception as e:
            logger.error(f"Performance optimization failed: {e}")
            return {'error': str(e)}
    
    async def analyze_security(self, file_path: str) -> Dict[str, Any]:
        """Analyze code for security issues"""
        logger.info(f"Analyzing security for: {file_path}")
        
        if not self.check_availability():
            return {"error": "Cursor CLI not available"}
        
        try:
            # Prepare security analysis command
            cmd = [
                'cursor', 'security',
                '--file', file_path,
                '--api-key', self.api_key,
                '--severity', 'high,medium,low'
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.config.get('working_directory', './')
            )
            
            stdout, stderr = await process.communicate()
            
            return {
                'file_path': file_path,
                'analysis_type': 'security',
                'exit_code': process.returncode,
                'stdout': stdout.decode(),
                'stderr': stderr.decode(),
                'timestamp': asyncio.get_event_loop().time()
            }
            
        except Exception as e:
            logger.error(f"Security analysis failed: {e}")
            return {'error': str(e)}
    
    async def generate_documentation(self, file_path: str) -> Dict[str, Any]:
        """Generate documentation for code"""
        logger.info(f"Generating documentation for: {file_path}")
        
        if not self.check_availability():
            return {"error": "Cursor CLI not available"}
        
        try:
            # Prepare documentation generation command
            cmd = [
                'cursor', 'docs',
                '--file', file_path,
                '--api-key', self.api_key,
                '--format', 'markdown'
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.config.get('working_directory', './')
            )
            
            stdout, stderr = await process.communicate()
            
            return {
                'file_path': file_path,
                'documentation_type': 'markdown',
                'exit_code': process.returncode,
                'stdout': stdout.decode(),
                'stderr': stderr.decode(),
                'timestamp': asyncio.get_event_loop().time()
            }
            
        except Exception as e:
            logger.error(f"Documentation generation failed: {e}")
            return {'error': str(e)}
    
    async def create_pull_request_review(self, repo_url: str, pr_number: int) -> Dict[str, Any]:
        """Review a pull request using Cursor AI"""
        logger.info(f"Reviewing PR #{pr_number} for: {repo_url}")
        
        if not self.check_availability():
            return {"error": "Cursor CLI not available"}
        
        try:
            # Prepare PR review command
            cmd = [
                'cursor', 'pr-review',
                '--repo', repo_url,
                '--pr', str(pr_number),
                '--api-key', self.api_key,
                '--comprehensive'
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
                'pr_number': pr_number,
                'exit_code': process.returncode,
                'stdout': stdout.decode(),
                'stderr': stderr.decode(),
                'timestamp': asyncio.get_event_loop().time()
            }
            
        except Exception as e:
            logger.error(f"PR review failed: {e}")
            return {'error': str(e)}
    
    async def run_comprehensive_analysis(self, file_path: str) -> Dict[str, Any]:
        """Run comprehensive code analysis"""
        logger.info(f"Running comprehensive analysis for: {file_path}")
        
        if not self.check_availability():
            return {"error": "Cursor CLI not available"}
        
        try:
            # Run all analysis types
            results = {}
            
            # Code review
            results['review'] = await self.review_code(file_path, 'comprehensive')
            
            # Bug detection
            results['bugs'] = await self.detect_bugs(file_path)
            
            # Security analysis
            results['security'] = await self.analyze_security(file_path)
            
            # Performance optimization
            results['performance'] = await self.optimize_performance(file_path)
            
            # Suggestions
            results['suggestions'] = await self.suggest_improvements(file_path)
            
            # Documentation
            results['documentation'] = await self.generate_documentation(file_path)
            
            return {
                'file_path': file_path,
                'analysis_type': 'comprehensive',
                'results': results,
                'timestamp': asyncio.get_event_loop().time()
            }
            
        except Exception as e:
            logger.error(f"Comprehensive analysis failed: {e}")
            return {'error': str(e)}
    
    def get_version(self) -> Dict[str, Any]:
        """Get Cursor CLI version"""
        if not self.check_availability():
            return {"error": "Cursor CLI not available"}
        
        try:
            process = subprocess.run(['cursor', '--version'], 
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
    
    def install_cursor(self) -> Dict[str, Any]:
        """Install Cursor CLI"""
        logger.info("Installing Cursor CLI")
        
        try:
            # Install via curl
            process = subprocess.run([
                'curl', '-fsSL', 'https://downloads.cursor.sh/linux/x64', 
                '|', 'bash'
            ], capture_output=True, text=True, timeout=60)
            
            if process.returncode == 0:
                logger.info("Cursor CLI installed successfully")
                return {
                    'success': True,
                    'message': 'Cursor CLI installed successfully',
                    'timestamp': asyncio.get_event_loop().time()
                }
            else:
                logger.error(f"Cursor CLI installation failed: {process.stderr}")
                return {
                    'success': False,
                    'error': process.stderr,
                    'timestamp': asyncio.get_event_loop().time()
                }
                
        except Exception as e:
            logger.error(f"Cursor CLI installation failed: {e}")
            return {
                'success': False,
                'error': str(e),
                'timestamp': asyncio.get_event_loop().time()
            }
    
    def configure_api_key(self, api_key: str) -> bool:
        """Configure Cursor API key"""
        try:
            # Store API key in config
            self.config['api_key'] = api_key
            self.api_key = api_key
            
            # Set up authentication
            process = subprocess.run(['cursor', 'auth', 'login', api_key], 
                                  capture_output=True, text=True, timeout=30)
            
            if process.returncode == 0:
                logger.info("Cursor API key configured successfully")
                return True
            else:
                logger.error(f"Failed to configure Cursor API key: {process.stderr}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to configure Cursor API key: {e}")
            return False