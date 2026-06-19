"""
api/deprecation_middleware.py — API Deprecation Middleware

Adds deprecation headers and warnings to legacy API routes.
Helps migrate users from deprecated routes to stable v1 surface.
"""
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Optional
import logging

logger = logging.getLogger(__name__)


# Deprecated routes and their migration paths
DEPRECATED_ROUTES = {
    # Legacy v2 routes
    "/api/v2/missions": {"migrate_to": "/api/v1/missions", "deprecated_since": "2026-06-19"},
    "/api/v2/memory": {"migrate_to": "/api/v1/memory", "deprecated_since": "2026-06-19"},
    
    # Experimental features
    "/api/v1/venture/": {"migrate_to": None, "deprecated_since": "2026-06-19", "reason": "Experimental feature"},
    "/api/v1/voice/": {"migrate_to": None, "deprecated_since": "2026-06-19", "reason": "Stub implementation"},
    "/api/v1/multimodal/": {"migrate_to": None, "deprecated_since": "2026-06-19", "reason": "Stub implementation"},
    "/api/v1/browser/": {"migrate_to": None, "deprecated_since": "2026-06-19", "reason": "Stub implementation"},
    "/api/v1/playbooks/": {"migrate_to": None, "deprecated_since": "2026-06-19", "reason": "Static data only"},
}


class DeprecationMiddleware(BaseHTTPMiddleware):
    """
    Middleware to add deprecation headers to deprecated routes.
    """
    
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        
        # Check if route is deprecated
        route_info = self._is_deprecated(request.url.path)
        if route_info:
            self._add_deprecation_headers(response, route_info)
            logger.warning(
                f"Deprecated route accessed: {request.url.path}",
                extra={"route": request.url.path, "migrate_to": route_info.get("migrate_to")}
            )
        
        return response
    
    def _is_deprecated(self, path: str) -> Optional[dict]:
        """Check if a route is deprecated and return migration info."""
        for deprecated_path, info in DEPRECATED_ROUTES.items():
            if path.startswith(deprecated_path.rstrip("/")):
                return info
        return None
    
    def _add_deprecation_headers(self, response: Response, route_info: dict):
        """Add deprecation headers to response."""
        response.headers["X-Deprecated"] = "true"
        response.headers["X-Deprecated-Since"] = route_info.get("deprecated_since", "unknown")
        
        if route_info.get("migrate_to"):
            response.headers["X-Migrate-To"] = route_info["migrate_to"]
        
        if route_info.get("reason"):
            response.headers["X-Deprecation-Reason"] = route_info["reason"]
        
        # Add warning header for HTTP clients
        warning_msg = f"This route is deprecated since {route_info.get('deprecated_since')}"
        if route_info.get("migrate_to"):
            warning_msg += f". Use {route_info['migrate_to']} instead."
        if route_info.get("reason"):
            warning_msg += f" Reason: {route_info['reason']}"
        
        response.headers["Warning"] = f'299 - "{warning_msg}"'
