"""
Process Manager — Manage background processes and long-running scans
"""
from __future__ import annotations

import logging
import os
import psutil
import shlex
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class ProcessStatus(Enum):
    """Status of a managed process"""
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    KILLED = "killed"


@dataclass
class ManagedProcess:
    """A process managed by ProcessManager"""
    pid: int
    command: str
    started_at: datetime
    status: ProcessStatus = ProcessStatus.RUNNING
    exit_code: Optional[int] = None
    stdout: List[str] = field(default_factory=list)
    stderr: List[str] = field(default_factory=list)
    timeout_seconds: Optional[int] = None
    
    def to_dict(self) -> Dict:
        """Serialize to dict"""
        return {
            "pid": self.pid,
            "command": self.command,
            "started_at": self.started_at.isoformat(),
            "status": self.status.value,
            "exit_code": self.exit_code,
            "runtime_seconds": (datetime.now() - self.started_at).total_seconds(),
            "stdout_lines": len(self.stdout),
            "stderr_lines": len(self.stderr),
        }


class ProcessManager:
    """
    Manage background processes for long-running scans.
    
    Usage:
        manager = ProcessManager()
        
        # Start background process
        process_id = manager.start(
            command="nmap -sV -p- example.com",
            timeout=3600
        )
        
        # Check status
        info = manager.get_info(process_id)
        if info["status"] == "completed":
            output = manager.get_output(process_id)
        
        # Kill if needed
        manager.kill(process_id)
    """
    
    def __init__(self):
        self._processes: Dict[int, ManagedProcess] = {}
        self._lock = threading.Lock()
        self._monitor_thread = None
        self._shutdown_event = threading.Event()
        
        # Start monitor thread
        self._start_monitor()
    
    def start(
        self,
        command: str,
        timeout: Optional[int] = None,
        capture_output: bool = True,
    ) -> int:
        """
        Start a background process.
        
        Args:
            command: Command to execute
            timeout: Timeout in seconds (None = no timeout)
            capture_output: Whether to capture stdout/stderr
        
        Returns:
            Process ID (PID)
        """
        logger.info(f"Starting process: {command[:100]}...")

        # Kill switch — hexstrike_v2 exécute des commandes arbitraires, opt-in requis.
        if os.environ.get("HEXSTRIKE_EXEC_ENABLED", "0") != "1":
            raise PermissionError(
                "HEXSTRIKE_EXEC_ENABLED!=1, exécution shell désactivée"
            )

        try:
            # Start process without shell expansion to reduce command injection risk
            argv = shlex.split(command, posix=True)
            if not argv:
                raise ValueError("Command vide")

            process = subprocess.Popen(
                argv,
                shell=False,
                stdout=subprocess.PIPE if capture_output else None,
                stderr=subprocess.PIPE if capture_output else None,
                text=True,
            )
            
            managed = ManagedProcess(
                pid=process.pid,
                command=command,
                started_at=datetime.now(),
                timeout_seconds=timeout,
            )
            
            with self._lock:
                self._processes[process.pid] = managed
            
            logger.info(f"Process started: PID={process.pid}")
            
            # Start output capture thread if needed
            if capture_output:
                threading.Thread(
                    target=self._capture_output,
                    args=(process, managed),
                    daemon=True
                ).start()
            
            return process.pid
        
        except Exception as e:
            logger.error(f"Failed to start process: {e}", exc_info=True)
            raise
    
    def _capture_output(self, process: subprocess.Popen, managed: ManagedProcess):
        """Capture stdout/stderr from process"""
        try:
            while True:
                stdout_line = process.stdout.readline() if process.stdout else None
                stderr_line = process.stderr.readline() if process.stderr else None
                
                if stdout_line:
                    managed.stdout.append(stdout_line.strip())
                
                if stderr_line:
                    managed.stderr.append(stderr_line.strip())
                
                # Check if process finished
                if process.poll() is not None:
                    # Read remaining output
                    if process.stdout:
                        managed.stdout.extend([line.strip() for line in process.stdout.readlines()])
                    if process.stderr:
                        managed.stderr.extend([line.strip() for line in process.stderr.readlines()])
                    
                    managed.exit_code = process.returncode
                    managed.status = ProcessStatus.COMPLETED if process.returncode == 0 else ProcessStatus.FAILED
                    break
                
                time.sleep(0.1)
        
        except Exception as e:
            logger.error(f"Error capturing output for PID={managed.pid}: {e}")
            managed.status = ProcessStatus.FAILED
    
    def _start_monitor(self):
        """Start background monitoring thread"""
        def monitor():
            while not self._shutdown_event.is_set():
                self._check_processes()
                time.sleep(5)  # Check every 5 seconds
        
        self._monitor_thread = threading.Thread(target=monitor, daemon=True)
        self._monitor_thread.start()
        logger.info("Process monitor started")
    
    def _check_processes(self):
        """Check all managed processes for timeout/completion"""
        with self._lock:
            for pid, managed in list(self._processes.items()):
                if managed.status != ProcessStatus.RUNNING:
                    continue
                
                # Check if process still exists
                try:
                    psutil.Process(pid)
                    
                    # Check timeout
                    if managed.timeout_seconds:
                        runtime = (datetime.now() - managed.started_at).total_seconds()
                        if runtime > managed.timeout_seconds:
                            logger.warning(f"Process timeout: PID={pid} ({runtime:.1f}s)")
                            self._kill_process(pid, managed, ProcessStatus.TIMEOUT)
                
                except psutil.NoSuchProcess:
                    # Process died
                    logger.info(f"Process completed: PID={pid}")
                    managed.status = ProcessStatus.COMPLETED
    
    def _kill_process(self, pid: int, managed: ManagedProcess, status: ProcessStatus):
        """Kill a process"""
        try:
            process = psutil.Process(pid)
            process.terminate()
            
            # Wait up to 5 seconds for graceful termination
            try:
                process.wait(timeout=5)
            except psutil.TimeoutExpired:
                # Force kill
                process.kill()
            
            managed.status = status
            logger.info(f"Process killed: PID={pid}")
        
        except psutil.NoSuchProcess:
            managed.status = status
    
    def get_info(self, pid: int) -> Optional[Dict]:
        """Get process information"""
        with self._lock:
            managed = self._processes.get(pid)
            if not managed:
                return None
            
            return managed.to_dict()
    
    def get_output(self, pid: int) -> Optional[Dict[str, List[str]]]:
        """Get process output (stdout/stderr)"""
        with self._lock:
            managed = self._processes.get(pid)
            if not managed:
                return None
            
            return {
                "stdout": managed.stdout.copy(),
                "stderr": managed.stderr.copy(),
            }
    
    def kill(self, pid: int) -> bool:
        """
        Kill a running process.
        
        Returns:
            True if process was killed
        """
        with self._lock:
            managed = self._processes.get(pid)
            if not managed or managed.status != ProcessStatus.RUNNING:
                return False
            
            self._kill_process(pid, managed, ProcessStatus.KILLED)
            return True
    
    def list_processes(self, status: Optional[ProcessStatus] = None) -> List[Dict]:
        """
        List all managed processes.
        
        Args:
            status: Filter by status (None = all)
        
        Returns:
            List of process info dicts
        """
        with self._lock:
            processes = []
            
            for managed in self._processes.values():
                if status is None or managed.status == status:
                    processes.append(managed.to_dict())
            
            return processes
    
    def cleanup(self, max_age_seconds: int = 3600) -> int:
        """
        Clean up old completed processes.
        
        Args:
            max_age_seconds: Remove processes older than this
        
        Returns:
            Number of processes removed
        """
        now = datetime.now()
        removed = 0
        
        with self._lock:
            pids_to_remove = []
            
            for pid, managed in self._processes.items():
                if managed.status == ProcessStatus.RUNNING:
                    continue
                
                age = (now - managed.started_at).total_seconds()
                if age > max_age_seconds:
                    pids_to_remove.append(pid)
            
            for pid in pids_to_remove:
                del self._processes[pid]
                removed += 1
        
        if removed > 0:
            logger.info(f"Cleaned up {removed} old processes")
        
        return removed
    
    def shutdown(self):
        """Shutdown manager and kill all running processes"""
        logger.info("Shutting down process manager...")
        
        self._shutdown_event.set()
        
        with self._lock:
            running = [pid for pid, m in self._processes.items() if m.status == ProcessStatus.RUNNING]
            
            for pid in running:
                self.kill(pid)
        
        logger.info("Process manager shutdown complete")


# Global process manager instance
process_manager = ProcessManager()
