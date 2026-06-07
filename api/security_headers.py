"""
BEA MAX — Security Headers Middleware (Phase 4.2)
=====================================================
Adds essential security headers to all HTTP responses.

Headers:
- HSTS: Enforce HTTPS
- CSP: Prevent XSS attacks
- X-Frame-Options: Prevent clickjacking
- X-Content-Type-Options: Prevent MIME sniffing
- Referrer-Policy: Control referrer leakage
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


# Paths qui doivent bypasser la CSP stricte (Swagger/redoc ont besoin d'inline).
_CSP_EXEMPT_PREFIXES = ("/docs", "/redoc", "/openapi.json")


def _is_csp_exempt(path: str) -> bool:
    """True si le path doit bypasser la CSP stricte (Swagger UI, ReDoc, OpenAPI)."""
    return any(path.startswith(p) for p in _CSP_EXEMPT_PREFIXES)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Adds security headers to all responses.
    
    Production-ready defaults following OWASP recommendations.
    """
    
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        
        # HSTS: Force HTTPS for 1 year (31536000 seconds)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        
        # CSP: Content Security Policy.
        # - Strict policy everywhere except Swagger/ReDoc/OpenAPI (which need
        #   inline scripts AND styles to render their UI).
        # - Audit Sprint 2 §4.1 P2: 'unsafe-inline' is scoped to /docs only,
        #   not applied to the main API surface.
        if _is_csp_exempt(request.url.path):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
                "img-src 'self' data: https:; "
                "font-src 'self' data: https://fonts.gstatic.com; "
                "connect-src 'self' https:; "
                "frame-ancestors 'none'"
            )
        else:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self'; "
                "style-src 'self' https://fonts.googleapis.com; "
                "img-src 'self' data: https:; "
                "font-src 'self' data: https://fonts.gstatic.com; "
                "connect-src 'self' https:; "
                "frame-ancestors 'none'"
            )
        
        # X-Frame-Options: Prevent clickjacking
        response.headers["X-Frame-Options"] = "DENY"
        
        # X-Content-Type-Options: Prevent MIME sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"
        
        # Referrer-Policy: Limit referrer information
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        # X-XSS-Protection: Legacy but still useful
        response.headers["X-XSS-Protection"] = "1; mode=block"
        
        # Permissions-Policy: Restrict browser features
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=()"
        )
        
        return response
