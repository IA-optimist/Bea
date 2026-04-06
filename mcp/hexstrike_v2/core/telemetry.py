"""
Telemetry — Track tool usage, performance, and errors
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ToolExecution:
    """Record of a tool execution"""
    tool_name: str
    started_at: datetime
    ended_at: Optional[datetime] = None
    success: bool = False
    duration_seconds: float = 0.0
    error: Optional[str] = None


class Telemetry:
    """
    Track tool usage and performance metrics.
    
    Usage:
        telemetry = Telemetry()
        
        # Start tracking
        exec_id = telemetry.start_execution("nmap_scan")
        
        try:
            # ... execute tool ...
            telemetry.end_execution(exec_id, success=True)
        except Exception as e:
            telemetry.end_execution(exec_id, success=False, error=str(e))
        
        # Get stats
        stats = telemetry.get_stats()
    """
    
    def __init__(self):
        self._executions: List[ToolExecution] = []
        self._active_executions: Dict[int, ToolExecution] = {}
        self._next_id = 0
        
        # Counters
        self._tool_counts = defaultdict(int)
        self._tool_errors = defaultdict(int)
        self._tool_durations = defaultdict(list)
    
    def start_execution(self, tool_name: str) -> int:
        """
        Start tracking a tool execution.
        
        Returns:
            Execution ID for later reference
        """
        exec_id = self._next_id
        self._next_id += 1
        
        execution = ToolExecution(
            tool_name=tool_name,
            started_at=datetime.now()
        )
        
        self._active_executions[exec_id] = execution
        self._tool_counts[tool_name] += 1
        
        logger.debug(f"Started tracking execution {exec_id}: {tool_name}")
        
        return exec_id
    
    def end_execution(
        self,
        exec_id: int,
        success: bool = True,
        error: Optional[str] = None
    ) -> None:
        """Mark an execution as completed"""
        if exec_id not in self._active_executions:
            logger.warning(f"Unknown execution ID: {exec_id}")
            return
        
        execution = self._active_executions.pop(exec_id)
        execution.ended_at = datetime.now()
        execution.success = success
        execution.error = error
        execution.duration_seconds = (execution.ended_at - execution.started_at).total_seconds()
        
        self._executions.append(execution)
        self._tool_durations[execution.tool_name].append(execution.duration_seconds)
        
        if not success:
            self._tool_errors[execution.tool_name] += 1
        
        logger.debug(
            f"Ended execution {exec_id}: {execution.tool_name} "
            f"({'success' if success else 'failed'}, {execution.duration_seconds:.2f}s)"
        )
    
    def get_stats(self, tool_name: Optional[str] = None) -> Dict:
        """
        Get telemetry statistics.
        
        Args:
            tool_name: Get stats for specific tool (None = all tools)
        
        Returns:
            Statistics dict
        """
        if tool_name:
            return self._get_tool_stats(tool_name)
        
        # Global stats
        total_executions = len(self._executions)
        total_errors = sum(self._tool_errors.values())
        
        all_durations = [e.duration_seconds for e in self._executions]
        avg_duration = sum(all_durations) / len(all_durations) if all_durations else 0
        
        return {
            "total_executions": total_executions,
            "total_errors": total_errors,
            "error_rate": f"{(total_errors / total_executions * 100) if total_executions > 0 else 0:.1f}%",
            "average_duration": f"{avg_duration:.2f}s",
            "active_executions": len(self._active_executions),
            "tools_used": len(self._tool_counts),
            "top_tools": self._get_top_tools(5),
        }
    
    def _get_tool_stats(self, tool_name: str) -> Dict:
        """Get stats for a specific tool"""
        executions = [e for e in self._executions if e.tool_name == tool_name]
        
        if not executions:
            return {
                "tool_name": tool_name,
                "executions": 0,
            }
        
        durations = [e.duration_seconds for e in executions]
        errors = sum(1 for e in executions if not e.success)
        
        return {
            "tool_name": tool_name,
            "executions": len(executions),
            "errors": errors,
            "error_rate": f"{(errors / len(executions) * 100):.1f}%",
            "average_duration": f"{sum(durations) / len(durations):.2f}s",
            "min_duration": f"{min(durations):.2f}s",
            "max_duration": f"{max(durations):.2f}s",
        }
    
    def _get_top_tools(self, limit: int = 5) -> List[Dict]:
        """Get most-used tools"""
        sorted_tools = sorted(
            self._tool_counts.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        return [
            {
                "tool_name": tool,
                "executions": count,
                "errors": self._tool_errors.get(tool, 0),
            }
            for tool, count in sorted_tools[:limit]
        ]
    
    def clear(self) -> None:
        """Clear all telemetry data"""
        count = len(self._executions)
        self._executions.clear()
        self._active_executions.clear()
        self._tool_counts.clear()
        self._tool_errors.clear()
        self._tool_durations.clear()
        
        logger.info(f"Telemetry cleared ({count} executions removed)")


# Global telemetry instance
telemetry = Telemetry()
