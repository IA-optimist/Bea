"""
Rate limiting middleware for JarvisMax API
- Uses Redis for distributed rate limiting
- Applies limits per IP address
- Returns X-RateLimit-* headers
"""

from typing import Callable, Optional
from fastapi import Request, Response, HTTPException
from fastapi.responses import JSONResponse
import time
import redis.asyncio as redis
from functools import wraps

# Rate limiter configuration
RATE_LIMITS = {
    "default": (100, 60),      # 100 requests per minute
    "missions": (20, 60),      # 20 missions per minute
    "opportunities": (50, 60), # 50 opportunities per minute
    "health": (200, 60),       # 200 health checks per minute
}


class RateLimiter:
    """Redis-backed rate limiter"""
    
    def __init__(self, redis_url: str = "redis://redis:6379"):
        self.redis_url = redis_url
        self._redis: Optional[redis.Redis] = None
    
    async def get_redis(self) -> redis.Redis:
        """Get Redis connection (lazy init)"""
        if self._redis is None:
            self._redis = redis.from_url(self.redis_url, decode_responses=True)
        return self._redis
    
    async def check_rate_limit(
        self,
        key: str,
        max_requests: int,
        window_seconds: int
    ) -> tuple[bool, dict]:
        """
        Check if request is within rate limit.
        
        Returns:
            (allowed, info_dict)
            - allowed: bool, whether request should be allowed
            - info_dict: dict with limit, remaining, reset timestamp
        """
        r = await self.get_redis()
        now = int(time.time())
        window_key = f"ratelimit:{key}:{now // window_seconds}"
        
        # Increment counter
        current = await r.incr(window_key)
        
        # Set expiry on first request
        if current == 1:
            await r.expire(window_key, window_seconds)
        
        # Calculate info
        remaining = max(0, max_requests - current)
        reset_time = (now // window_seconds + 1) * window_seconds
        
        info = {
            "limit": max_requests,
            "remaining": remaining,
            "reset": reset_time,
            "current": current,
        }
        
        allowed = current <= max_requests
        return allowed, info
    
    async def close(self):
        """Close Redis connection"""
        if self._redis:
            await self._redis.close()


# Global rate limiter instance
_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """Get global rate limiter instance"""
    global _limiter
    if _limiter is None:
        _limiter = RateLimiter()
    return _limiter


def rate_limit(
    endpoint_name: str = "default",
    max_requests: Optional[int] = None,
    window_seconds: Optional[int] = None
):
    """
    Rate limit decorator for FastAPI endpoints.
    
    Usage:
        @app.get("/api/missions")
        @rate_limit("missions")
        async def get_missions(request: Request):
            ...
    
    Args:
        endpoint_name: Name of endpoint (uses RATE_LIMITS config)
        max_requests: Override max requests (optional)
        window_seconds: Override window seconds (optional)
    """
    # Get config
    if endpoint_name in RATE_LIMITS:
        default_max, default_window = RATE_LIMITS[endpoint_name]
    else:
        default_max, default_window = RATE_LIMITS["default"]
    
    max_req = max_requests or default_max
    window = window_seconds or default_window
    
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(request: Request, *args, **kwargs):
            # Extract client IP
            client_ip = request.client.host if request.client else "unknown"
            forwarded = request.headers.get("X-Forwarded-For")
            if forwarded:
                client_ip = forwarded.split(",")[0].strip()
            
            # Check rate limit
            limiter = get_rate_limiter()
            rate_key = f"{client_ip}:{endpoint_name}"
            
            allowed, info = await limiter.check_rate_limit(
                rate_key, max_req, window
            )
            
            # Add rate limit headers to response
            if not allowed:
                # Rate limit exceeded
                raise HTTPException(
                    status_code=429,
                    detail={
                        "error": "Rate limit exceeded",
                        "limit": info["limit"],
                        "reset": info["reset"],
                        "retry_after": info["reset"] - int(time.time()),
                    },
                    headers={
                        "X-RateLimit-Limit": str(info["limit"]),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(info["reset"]),
                        "Retry-After": str(info["reset"] - int(time.time())),
                    }
                )
            
            # Execute endpoint
            response = await func(request, *args, **kwargs)
            
            # Add headers to successful response
            if isinstance(response, Response):
                response.headers["X-RateLimit-Limit"] = str(info["limit"])
                response.headers["X-RateLimit-Remaining"] = str(info["remaining"])
                response.headers["X-RateLimit-Reset"] = str(info["reset"])
            
            return response
        
        return wrapper
    return decorator


# Middleware for automatic rate limiting (optional global approach)
async def rate_limit_middleware(request: Request, call_next):
    """
    Global rate limiting middleware.
    Apply to all endpoints automatically.
    """
    # Skip rate limiting for health checks and static files
    if request.url.path in ["/health", "/docs", "/redoc", "/openapi.json"]:
        return await call_next(request)
    
    # Extract client IP
    client_ip = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
    
    # Determine endpoint type
    endpoint_name = "default"
    if "/missions" in request.url.path:
        endpoint_name = "missions"
    elif "/opportunities" in request.url.path:
        endpoint_name = "opportunities"
    elif "/health" in request.url.path:
        endpoint_name = "health"
    
    max_req, window = RATE_LIMITS.get(endpoint_name, RATE_LIMITS["default"])
    
    # Check rate limit
    limiter = get_rate_limiter()
    rate_key = f"{client_ip}:{endpoint_name}"
    
    allowed, info = await limiter.check_rate_limit(rate_key, max_req, window)
    
    if not allowed:
        return JSONResponse(
            status_code=429,
            content={
                "ok": False,
                "error": "Rate limit exceeded",
                "limit": info["limit"],
                "reset": info["reset"],
                "retry_after": info["reset"] - int(time.time()),
            },
            headers={
                "X-RateLimit-Limit": str(info["limit"]),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(info["reset"]),
                "Retry-After": str(info["reset"] - int(time.time())),
            }
        )
    
    # Execute request
    response = await call_next(request)
    
    # Add rate limit headers
    response.headers["X-RateLimit-Limit"] = str(info["limit"])
    response.headers["X-RateLimit-Remaining"] = str(info["remaining"])
    response.headers["X-RateLimit-Reset"] = str(info["reset"])
    
    return response
