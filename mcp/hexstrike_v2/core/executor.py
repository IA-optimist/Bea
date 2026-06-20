"""
Command Executor — Safe command execution with timeout, retry, and error handling
"""
from __future__ import annotations

import logging
import shlex
import subprocess
from dataclasses import dataclass
from typing import Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Result of a command execution"""
    success: bool
    stdout: str
    stderr: str
    exit_code: int
    command: str
    duration_seconds: float
    error: Optional[str] = None


class CommandExecutor:
    """
    Executes shell commands safely with timeout and retry logic.
    
    Usage:
        executor = CommandExecutor()
        result = executor.execute("nmap -sV example.com", timeout=60)
        if result.success:
            print(result.stdout)
    """

    def __init__(
        self,
        default_timeout: int = 300,
        max_retries: int = 3,
        shell: bool = False,
    ):
        self.default_timeout = default_timeout
        self.max_retries = max_retries
        self.shell = shell

    def execute(
        self,
        command: str,
        timeout: Optional[int] = None,
        retry: bool = True,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> ExecutionResult:
        """
        Execute a shell command safely.
        
        Args:
            command: Command to execute
            timeout: Timeout in seconds (None = default)
            retry: Whether to retry on failure
            cwd: Working directory
            env: Environment variables
        
        Returns:
            ExecutionResult with stdout, stderr, exit_code, etc.
        """
        timeout = timeout or self.default_timeout
        max_attempts = self.max_retries if retry else 1

        logger.info(f"Executing: {command[:100]}...")

        for attempt in range(1, max_attempts + 1):
            try:
                import time
                start_time = time.time()

                # Parse command if not using shell
                if not self.shell:
                    cmd_parts = shlex.split(command)
                else:
                    cmd_parts = command

                # Execute
                process = subprocess.run(
                    cmd_parts,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=cwd,
                    env=env,
                    shell=self.shell,
                )

                duration = time.time() - start_time

                result = ExecutionResult(
                    success=(process.returncode == 0),
                    stdout=process.stdout,
                    stderr=process.stderr,
                    exit_code=process.returncode,
                    command=command,
                    duration_seconds=duration,
                )

                if result.success:
                    logger.info(f"Command succeeded (attempt {attempt}/{max_attempts}, {duration:.2f}s)")
                    return result
                else:
                    logger.warning(f"Command failed with exit code {result.exit_code} (attempt {attempt}/{max_attempts})")
                    if attempt < max_attempts:
                        logger.info("Retrying in 2 seconds...")
                        time.sleep(2)
                    else:
                        return result

            except subprocess.TimeoutExpired:
                logger.error(f"Command timed out after {timeout}s (attempt {attempt}/{max_attempts})")
                if attempt >= max_attempts:
                    return ExecutionResult(
                        success=False,
                        stdout="",
                        stderr="",
                        exit_code=-1,
                        command=command,
                        duration_seconds=timeout,
                        error=f"Command timed out after {timeout}s",
                    )

            except Exception as e:
                logger.error(f"Command execution error: {e} (attempt {attempt}/{max_attempts})", exc_info=True)
                if attempt >= max_attempts:
                    return ExecutionResult(
                        success=False,
                        stdout="",
                        stderr=str(e),
                        exit_code=-1,
                        command=command,
                        duration_seconds=0,
                        error=str(e),
                    )

        # Should never reach here
        return ExecutionResult(
            success=False,
            stdout="",
            stderr="",
            exit_code=-1,
            command=command,
            duration_seconds=0,
            error="Unknown error",
        )

    def execute_with_recovery(
        self,
        command: str,
        recovery_commands: list[str] = None,
        **kwargs,
    ) -> ExecutionResult:
        """
        Execute command with recovery commands if it fails.
        
        Args:
            command: Primary command
            recovery_commands: Commands to try if primary fails
            **kwargs: Passed to execute()
        
        Returns:
            ExecutionResult from successful command (or last failure)
        """
        result = self.execute(command, **kwargs)

        if result.success or not recovery_commands:
            return result

        logger.info(f"Primary command failed, trying {len(recovery_commands)} recovery commands...")

        for i, recovery_cmd in enumerate(recovery_commands, 1):
            logger.info(f"Recovery attempt {i}/{len(recovery_commands)}: {recovery_cmd[:100]}...")
            result = self.execute(recovery_cmd, **kwargs)
            if result.success:
                logger.info(f"Recovery successful with command {i}")
                return result

        logger.error("All recovery attempts failed")
        return result


# Global executor instance
executor = CommandExecutor()


def execute_command(command: str, **kwargs) -> ExecutionResult:
    """Convenience function to execute a command using the global executor"""
    return executor.execute(command, **kwargs)
