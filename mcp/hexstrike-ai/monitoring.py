"""
HexStrike Monitoring — telemetry + performance + resource tracking.

Extrait depuis hexstrike_server.py pour isoler les 3 composants
autonomes de télémétrie/monitoring. Backward-compat :
`from .monitoring import TelemetryCollector, ResourceMonitor, PerformanceMonitor`.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import psutil

logger = logging.getLogger("hexstrike_server")


class PerformanceMonitor:
    """Advanced performance monitoring with automatic resource allocation"""

    def __init__(self):
        self.performance_metrics = {}
        self.resource_thresholds = {
            "cpu_high": 80.0,
            "memory_high": 85.0,
            "disk_high": 90.0,
            "network_high": 80.0
        }

        self.optimization_rules = {
            "high_cpu": {
                "reduce_threads": 0.5,
                "increase_delay": 2.0,
                "enable_nice": True
            },
            "high_memory": {
                "reduce_batch_size": 0.6,
                "enable_streaming": True,
                "clear_cache": True
            },
            "high_disk": {
                "reduce_output_verbosity": True,
                "enable_compression": True,
                "cleanup_temp_files": True
            },
            "high_network": {
                "reduce_concurrent_connections": 0.7,
                "increase_timeout": 1.5,
                "enable_connection_pooling": True
            }
        }

    def monitor_system_resources(self) -> Dict[str, float]:
        """Monitor current system resource usage"""
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            network = psutil.net_io_counters()

            return {
                "cpu_percent": cpu_percent,
                "memory_percent": memory.percent,
                "disk_percent": disk.percent,
                "network_bytes_sent": network.bytes_sent,
                "network_bytes_recv": network.bytes_recv,
                "timestamp": time.time()
            }
        except Exception as e:
            logger.error(f"Error monitoring system resources: {str(e)}")
            return {}

    def optimize_based_on_resources(self, current_params: Dict[str, Any], resource_usage: Dict[str, float]) -> Dict[str, Any]:
        """Optimize parameters based on current resource usage"""
        optimized_params = current_params.copy()
        optimizations_applied = []

        # CPU optimization
        if resource_usage.get("cpu_percent", 0) > self.resource_thresholds["cpu_high"]:
            if "threads" in optimized_params:
                original_threads = optimized_params["threads"]
                optimized_params["threads"] = max(1, int(original_threads * self.optimization_rules["high_cpu"]["reduce_threads"]))
                optimizations_applied.append(f"Reduced threads from {original_threads} to {optimized_params['threads']}")

            if "delay" in optimized_params:
                original_delay = optimized_params.get("delay", 0)
                optimized_params["delay"] = original_delay * self.optimization_rules["high_cpu"]["increase_delay"]
                optimizations_applied.append(f"Increased delay to {optimized_params['delay']}")

        # Memory optimization
        if resource_usage.get("memory_percent", 0) > self.resource_thresholds["memory_high"]:
            if "batch_size" in optimized_params:
                original_batch = optimized_params["batch_size"]
                optimized_params["batch_size"] = max(1, int(original_batch * self.optimization_rules["high_memory"]["reduce_batch_size"]))
                optimizations_applied.append(f"Reduced batch size from {original_batch} to {optimized_params['batch_size']}")

        # Network optimization
        if "network_bytes_sent" in resource_usage:
            # Simple heuristic for high network usage
            if resource_usage["network_bytes_sent"] > 1000000:  # 1MB/s
                if "concurrent_connections" in optimized_params:
                    original_conn = optimized_params["concurrent_connections"]
                    optimized_params["concurrent_connections"] = max(1, int(original_conn * self.optimization_rules["high_network"]["reduce_concurrent_connections"]))
                    optimizations_applied.append(f"Reduced concurrent connections to {optimized_params['concurrent_connections']}")

        optimized_params["_optimizations_applied"] = optimizations_applied
        return optimized_params


class ResourceMonitor:
    """Advanced resource monitoring with historical tracking"""

    def __init__(self, history_size=100):
        self.history_size = history_size
        self.usage_history = []
        self.history_lock = threading.Lock()

    def get_current_usage(self) -> Dict[str, float]:
        """Get current system resource usage"""
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            network = psutil.net_io_counters()

            usage = {
                "cpu_percent": cpu_percent,
                "memory_percent": memory.percent,
                "memory_available_gb": memory.available / (1024**3),
                "disk_percent": disk.percent,
                "disk_free_gb": disk.free / (1024**3),
                "network_bytes_sent": network.bytes_sent,
                "network_bytes_recv": network.bytes_recv,
                "timestamp": time.time()
            }

            # Add to history
            with self.history_lock:
                self.usage_history.append(usage)
                if len(self.usage_history) > self.history_size:
                    self.usage_history.pop(0)

            return usage

        except Exception as e:
            logger.error(f"💥 Error getting resource usage: {str(e)}")
            return {
                "cpu_percent": 0,
                "memory_percent": 0,
                "memory_available_gb": 0,
                "disk_percent": 0,
                "disk_free_gb": 0,
                "network_bytes_sent": 0,
                "network_bytes_recv": 0,
                "timestamp": time.time()
            }

    def get_process_usage(self, pid: int) -> Dict[str, Any]:
        """Get resource usage for specific process"""
        try:
            process = psutil.Process(pid)
            return {
                "cpu_percent": process.cpu_percent(),
                "memory_percent": process.memory_percent(),
                "memory_rss_mb": process.memory_info().rss / (1024**2),
                "num_threads": process.num_threads(),
                "status": process.status()
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return {}

    def get_usage_trends(self) -> Dict[str, Any]:
        """Get resource usage trends"""
        with self.history_lock:
            if len(self.usage_history) < 2:
                return {}

            recent = self.usage_history[-10:]  # Last 10 measurements

            cpu_trend = sum(u["cpu_percent"] for u in recent) / len(recent)
            memory_trend = sum(u["memory_percent"] for u in recent) / len(recent)

            return {
                "cpu_avg_10": cpu_trend,
                "memory_avg_10": memory_trend,
                "measurements": len(self.usage_history),
                "trend_period_minutes": len(recent) * 15 / 60  # 15 second intervals
            }


class TelemetryCollector:
    """Collect and manage system telemetry"""

    def __init__(self):
        self.stats = {
            "commands_executed": 0,
            "successful_commands": 0,
            "failed_commands": 0,
            "total_execution_time": 0.0,
            "start_time": time.time()
        }

    def record_execution(self, success: bool, execution_time: float):
        """Record command execution statistics"""
        self.stats["commands_executed"] += 1
        if success:
            self.stats["successful_commands"] += 1
        else:
            self.stats["failed_commands"] += 1
        self.stats["total_execution_time"] += execution_time

    def get_system_metrics(self) -> Dict[str, Any]:
        """Get current system metrics"""
        return {
            "cpu_percent": psutil.cpu_percent(interval=1),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_usage": psutil.disk_usage('/').percent,
            "network_io": psutil.net_io_counters()._asdict() if psutil.net_io_counters() else {}
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get telemetry statistics"""
        uptime = time.time() - self.stats["start_time"]
        success_rate = (self.stats["successful_commands"] / self.stats["commands_executed"] * 100) if self.stats["commands_executed"] > 0 else 0
        avg_execution_time = (self.stats["total_execution_time"] / self.stats["commands_executed"]) if self.stats["commands_executed"] > 0 else 0

        return {
            "uptime_seconds": uptime,
            "commands_executed": self.stats["commands_executed"],
            "success_rate": f"{success_rate:.1f}%",
            "average_execution_time": f"{avg_execution_time:.2f}s",
            "system_metrics": self.get_system_metrics()
        }

# Global telemetry collector
telemetry = TelemetryCollector()


__all__ = ["TelemetryCollector", "ResourceMonitor", "PerformanceMonitor"]
