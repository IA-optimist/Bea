#!/usr/bin/env python3
"""
JarvisMax OS — REST API

FastAPI server for JarvisMax OS.

Endpoints:
- GET  /health              Health check
- GET  /status              OS status
- GET  /modules             List all modules
- GET  /modules/{name}      Get module details
- POST /modules/{name}/start    Start module
- POST /modules/{name}/stop     Stop module
- GET  /tasks               List tasks
- POST /tasks               Create task
- GET  /tasks/{id}          Get task details
- GET  /revenue             Revenue dashboard
- GET  /metrics             System metrics
"""
from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from uuid import uuid4

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.jarvismax_os import JarvisMaxOS, ModuleStatus

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s'
)
logger = logging.getLogger("JarvisMaxAPI")

# Global OS instance
os_instance: Optional[JarvisMaxOS] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager — start/stop OS with FastAPI"""
    global os_instance
    
    logger.info("🚀 Starting JarvisMax OS...")
    os_instance = JarvisMaxOS()
    await os_instance.start()
    logger.info("✅ JarvisMax OS started")
    
    yield
    
    logger.info("🛑 Stopping JarvisMax OS...")
    await os_instance.stop()
    logger.info("✅ JarvisMax OS stopped")


# FastAPI app
app = FastAPI(
    title="JarvisMax OS API",
    description="REST API for JarvisMax Autonomous AI Operating System",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# REQUEST/RESPONSE MODELS
# ============================================================================

class TaskCreate(BaseModel):
    module: str
    action: str
    params: Optional[Dict] = {}


class TaskResponse(BaseModel):
    id: str
    module: str
    action: str
    params: Dict
    status: str
    created_at: str


class ModuleResponse(BaseModel):
    name: str
    description: str
    version: str
    status: str
    error: Optional[str]
    started_at: Optional[str]
    metrics: Dict
    revenue: Dict


# ============================================================================
# ENDPOINTS
# ============================================================================

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "name": "JarvisMax OS API",
        "version": "1.0.0",
        "status": "operational",
        "docs": "/docs",
    }


@app.get("/health")
async def health():
    """Health check"""
    if not os_instance or not os_instance.running:
        raise HTTPException(status_code=503, detail="OS not running")
    
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "os_running": os_instance.running,
    }


@app.get("/status")
async def get_status():
    """Get OS status"""
    if not os_instance:
        raise HTTPException(status_code=503, detail="OS not initialized")
    
    status = os_instance.get_status()
    return status


@app.get("/modules")
async def list_modules() -> List[ModuleResponse]:
    """List all modules"""
    if not os_instance:
        raise HTTPException(status_code=503, detail="OS not initialized")
    
    modules = []
    for name, module in os_instance.modules.items():
        modules.append(ModuleResponse(**module.to_dict()))
    
    return modules


@app.get("/modules/{name}")
async def get_module(name: str) -> ModuleResponse:
    """Get module details"""
    if not os_instance:
        raise HTTPException(status_code=503, detail="OS not initialized")
    
    module = os_instance.modules.get(name)
    if not module:
        raise HTTPException(status_code=404, detail=f"Module not found: {name}")
    
    return ModuleResponse(**module.to_dict())


@app.post("/modules/{name}/start")
async def start_module(name: str):
    """Start a module"""
    if not os_instance:
        raise HTTPException(status_code=503, detail="OS not initialized")
    
    if name not in os_instance.modules:
        raise HTTPException(status_code=404, detail=f"Module not found: {name}")
    
    await os_instance._start_module(name)
    
    module = os_instance.modules[name]
    return {
        "status": "success",
        "module": name,
        "module_status": module.status.value,
    }


@app.post("/modules/{name}/stop")
async def stop_module(name: str):
    """Stop a module"""
    if not os_instance:
        raise HTTPException(status_code=503, detail="OS not initialized")
    
    if name not in os_instance.modules:
        raise HTTPException(status_code=404, detail=f"Module not found: {name}")
    
    await os_instance._stop_module(name)
    
    module = os_instance.modules[name]
    return {
        "status": "success",
        "module": name,
        "module_status": module.status.value,
    }


@app.post("/tasks")
async def create_task(task: TaskCreate, background_tasks: BackgroundTasks) -> TaskResponse:
    """Create and queue a task"""
    if not os_instance:
        raise HTTPException(status_code=503, detail="OS not initialized")
    
    # Validate module exists
    if task.module not in os_instance.modules:
        raise HTTPException(status_code=404, detail=f"Module not found: {task.module}")
    
    # Validate module is running
    module = os_instance.modules[task.module]
    if module.status != ModuleStatus.RUNNING:
        raise HTTPException(
            status_code=400,
            detail=f"Module not running: {task.module} (status: {module.status.value})"
        )
    
    # Create task
    task_id = str(uuid4())
    task_data = {
        'id': task_id,
        'module': task.module,
        'action': task.action,
        'params': task.params,
        'status': 'queued',
        'created_at': datetime.now().isoformat(),
    }
    
    # Queue task
    await os_instance.task_queue.put(task_data)
    
    return TaskResponse(**task_data)


@app.get("/tasks")
async def list_tasks():
    """List all tasks (stub)"""
    # In real implementation: query database for task history
    return {
        "tasks": [],
        "total": 0,
        "note": "Task history coming in v1.1.0",
    }


@app.get("/tasks/{task_id}")
async def get_task(task_id: str):
    """Get task details (stub)"""
    # In real implementation: query database
    raise HTTPException(status_code=404, detail="Task not found")


@app.get("/revenue")
async def get_revenue():
    """Get revenue dashboard"""
    if not os_instance:
        raise HTTPException(status_code=503, detail="OS not initialized")
    
    status = os_instance.get_status()
    
    # Build breakdown by module
    breakdown = []
    for name, module in sorted(
        os_instance.modules.items(),
        key=lambda x: x[1].mrr,
        reverse=True
    ):
        if module.mrr > 0:
            percentage = (module.mrr / status['revenue']['mrr']) * 100 if status['revenue']['mrr'] > 0 else 0
            breakdown.append({
                'module': name,
                'mrr': round(module.mrr, 2),
                'customers': module.customers,
                'percentage': round(percentage, 1),
            })
    
    return {
        'mrr': status['revenue']['mrr'],
        'arr': status['revenue']['arr'],
        'customers': status['revenue']['customers'],
        'breakdown': breakdown,
    }


@app.get("/metrics")
async def get_metrics():
    """Get system metrics"""
    if not os_instance:
        raise HTTPException(status_code=503, detail="OS not initialized")
    
    status = os_instance.get_status()
    
    # Per-module metrics
    module_metrics = []
    for name, module in os_instance.modules.items():
        module_metrics.append({
            'module': name,
            'status': module.status.value,
            'requests_total': module.requests_total,
            'requests_failed': module.requests_failed,
            'avg_response_time': round(module.avg_response_time, 3),
        })
    
    return {
        'system': {
            'uptime': status['uptime'],
            'modules_running': status['modules']['running'],
            'modules_total': status['modules']['total'],
        },
        'requests': {
            'total': status['metrics']['requests_total'],
            'failed': status['metrics']['requests_failed'],
            'success_rate': round(status['metrics']['success_rate'], 2),
        },
        'modules': module_metrics,
    }


# ============================================================================
# ERROR HANDLERS
# ============================================================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "status_code": exc.status_code,
            "timestamp": datetime.now().isoformat(),
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "status_code": 500,
            "timestamp": datetime.now().isoformat(),
        }
    )


# ============================================================================
# MAIN (for standalone mode)
# ============================================================================

if __name__ == '__main__':
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
