"""
JarvisMax - Project Context Management
Thread-safe storage for current project context.
"""
import threading
from typing import Optional
import structlog

log = structlog.get_logger(__name__)

_context = threading.local()

def set_project(project_id: str):
    """Set current project context."""
    _context.project_id = project_id
    log.debug("project_context_set", project_id=project_id)

def get_project() -> Optional[str]:
    """Get current project ID."""
    return getattr(_context, "project_id", None)

def clear_project():
    """Clear project context."""
    if hasattr(_context, "project_id"):
        delattr(_context, "project_id")

def inject_project(data: dict) -> dict:
    """Inject project_id into data if not present."""
    if "project_id" not in data:
        pid = get_project()
        if pid:
            data["project_id"] = pid
    return data
