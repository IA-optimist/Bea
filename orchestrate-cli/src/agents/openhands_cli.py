"""
OpenHands CLI Integration - Development and testing tools

Features:
- Interactive coding sessions
- Code debugging and analysis
- Automated testing
- Code generation
- Performance profiling
"""

import asyncio
import json
import subprocess
from typing import Dict, Any
from loguru import logger

try:
    import openhands  # noqa: F401
    OPENHANDS_AVAILABLE = True
except ImportError:
    OPENHANDS_AVAILABLE = False

class OpenHandsCLI:
    """OpenHands CLI integration for development tasks"""

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.available = OPENHANDS_AVAILABLE

    def check_availability(self) -> bool:
        """Check if OpenHands CLI is available"""
        if not self.available:
            logger.error("OpenHands CLI not available")
            return False

        try:
            # Check if openhands command is available
            result = subprocess.run(['openhands', '--version'],
                                  capture_output=True, text=True, timeout=10)
            return result.returncode == 0
        except Exception as e:
            logger.error(f"OpenHands CLI check failed: {e}")
            return False

    async def run_interactive_session(self, task: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """Run an interactive coding session"""
        logger.info(f"Starting OpenHands interactive session: {task}")

        if not self.check_availability():
            return {"error": "OpenHands CLI not available"}

        try:
            # Prepare command
            cmd = ['openhands', 'interact', '--task', task]

            # Add context if provided
            if context:
                context_file = '/tmp/openhands_context.json'
                with open(context_file, 'w') as f:
                    json.dump(context, f)
                cmd.extend(['--context', context_file])

            # Run interactive session
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.config.get('working_directory', './')
            )

            stdout, stderr = await process.communicate()

            return {
                'task': task,
                'exit_code': process.returncode,
                'stdout': stdout.decode(),
                'stderr': stderr.decode(),
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"OpenHands interactive session failed: {e}")
            return {'error': str(e)}

    async def run_test_suite(self, test_dir: str = './tests') -> Dict[str, Any]:
        """Run automated tests"""
        logger.info(f"Running OpenHands test suite: {test_dir}")

        if not self.check_availability():
            return {"error": "OpenHands CLI not available"}

        try:
            # Run test suite
            cmd = ['openhands', 'test', '--dir', test_dir]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.config.get('working_directory', './')
            )

            stdout, stderr = await process.communicate()

            return {
                'test_dir': test_dir,
                'exit_code': process.returncode,
                'stdout': stdout.decode(),
                'stderr': stderr.decode(),
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"OpenHands test suite failed: {e}")
            return {'error': str(e)}

    async def debug_code(self, file_path: str, breakpoint_line: int = None) -> Dict[str, Any]:
        """Debug code with breakpoints"""
        logger.info(f"Debugging code: {file_path}")

        if not self.check_availability():
            return {"error": "OpenHands CLI not available"}

        try:
            # Prepare debug command
            cmd = ['openhands', 'debug', '--file', file_path]

            if breakpoint_line:
                cmd.extend(['--break', str(breakpoint_line)])

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.config.get('working_directory', './')
            )

            stdout, stderr = await process.communicate()

            return {
                'file_path': file_path,
                'breakpoint_line': breakpoint_line,
                'exit_code': process.returncode,
                'stdout': stdout.decode(),
                'stderr': stderr.decode(),
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"OpenHands debugging failed: {e}")
            return {'error': str(e)}

    async def generate_code(self, prompt: str, output_file: str) -> Dict[str, Any]:
        """Generate code based on prompt"""
        logger.info(f"Generating code: {prompt}")

        if not self.check_availability():
            return {"error": "OpenHands CLI not available"}

        try:
            # Prepare generation command
            cmd = ['openhands', 'generate', '--prompt', prompt, '--output', output_file]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.config.get('working_directory', './')
            )

            stdout, stderr = await process.communicate()

            return {
                'prompt': prompt,
                'output_file': output_file,
                'exit_code': process.returncode,
                'stdout': stdout.decode(),
                'stderr': stderr.decode(),
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"OpenHands code generation failed: {e}")
            return {'error': str(e)}

    async def profile_code(self, file_path: str) -> Dict[str, Any]:
        """Profile code performance"""
        logger.info(f"Profiling code: {file_path}")

        if not self.check_availability():
            return {"error": "OpenHands CLI not available"}

        try:
            # Prepare profiling command
            cmd = ['openhands', 'profile', '--file', file_path]

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
            logger.error(f"OpenHands profiling failed: {e}")
            return {'error': str(e)}

    def get_version(self) -> Dict[str, Any]:
        """Get OpenHands CLI version"""
        if not self.check_availability():
            return {"error": "OpenHands CLI not available"}

        try:
            process = subprocess.run(['openhands', '--version'],
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

    def install_openhands(self) -> Dict[str, Any]:
        """Install OpenHands CLI"""
        logger.info("Installing OpenHands CLI")

        try:
            # Install via pip
            process = subprocess.run(['pip', 'install', 'openhands'],
                                  capture_output=True, text=True, timeout=60)

            if process.returncode == 0:
                logger.info("OpenHands CLI installed successfully")
                return {
                    'success': True,
                    'message': 'OpenHands CLI installed successfully',
                    'timestamp': asyncio.get_event_loop().time()
                }
            else:
                logger.error(f"OpenHands CLI installation failed: {process.stderr}")
                return {
                    'success': False,
                    'error': process.stderr,
                    'timestamp': asyncio.get_event_loop().time()
                }

        except Exception as e:
            logger.error(f"OpenHands CLI installation failed: {e}")
            return {
                'success': False,
                'error': str(e),
                'timestamp': asyncio.get_event_loop().time()
            }
