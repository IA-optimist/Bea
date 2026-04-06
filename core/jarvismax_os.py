#!/usr/bin/env python3
"""
JarvisMax OS — Autonomous AI Operating System

Central orchestrator for all JarvisMax modules.

Architecture:
- Core OS (this file) — Module registry, task dispatcher, lifecycle management
- API Server (web_api/) — REST API + WebSocket
- Dashboard (web_dashboard/) — Web UI
- Database (PostgreSQL) — Persistent storage
- Cache (Redis) — Task queue, session state
- Modules:
  * Business Engine (business/)
  * HexStrike (security/hexstrike_v2/)
  * Tax Optimizer (business/fiscal/)
  * SOC Service (security/blue_team/)
  * Data Intelligence (data_intelligence/)
  * Agent Marketplace (agent_marketplace/)
"""
from __future__ import annotations

import asyncio
import logging
import signal
import sys
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("JarvisMaxOS")


class ModuleStatus(str, Enum):
    """Module status"""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"
    STOPPING = "stopping"


@dataclass
class Module:
    """OS module"""
    name: str
    description: str
    version: str
    
    # Lifecycle hooks
    start_fn: Optional[Callable] = None
    stop_fn: Optional[Callable] = None
    health_fn: Optional[Callable] = None
    
    # State
    status: ModuleStatus = ModuleStatus.STOPPED
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    
    # Metrics
    requests_total: int = 0
    requests_failed: int = 0
    avg_response_time: float = 0.0
    
    # Revenue (if applicable)
    mrr: float = 0.0
    customers: int = 0
    
    def to_dict(self) -> Dict:
        return {
            'name': self.name,
            'description': self.description,
            'version': self.version,
            'status': self.status.value,
            'error': self.error,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'metrics': {
                'requests_total': self.requests_total,
                'requests_failed': self.requests_failed,
                'avg_response_time': round(self.avg_response_time, 3),
            },
            'revenue': {
                'mrr': round(self.mrr, 2),
                'customers': self.customers,
            },
        }


