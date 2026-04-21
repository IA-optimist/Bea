"""
HexStrike Execution Framework — centralized command execution with recovery.

Extrait depuis hexstrike_server.py (Phase M). Fonctions utilitaires pures
qui encapsulent l'exécution de commandes shell avec :
  - Intelligent error handling (via IntelligentErrorHandler)
  - Graceful degradation (via GracefulDegradation)
  - Operation type detection (recon / scan / exploit / ...)
  - Command rebuild with optimized parameters

Ces helpers sont appelés par 150+ tool endpoints dans hexstrike_server.py.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict

from error_handling import IntelligentErrorHandler, GracefulDegradation

logger = logging.getLogger("hexstrike_server")

# Singleton managers — réutilisés par les 150+ endpoints tool.
error_handler = IntelligentErrorHandler()
degradation_manager = GracefulDegradation()


def execute_command(command: str, use_cache: bool = True) -> Dict[str, Any]:
    """
    Execute a shell command with enhanced features

    Args:
        command: The command to execute
        use_cache: Whether to use caching for this command

    Returns:
        A dictionary containing the stdout, stderr, return code, and metadata
    """

    # Kill switch — opt-in explicite pour exécution shell (RCE par design).
    if os.environ.get("HEXSTRIKE_EXEC_ENABLED", "0") != "1":
        return {
            "success": False,
            "status": "refused",
            "error": "HEXSTRIKE_EXEC_ENABLED!=1, exécution shell désactivée",
            "command": command[:120],
        }

    # Check cache first
    if use_cache:
        cached_result = cache.get(command, {})
        if cached_result:
            return cached_result

    # Execute command
    executor = EnhancedCommandExecutor(command)
    result = executor.execute()

    # Cache successful results
    if use_cache and result.get("success", False):
        cache.set(command, {}, result)

    return result


def execute_command_with_recovery(tool_name: str, command: str, parameters: Dict[str, Any] = None,
                                 use_cache: bool = True, max_attempts: int = 3) -> Dict[str, Any]:
    """
    Execute a command with intelligent error handling and recovery

    Args:
        tool_name: Name of the tool being executed
        command: The command to execute
        parameters: Tool parameters for context
        use_cache: Whether to use caching
        max_attempts: Maximum number of recovery attempts

    Returns:
        A dictionary containing execution results with recovery information
    """
    if parameters is None:
        parameters = {}

    attempt_count = 0
    last_error = None
    recovery_history = []

    while attempt_count < max_attempts:
        attempt_count += 1

        try:
            # Execute the command
            result = execute_command(command, use_cache)

            # Check if execution was successful
            if result.get("success", False):
                # Add recovery information to successful result
                result["recovery_info"] = {
                    "attempts_made": attempt_count,
                    "recovery_applied": len(recovery_history) > 0,
                    "recovery_history": recovery_history
                }
                return result

            # Command failed, determine if we should attempt recovery
            error_message = result.get("stderr", "Unknown error")
            exception = Exception(error_message)

            # Create context for error handler
            context = {
                "target": parameters.get("target", "unknown"),
                "parameters": parameters,
                "attempt_count": attempt_count,
                "command": command
            }

            # Get recovery strategy from error handler
            recovery_strategy = error_handler.handle_tool_failure(tool_name, exception, context)
            recovery_history.append({
                "attempt": attempt_count,
                "error": error_message,
                "recovery_action": recovery_strategy.action.value,
                "timestamp": datetime.now().isoformat()
            })

            # Apply recovery strategy
            if recovery_strategy.action == RecoveryAction.RETRY_WITH_BACKOFF:
                delay = recovery_strategy.parameters.get("initial_delay", 5)
                backoff = recovery_strategy.parameters.get("max_delay", 60)
                actual_delay = min(delay * (recovery_strategy.backoff_multiplier ** (attempt_count - 1)), backoff)

                retry_info = f'Retrying in {actual_delay}s (attempt {attempt_count}/{max_attempts})'
                logger.info(f"{ModernVisualEngine.format_tool_status(tool_name, 'RECOVERY', retry_info)}")
                time.sleep(actual_delay)
                continue

            elif recovery_strategy.action == RecoveryAction.RETRY_WITH_REDUCED_SCOPE:
                # Adjust parameters to reduce scope
                adjusted_params = error_handler.auto_adjust_parameters(
                    tool_name,
                    error_handler.classify_error(error_message, exception),
                    parameters
                )

                # Rebuild command with adjusted parameters
                command = _rebuild_command_with_params(tool_name, command, adjusted_params)
                logger.info(f"🔧 Retrying {tool_name} with reduced scope")
                continue

            elif recovery_strategy.action == RecoveryAction.SWITCH_TO_ALTERNATIVE_TOOL:
                # Get alternative tool
                alternative_tool = error_handler.get_alternative_tool(tool_name, recovery_strategy.parameters)

                if alternative_tool:
                    switch_info = f'Switching to alternative: {alternative_tool}'
                    logger.info(f"{ModernVisualEngine.format_tool_status(tool_name, 'RECOVERY', switch_info)}")
                    # This would require the calling function to handle tool switching
                    result["alternative_tool_suggested"] = alternative_tool
                    result["recovery_info"] = {
                        "attempts_made": attempt_count,
                        "recovery_applied": True,
                        "recovery_history": recovery_history,
                        "final_action": "tool_switch_suggested"
                    }
                    return result
                else:
                    logger.warning(f"⚠️  No alternative tool found for {tool_name}")

            elif recovery_strategy.action == RecoveryAction.ADJUST_PARAMETERS:
                # Adjust parameters based on error type
                error_type = error_handler.classify_error(error_message, exception)
                adjusted_params = error_handler.auto_adjust_parameters(tool_name, error_type, parameters)

                # Rebuild command with adjusted parameters
                command = _rebuild_command_with_params(tool_name, command, adjusted_params)
                logger.info(f"🔧 Retrying {tool_name} with adjusted parameters")
                continue

            elif recovery_strategy.action == RecoveryAction.ESCALATE_TO_HUMAN:
                # Create error context for escalation
                error_context = ErrorContext(
                    tool_name=tool_name,
                    target=parameters.get("target", "unknown"),
                    parameters=parameters,
                    error_type=error_handler.classify_error(error_message, exception),
                    error_message=error_message,
                    attempt_count=attempt_count,
                    timestamp=datetime.now(),
                    stack_trace="",
                    system_resources=error_handler._get_system_resources()
                )

                escalation_data = error_handler.escalate_to_human(
                    error_context,
                    recovery_strategy.parameters.get("urgency", "medium")
                )

                result["human_escalation"] = escalation_data
                result["recovery_info"] = {
                    "attempts_made": attempt_count,
                    "recovery_applied": True,
                    "recovery_history": recovery_history,
                    "final_action": "human_escalation"
                }
                return result

            elif recovery_strategy.action == RecoveryAction.GRACEFUL_DEGRADATION:
                # Apply graceful degradation
                operation = _determine_operation_type(tool_name)
                degraded_result = degradation_manager.handle_partial_failure(
                    operation,
                    result,
                    [tool_name]
                )

                degraded_result["recovery_info"] = {
                    "attempts_made": attempt_count,
                    "recovery_applied": True,
                    "recovery_history": recovery_history,
                    "final_action": "graceful_degradation"
                }
                return degraded_result

            elif recovery_strategy.action == RecoveryAction.ABORT_OPERATION:
                logger.error(f"🛑 Aborting {tool_name} operation after {attempt_count} attempts")
                result["recovery_info"] = {
                    "attempts_made": attempt_count,
                    "recovery_applied": True,
                    "recovery_history": recovery_history,
                    "final_action": "operation_aborted"
                }
                return result

            last_error = exception

        except Exception as e:
            last_error = e
            logger.error(f"💥 Unexpected error in recovery attempt {attempt_count}: {str(e)}")

            # If this is the last attempt, escalate to human
            if attempt_count >= max_attempts:
                error_context = ErrorContext(
                    tool_name=tool_name,
                    target=parameters.get("target", "unknown"),
                    parameters=parameters,
                    error_type=ErrorType.UNKNOWN,
                    error_message=str(e),
                    attempt_count=attempt_count,
                    timestamp=datetime.now(),
                    stack_trace=traceback.format_exc(),
                    system_resources=error_handler._get_system_resources()
                )

                escalation_data = error_handler.escalate_to_human(error_context, "high")

                return {
                    "success": False,
                    "error": str(e),
                    "human_escalation": escalation_data,
                    "recovery_info": {
                        "attempts_made": attempt_count,
                        "recovery_applied": True,
                        "recovery_history": recovery_history,
                        "final_action": "human_escalation_after_failure"
                    }
                }

    # All attempts exhausted
    logger.error(f"🚫 All recovery attempts exhausted for {tool_name}")
    return {
        "success": False,
        "error": f"All recovery attempts exhausted: {str(last_error)}",
        "recovery_info": {
            "attempts_made": attempt_count,
            "recovery_applied": True,
            "recovery_history": recovery_history,
            "final_action": "all_attempts_exhausted"
        }
    }


def _rebuild_command_with_params(tool_name: str, original_command: str, new_params: Dict[str, Any]) -> str:
    """Rebuild command with new parameters"""
    # This is a simplified implementation - in practice, you'd need tool-specific logic
    # For now, we'll just append new parameters
    additional_args = []

    for key, value in new_params.items():
        if key == "timeout" and tool_name in ["nmap", "gobuster", "nuclei"]:
            additional_args.append(f"--timeout {value}")
        elif key == "threads" and tool_name in ["gobuster", "feroxbuster", "ffuf"]:
            additional_args.append(f"-t {value}")
        elif key == "delay" and tool_name in ["gobuster", "feroxbuster"]:
            additional_args.append(f"--delay {value}")
        elif key == "timing" and tool_name == "nmap":
            additional_args.append(f"{value}")
        elif key == "concurrency" and tool_name == "nuclei":
            additional_args.append(f"-c {value}")
        elif key == "rate-limit" and tool_name == "nuclei":
            additional_args.append(f"-rl {value}")

    if additional_args:
        return f"{original_command} {' '.join(additional_args)}"

    return original_command


def _determine_operation_type(tool_name: str) -> str:
    """Determine operation type based on tool name"""
    operation_mapping = {
        "nmap": "network_discovery",
        "rustscan": "network_discovery",
        "masscan": "network_discovery",
        "gobuster": "web_discovery",
        "feroxbuster": "web_discovery",
        "dirsearch": "web_discovery",
        "ffuf": "web_discovery",
        "nuclei": "vulnerability_scanning",
        "jaeles": "vulnerability_scanning",
        "nikto": "vulnerability_scanning",
        "subfinder": "subdomain_enumeration",
        "amass": "subdomain_enumeration",
        "assetfinder": "subdomain_enumeration",
        "arjun": "parameter_discovery",
        "paramspider": "parameter_discovery",
        "x8": "parameter_discovery"
    }

    return operation_mapping.get(tool_name, "unknown_operation")


__all__ = [
    "execute_command", "execute_command_with_recovery",
    "_rebuild_command_with_params", "_determine_operation_type",
    "error_handler", "degradation_manager",
]
