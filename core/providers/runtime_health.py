"""Runtime health check for LLM providers (PR #92).

Detects which providers are available at runtime — key present, network
reachable, models listed — and returns a structured ProviderHealth result.

Usage (sync, e.g. CLI):
    from core.providers.runtime_health import check_provider_health_sync
    health = check_provider_health_sync()
    print(health.status)  # READY | DEGRADED | UNAVAILABLE

Usage (async, e.g. in an ASGI route):
    from core.providers.runtime_health import check_provider_health
    health = await check_provider_health()
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import os
from dataclasses import dataclass, field

import httpx
import structlog

log = structlog.get_logger(__name__)

# Ordered list of localhost alternatives to try when the configured host is
# the Docker-compose default and is not reachable.
_OLLAMA_LOCAL_CANDIDATES: tuple[str, ...] = (
    "http://127.0.0.1:11434",
    "http://localhost:11434",
)

_DOCKER_OLLAMA_HOST = "http://ollama:11434"


@dataclass
class ProviderHealth:
    """Snapshot of LLM provider availability."""

    openrouter_key_present: bool = False
    openrouter_usable: bool | None = None  # None = not probed (key absent)
    ollama_reachable: bool = False
    ollama_host_used: str = ""
    ollama_models: list[str] = field(default_factory=list)
    default_provider: str = "none"
    fallback_provider: str = "none"
    status: str = "UNAVAILABLE"  # "READY" | "DEGRADED" | "UNAVAILABLE"
    hints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "openrouter_key_present": self.openrouter_key_present,
            "openrouter_usable": self.openrouter_usable,
            "ollama_reachable": self.ollama_reachable,
            "ollama_host_used": self.ollama_host_used,
            "ollama_models": self.ollama_models,
            "default_provider": self.default_provider,
            "fallback_provider": self.fallback_provider,
            "status": self.status,
            "hints": self.hints,
        }


def _key_looks_valid(key: str | None) -> bool:
    """True if key is present and not a placeholder."""
    if not key:
        return False
    k = key.strip().lower()
    if len(k) < 20:
        return False
    for frag in ("change_me", "replace_me", "your_key", "placeholder", "xxx"):
        if frag in k:
            return False
    return True


async def check_provider_health(settings=None) -> ProviderHealth:
    """Probe all LLM providers and return a ProviderHealth snapshot.

    Never logs secret values — only key presence (yes/no).
    """
    if settings is None:
        try:
            from config.settings import get_settings
            settings = get_settings()
        except Exception:
            pass

    result = ProviderHealth()

    # ── OpenRouter ────────────────────────────────────────────────────────────
    or_key: str = (
        getattr(settings, "openrouter_api_key", "") or
        os.environ.get("OPENROUTER_API_KEY", "")
    )
    result.openrouter_key_present = _key_looks_valid(or_key)

    if result.openrouter_key_present:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:  # noqa: SIM117
                resp = await client.get(
                    "https://openrouter.ai/api/v1/models",
                    headers={"Authorization": f"Bearer {or_key}"},
                )
                result.openrouter_usable = resp.status_code == 200
        except Exception as exc:
            result.openrouter_usable = False
            log.debug("openrouter_probe_failed", err=str(exc)[:80])
    else:
        result.openrouter_usable = False
        result.hints.append(
            "OPENROUTER_API_KEY absent ou invalide. "
            "En mode CLI: exporter OPENROUTER_API_KEY=sk-or-... "
            "Via le service Windows, bea_api_service.cmd charge le .env automatiquement."
        )

    # ── Ollama ────────────────────────────────────────────────────────────────
    configured_host: str = (
        getattr(settings, "ollama_host", "") or
        os.environ.get("OLLAMA_HOST", _DOCKER_OLLAMA_HOST)
    )

    # Build probe list: configured first, then localhost alternatives if Docker default
    probe_hosts = [configured_host]
    if configured_host == _DOCKER_OLLAMA_HOST:
        for alt in _OLLAMA_LOCAL_CANDIDATES:
            if alt not in probe_hosts:
                probe_hosts.append(alt)

    for host in probe_hosts:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:  # noqa: SIM117
                version_resp = await client.get(f"{host}/api/version")
                if version_resp.status_code == 200:
                    result.ollama_reachable = True
                    result.ollama_host_used = host
                    # Fetch available models
                    try:
                        tags_resp = await client.get(f"{host}/api/tags")
                        if tags_resp.status_code == 200:
                            models_data = tags_resp.json()
                            result.ollama_models = [
                                m["name"] for m in models_data.get("models", [])
                            ]
                    except Exception:
                        pass
                    if host != configured_host:
                        log.info(
                            "ollama_host_autodiscovered",
                            configured=configured_host,
                            resolved=host,
                        )
                    break
        except Exception:
            continue

    if not result.ollama_reachable:
        result.hints.append(
            "Ollama n'est pas joignable. "
            "Démarrer avec: ollama serve "
            f"(testé: {', '.join(probe_hosts)}). "
            "Configurer OLLAMA_HOST=http://127.0.0.1:11434 pour dev local."
        )

    # ── Determine overall status ──────────────────────────────────────────────
    if result.openrouter_usable:
        result.default_provider = "openrouter"
        result.fallback_provider = "ollama" if result.ollama_reachable else "none"
        result.status = "READY"
    elif result.ollama_reachable:
        result.default_provider = "ollama"
        result.fallback_provider = "none"
        result.status = "DEGRADED"
        model_list = ", ".join(result.ollama_models[:5]) or "aucun"
        result.hints.append(
            f"Mode dégradé: OpenRouter absent, Ollama disponible ({model_list}). "
            "Les rôles cloud utiliseront Ollama en fallback."
        )
    else:
        result.status = "UNAVAILABLE"
        result.hints.append(
            "Aucun provider LLM disponible. "
            "Configurer OPENROUTER_API_KEY ou démarrer Ollama (ollama serve)."
        )

    log.info(
        "provider_health_checked",
        status=result.status,
        openrouter_key=result.openrouter_key_present,
        openrouter_ok=result.openrouter_usable,
        ollama_ok=result.ollama_reachable,
        ollama_host=result.ollama_host_used or "none",
        models=len(result.ollama_models),
    )

    return result


def check_provider_health_sync(settings=None, timeout: float = 15.0) -> ProviderHealth:
    """Synchronous wrapper — safe to call from both sync and async contexts."""
    try:
        asyncio.get_running_loop()
        # Already inside an event loop — run in a thread to avoid blocking
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(asyncio.run, check_provider_health(settings))
            return fut.result(timeout=timeout)
    except RuntimeError:
        # No running event loop — safe to use asyncio.run()
        return asyncio.run(check_provider_health(settings))