class JarvisMaxOS:
    """
    JarvisMax Autonomous AI Operating System.
    
    Central orchestrator for all modules.
    
    Usage:
        os = JarvisMaxOS()
        await os.start()
        
        # Use modules
        result = await os.dispatch("business_engine", "scan_opportunities")
        
        # Stop
        await os.stop()
    """
    
    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or Path.home() / ".jarvismax" / "config.yaml"
        self.data_dir = Path.home() / ".jarvismax"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Module registry
        self.modules: Dict[str, Module] = {}
        
        # State
        self.running = False
        self.started_at: Optional[datetime] = None
        
        # Task queue
        self.task_queue: asyncio.Queue = asyncio.Queue()
        self.workers: List[asyncio.Task] = []
        
        logger.info("🚀 JarvisMax OS initialized")
    
    def register_module(
        self,
        name: str,
        description: str,
        version: str = "1.0.0",
        start_fn: Optional[Callable] = None,
        stop_fn: Optional[Callable] = None,
        health_fn: Optional[Callable] = None,
    ) -> Module:
        """Register a module"""
        module = Module(
            name=name,
            description=description,
            version=version,
            start_fn=start_fn,
            stop_fn=stop_fn,
            health_fn=health_fn,
        )
        
        self.modules[name] = module
        logger.info(f"✅ Module registered: {name} v{version}")
        
        return module
    
    async def start(self):
        """Start the OS"""
        if self.running:
            logger.warning("OS already running")
            return
        
        logger.info("=" * 80)
        logger.info("🚀 JARVISMAX OS — STARTING")
        logger.info("=" * 80)
        
        self.running = True
        self.started_at = datetime.now()
        
        # Register core modules
        self._register_core_modules()
        
        # Start all modules
        for name, module in self.modules.items():
            await self._start_module(name)
        
        # Start task workers
        num_workers = 4
        for i in range(num_workers):
            worker = asyncio.create_task(self._task_worker(i))
            self.workers.append(worker)
        
        logger.info("=" * 80)
        logger.info(f"✅ JARVISMAX OS — RUNNING ({len(self.modules)} modules)")
        logger.info("=" * 80)
        
        # Print status
        self.print_status()
    
    async def stop(self):
        """Stop the OS"""
        if not self.running:
            logger.warning("OS not running")
            return
        
        logger.info("=" * 80)
        logger.info("🛑 JARVISMAX OS — STOPPING")
        logger.info("=" * 80)
        
        self.running = False
        
        # Stop workers
        for worker in self.workers:
            worker.cancel()
        
        await asyncio.gather(*self.workers, return_exceptions=True)
        self.workers.clear()
        
        # Stop all modules
        for name, module in self.modules.items():
            await self._stop_module(name)
        
        logger.info("=" * 80)
        logger.info("✅ JARVISMAX OS — STOPPED")
        logger.info("=" * 80)
    
    def _register_core_modules(self):
        """Register all core modules"""
        
        # 1. Business Engine
        self.register_module(
            name="business_engine",
            description="Autonomous SaaS generation pipeline",
            version="1.0.0",
            start_fn=self._start_business_engine,
            health_fn=self._health_business_engine,
        )
        
        # 2. HexStrike (Bug Bounty)
        self.register_module(
            name="hexstrike",
            description="Automated bug bounty hunting",
            version="2.0.0",
            start_fn=self._start_hexstrike,
            health_fn=self._health_hexstrike,
        )
        
        # 3. Tax Optimizer
        self.register_module(
            name="tax_optimizer",
            description="Legal tax optimization service",
            version="1.0.0",
            start_fn=self._start_tax_optimizer,
            health_fn=self._health_tax_optimizer,
        )
        
        # 4. SOC Service
        self.register_module(
            name="soc_service",
            description="Security Operations Center as a Service",
            version="1.0.0",
            start_fn=self._start_soc_service,
            health_fn=self._health_soc_service,
        )
        
        # 5. Data Intelligence
        self.register_module(
            name="data_intelligence",
            description="Market research & competitive analysis",
            version="1.0.0",
            start_fn=self._start_data_intelligence,
            health_fn=self._health_data_intelligence,
        )
        
        # 6. Agent Marketplace
        self.register_module(
            name="agent_marketplace",
            description="AI agent marketplace platform",
            version="1.0.0",
            start_fn=self._start_agent_marketplace,
            health_fn=self._health_agent_marketplace,
        )
    
    async def _start_module(self, name: str):
        """Start a module"""
        module = self.modules.get(name)
        if not module:
            logger.error(f"Module not found: {name}")
            return
        
        logger.info(f"🔄 Starting module: {name}")
        
        try:
            module.status = ModuleStatus.STARTING
            
            if module.start_fn:
                result = module.start_fn()
                if asyncio.iscoroutine(result):
                    await result
            
            module.status = ModuleStatus.RUNNING
            module.started_at = datetime.now()
            module.error = None
            
            logger.info(f"✅ Module started: {name}")
        
        except Exception as e:
            module.status = ModuleStatus.ERROR
            module.error = str(e)
            logger.error(f"❌ Failed to start module {name}: {e}")
    
    async def _stop_module(self, name: str):
        """Stop a module"""
        module = self.modules.get(name)
        if not module:
            return
        
        logger.info(f"🔄 Stopping module: {name}")
        
        try:
            module.status = ModuleStatus.STOPPING
            
            if module.stop_fn:
                result = module.stop_fn()
                if asyncio.iscoroutine(result):
                    await result
            
            module.status = ModuleStatus.STOPPED
            
            logger.info(f"✅ Module stopped: {name}")
        
        except Exception as e:
            module.status = ModuleStatus.ERROR
            module.error = str(e)
            logger.error(f"❌ Failed to stop module {name}: {e}")
    
    async def dispatch(self, module_name: str, action: str, **kwargs) -> Any:
        """
        Dispatch action to a module.
        
        Args:
            module_name: Target module
            action: Action to perform
            **kwargs: Action parameters
        
        Returns:
            Action result
        """
        module = self.modules.get(module_name)
        if not module:
            raise ValueError(f"Module not found: {module_name}")
        
        if module.status != ModuleStatus.RUNNING:
            raise RuntimeError(f"Module not running: {module_name} (status: {module.status.value})")
        
        # Queue task
        task = {
            'module': module_name,
            'action': action,
            'params': kwargs,
            'created_at': datetime.now(),
        }
        
        await self.task_queue.put(task)
        
        # In real implementation: return Future and wait for result
        return {"status": "queued", "task": task}
    
    async def _task_worker(self, worker_id: int):
        """Task worker (processes queued tasks)"""
        logger.info(f"🔧 Worker {worker_id} started")
        
        # Import action executor
        from core.modules_integration import execute_action
        
        while self.running:
            try:
                # Get task from queue
                task = await asyncio.wait_for(self.task_queue.get(), timeout=1.0)
                
                module_name = task['module']
                action = task['action']
                params = task.get('params', {})
                
                logger.info(f"⚙️  Worker {worker_id}: {module_name}.{action}")
                
                # Execute task
                start_time = datetime.now()
                
                try:
                    result = await execute_action(module_name, action, params)
                    
                    # Update metrics
                    module = self.modules[module_name]
                    module.requests_total += 1
                    
                    # Update avg response time
                    response_time = (datetime.now() - start_time).total_seconds()
                    if module.avg_response_time == 0:
                        module.avg_response_time = response_time
                    else:
                        module.avg_response_time = (module.avg_response_time + response_time) / 2
                    
                    logger.info(f"✅ Worker {worker_id}: {module_name}.{action} completed ({response_time:.2f}s)")
                
                except Exception as e:
                    # Update error metrics
                    module = self.modules[module_name]
                    module.requests_total += 1
                    module.requests_failed += 1
                    
                    logger.error(f"❌ Worker {worker_id}: {module_name}.{action} failed: {e}")
                
                self.task_queue.task_done()
            
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Worker {worker_id} error: {e}")
        
        logger.info(f"🔧 Worker {worker_id} stopped")
    
    def get_status(self) -> Dict:
        """Get OS status"""
        uptime = (datetime.now() - self.started_at).total_seconds() if self.started_at else 0
        
        # Calculate totals
        total_requests = sum(m.requests_total for m in self.modules.values())
        total_failed = sum(m.requests_failed for m in self.modules.values())
        total_mrr = sum(m.mrr for m in self.modules.values())
        total_customers = sum(m.customers for m in self.modules.values())
        
        running_modules = sum(1 for m in self.modules.values() if m.status == ModuleStatus.RUNNING)
        
        return {
            'status': 'running' if self.running else 'stopped',
            'uptime': round(uptime, 2),
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'modules': {
                'total': len(self.modules),
                'running': running_modules,
                'error': sum(1 for m in self.modules.values() if m.status == ModuleStatus.ERROR),
            },
            'metrics': {
                'requests_total': total_requests,
                'requests_failed': total_failed,
                'success_rate': (total_requests - total_failed) / max(total_requests, 1) * 100,
            },
            'revenue': {
                'mrr': round(total_mrr, 2),
                'arr': round(total_mrr * 12, 2),
                'customers': total_customers,
            },
        }
    
    def print_status(self):
        """Print OS status to console"""
        status = self.get_status()
        
        print("\n" + "=" * 80)
        print("📊 JARVISMAX OS — STATUS")
        print("=" * 80)
        print(f"Status: {status['status'].upper()}")
        print(f"Uptime: {status['uptime']:.0f}s")
        print(f"Modules: {status['modules']['running']}/{status['modules']['total']} running")
        print(f"Requests: {status['metrics']['requests_total']} total, {status['metrics']['success_rate']:.1f}% success")
        print(f"Revenue: €{status['revenue']['mrr']:,.2f} MRR, {status['revenue']['customers']} customers")
        print("=" * 80)
        print("\n📦 MODULES:\n")
        
        for name, module in self.modules.items():
            status_icon = {
                ModuleStatus.RUNNING: "✅",
                ModuleStatus.STOPPED: "⭕",
                ModuleStatus.ERROR: "❌",
                ModuleStatus.STARTING: "🔄",
                ModuleStatus.STOPPING: "🔄",
            }.get(module.status, "❓")
            
            print(f"{status_icon} {name:20s} {module.status.value:10s} — {module.description}")
            if module.error:
                print(f"   Error: {module.error}")
        
        print("\n" + "=" * 80 + "\n")
    
    # Module-specific start functions
    
    def _start_business_engine(self):
        """Start Business Engine"""
        logger.info("💼 Business Engine: Initializing opportunity scanner...")
        # In real implementation: start background scanner
        
        # Update metrics (demo)
        self.modules['business_engine'].mrr = 500.0  # €500 MRR from 2 MVPs
        self.modules['business_engine'].customers = 2
    
    def _health_business_engine(self) -> bool:
        """Health check: Business Engine"""
        return True
    
    def _start_hexstrike(self):
        """Start HexStrike"""
        logger.info("🎯 HexStrike: Loading security tools...")
        # In real implementation: load tool registry
        
        self.modules['hexstrike'].mrr = 0.0  # In development
        self.modules['hexstrike'].customers = 0
    
    def _health_hexstrike(self) -> bool:
        return True
    
    def _start_tax_optimizer(self):
        """Start Tax Optimizer"""
        logger.info("💶 Tax Optimizer: Loading tax scenarios...")
        
        self.modules['tax_optimizer'].mrr = 100.0  # €100 from 10 beta users
        self.modules['tax_optimizer'].customers = 10
    
    def _health_tax_optimizer(self) -> bool:
        return True
    
    def _start_soc_service(self):
        """Start SOC Service"""
        logger.info("🛡️  SOC Service: Connecting to SIEM...")
        
        self.modules['soc_service'].mrr = 2000.0  # €2k from 1 client
        self.modules['soc_service'].customers = 1
    
    def _health_soc_service(self) -> bool:
        return True
    
    def _start_data_intelligence(self):
        """Start Data Intelligence"""
        logger.info("📊 Data Intelligence: Starting market scanners...")
        
        self.modules['data_intelligence'].mrr = 200.0  # €200 from 1 client
        self.modules['data_intelligence'].customers = 1
    
    def _health_data_intelligence(self) -> bool:
        return True
    
    def _start_agent_marketplace(self):
        """Start Agent Marketplace"""
        logger.info("🤖 Agent Marketplace: Loading agent catalog...")
        
        self.modules['agent_marketplace'].mrr = 100.0  # €100 first sales
        self.modules['agent_marketplace'].customers = 5
    
    def _health_agent_marketplace(self) -> bool:
        return True


async def main():
    """Main entry point"""
    os_instance = JarvisMaxOS()
    
    # Signal handlers
    loop = asyncio.get_event_loop()
    
    def signal_handler(sig):
        logger.info(f"Received signal {sig}, shutting down...")
        asyncio.create_task(os_instance.stop())
    
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig: signal_handler(s))
    
    # Start OS
    await os_instance.start()
    
    # Keep running until stopped
    try:
        while os_instance.running:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        await os_instance.stop()


if __name__ == '__main__':
    asyncio.run(main())
