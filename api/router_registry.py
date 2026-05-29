"""
api/router_registry.py — Canonical router registration system.

Provides structured registration, status tracking, and dependency loading
for all API routers in JarvisMax.

Design:
  - register_router(name, router): register with metadata
  - get_router(name): retrieve by name
  - get_registry_status(): health summary of all registered routers
  - Soft dependency loading with explicit logging (replaces silent try/except)
"""
from __future__ import annotations

import structlog
from dataclasses import dataclass, field
from typing import Optional
from fastapi import APIRouter

log = structlog.get_logger("api.registry")


@dataclass
class RouterEntry:
    """Registry entry for a mounted API router."""
    name: str
    router: APIRouter
    prefix: str = ""
    tags: list[str] = field(default_factory=list)
    loaded: bool = True
    error: str = ""
    route_count: int = 0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "prefix": self.prefix,
            "tags": self.tags,
            "loaded": self.loaded,
            "error": self.error[:200] if self.error else "",
            "route_count": self.route_count,
        }


class RouterRegistry:
    """Central registry for all API routers."""

    def __init__(self):
        self._routers: dict[str, RouterEntry] = {}
        self._load_errors: list[dict] = []

    def register(self, name: str, router: APIRouter, prefix: str = "", tags: list[str] | None = None) -> None:
        """Register a successfully loaded router."""
        route_count = len(router.routes) if hasattr(router, 'routes') else 0
        entry = RouterEntry(
            name=name,
            router=router,
            prefix=prefix or getattr(router, 'prefix', ''),
            tags=tags or list(getattr(router, 'tags', [])),
            loaded=True,
            route_count=route_count,
        )
        self._routers[name] = entry
        log.debug("router_registered", name=name, prefix=entry.prefix, routes=route_count)

    def register_failure(self, name: str, error: str) -> None:
        """Record a router that failed to load."""
        self._routers[name] = RouterEntry(
            name=name,
            router=APIRouter(),  # empty placeholder
            loaded=False,
            error=error,
        )
        self._load_errors.append({"name": name, "error": error[:200]})
        log.warning("router_load_failed", name=name, err=error[:100])

    def get(self, name: str) -> Optional[APIRouter]:
        """Get a router by name. Returns None if not found or failed."""
        entry = self._routers.get(name)
        if entry and entry.loaded:
            return entry.router
        return None

    def get_status(self) -> dict:
        """Get full registry status summary."""
        loaded = [e for e in self._routers.values() if e.loaded]
        failed = [e for e in self._routers.values() if not e.loaded]
        total_routes = sum(e.route_count for e in loaded)

        return {
            "total_routers": len(self._routers),
            "loaded": len(loaded),
            "failed": len(failed),
            "total_routes": total_routes,
            "routers": {name: e.to_dict() for name, e in self._routers.items()},
            "load_errors": self._load_errors[-20:],
        }

    def get_loaded_names(self) -> list[str]:
        """Get names of all successfully loaded routers."""
        return [name for name, e in self._routers.items() if e.loaded]

    def get_failed_names(self) -> list[str]:
        """Get names of all failed routers."""
        return [name for name, e in self._routers.items() if not e.loaded]


# Singleton
_registry = RouterRegistry()


def register_router(name: str, router: APIRouter, prefix: str = "", tags: list[str] | None = None) -> None:
    _registry.register(name, router, prefix, tags)


def register_failure(name: str, error: str) -> None:
    _registry.register_failure(name, error)


def get_router(name: str) -> Optional[APIRouter]:
    return _registry.get(name)


def get_registry_status() -> dict:
    return _registry.get_status()


def get_registry() -> RouterRegistry:
    return _registry
