"""
JARVIS MAX — Security Headers Middleware (Phase 4.2)
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


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Adds security headers to all responses.
    
    Production-ready defaults following OWASP recommendations.
    """
    
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        
        # HSTS: Force HTTPS for 1 year (31536000 seconds)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        
        # CSP: Content Security Policy (strict but functional)
        # Allows self + inline scripts/styles + Google Fonts
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
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
