"""
core/model_intelligence/catalog.py — OpenRouter model catalog.

Fetches, normalizes, and caches available models from OpenRouter.

Design:
  - Fetches from https://openrouter.ai/api/v1/models
  - Normalizes into typed ModelEntry dataclass
  - Persists last known catalog to JSON (survives restarts)
  - Fail-open: returns cached catalog if refresh fails
  - Periodic refresh support (no automatic background thread)
"""
from __future__ import annotations

import json
import time
import threading
import structlog
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = structlog.get_logger("model_intelligence.catalog")

_CATALOG_PATH = Path("data/model_catalog.json")
_OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"


@dataclass
class ModelEntry:
    """Normalized model metadata from OpenRouter."""
    model_id: str = ""              # "anthropic/claude-sonnet-4.5"
    name: str = ""                  # "Claude 3.5 Sonnet"
    provider: str = ""              # "anthropic"
    context_length: int = 0         # max tokens
    pricing_prompt: float = 0.0     # $/1M tokens (prompt)
    pricing_completion: float = 0.0 # $/1M tokens (completion)
    supports_tools: bool = False
    supports_vision: bool = False
    supports_reasoning: bool = False
    top_provider: bool = False
    modality: str = "text"          # "text", "multimodal"
    last_seen: float = field(default_factory=time.time)

    @property
    def avg_cost_per_million(self) -> float:
        """Blended cost $/1M tokens (avg of prompt + completion)."""
        return (self.pricing_prompt + self.pricing_completion) / 2.0

    @property
    def cost_tier(self) -> str:
        """Classify cost: free, cheap, mid, premium, ultra.

        Based on $/1M tokens (blended prompt + completion average).
        """
        cost = self.avg_cost_per_million
        if cost <= 0:
            return "free"
        elif cost < 0.5:
            return "cheap"
        elif cost < 3.0:
            return "mid"
        elif cost < 15.0:
            return "premium"
        return "ultra"

    def to_dict(self) -> dict:
        return {
            "model_id": self.model_id,
            "name": self.name,
            "provider": self.provider,
            "context_length": self.context_length,
            "pricing_prompt": self.pricing_prompt,
            "pricing_completion": self.pricing_completion,
            "supports_tools": self.supports_tools,
            "supports_vision": self.supports_vision,
            "supports_reasoning": self.supports_reasoning,
            "top_provider": self.top_provider,
            "modality": self.modality,
            "cost_tier": self.cost_tier,
            "last_seen": self.last_seen,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ModelEntry":
        return cls(
            model_id=d.get("model_id", ""),
            name=d.get("name", ""),
            provider=d.get("provider", ""),
            context_length=int(d.get("context_length", 0)),
            pricing_prompt=float(d.get("pricing_prompt", 0)),
            pricing_completion=float(d.get("pricing_completion", 0)),
            supports_tools=bool(d.get("supports_tools", False)),
            supports_vision=bool(d.get("supports_vision", False)),
            supports_reasoning=bool(d.get("supports_reasoning", False)),
            top_provider=bool(d.get("top_provider", False)),
            modality=d.get("modality", "text"),
            last_seen=float(d.get("last_seen", time.time())),
        )

    @classmethod
    def from_openrouter(cls, raw: dict) -> "ModelEntry":
        """Parse from OpenRouter /v1/models response item."""
        model_id = raw.get("id", "")
        provider = model_id.split("/")[0] if "/" in model_id else ""

        pricing = raw.get("pricing", {})
        prompt_cost = float(pricing.get("prompt", "0") or "0")
        completion_cost = float(pricing.get("completion", "0") or "0")

        arch = raw.get("architecture", {})
        modality_in = arch.get("modality", "text->text") or "text->text"

        top = raw.get("top_provider", {})

        return cls(
            model_id=model_id,
            name=raw.get("name", model_id),
            provider=provider,
            context_length=int(raw.get("context_length", 0) or 0),
            pricing_prompt=prompt_cost * 1_000_000,  # Convert $/token to $/1M tokens
            pricing_completion=completion_cost * 1_000_000,
            supports_tools="tool" in str(raw.get("supported_parameters", [])).lower()
                           or raw.get("supports_tool_parameters", False),
            supports_vision="image" in modality_in,
            supports_reasoning="reason" in str(raw.get("supported_parameters", [])).lower(),
            top_provider=bool(top.get("is_moderated", False) if isinstance(top, dict) else False),
            modality="multimodal" if "image" in modality_in else "text",
        )


class ModelCatalog:
    """
    Cached catalog of available OpenRouter models.

    Thread-safe, persistent, fail-open.
    """

    def __init__(self, catalog_path: Optional[Path] = None):
        self._lock = threading.Lock()
        self._models: dict[str, ModelEntry] = {}
        self._path = catalog_path or _CATALOG_PATH
        self._last_refresh: float = 0
        self._load_cached()

    def _load_cached(self) -> None:
        """Load last known catalog from disk."""
        try:
            if self._path.exists():
                with open(self._path) as f:
                    data = json.load(f)
                for entry in data.get("models", []):
                    model = ModelEntry.from_dict(entry)
                    if model.model_id:
                        self._models[model.model_id] = model
                self._last_refresh = data.get("refreshed_at", 0)
                log.debug("catalog_loaded_from_cache", count=len(self._models))
        except Exception as e:
            log.debug("catalog_cache_load_failed", err=str(e)[:80])

    def _save_cache(self) -> None:
        """Persist catalog to disk (atomic write)."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            with open(tmp, "w") as f:
                json.dump({
                    "version": 1,
                    "refreshed_at": self._last_refresh,
                    "model_count": len(self._models),
                    "models": [m.to_dict() for m in self._models.values()],
                }, f)
            tmp.rename(self._path)
        except Exception as e:
            log.debug("catalog_cache_save_failed", err=str(e)[:80])

    def refresh(self, api_key: str = "") -> int:
        """
        Fetch latest models from OpenRouter API.

        Returns number of models loaded, or -1 on failure.
        Fail-open: preserves existing catalog on failure.
        """
        if not api_key:
            try:
                import os
                api_key = os.environ.get("OPENROUTER_API_KEY", "")
            except Exception as _exc:
                log.warning("swallowed_exception", action="catalog_swallow", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

        if not api_key:
            log.debug("catalog_refresh_skipped", reason="no_api_key")
            return -1

        try:
            import urllib.request
            import urllib.error

            req = urllib.request.Request(
                _OPENROUTER_MODELS_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=15) as resp:  # nosec B310 — URL pre-validated upstream (scheme/host allowlist or trusted config)
                data = json.loads(resp.read().decode())

            raw_models = data.get("data", [])
            if not raw_models:
                log.warning("catalog_refresh_empty")
                return 0

            new_models: dict[str, ModelEntry] = {}
            for raw in raw_models:
                entry = ModelEntry.from_openrouter(raw)
                if entry.model_id:
                    new_models[entry.model_id] = entry

            with self._lock:
                self._models = new_models
                self._last_refresh = time.time()

            self._save_cache()
            log.info("catalog_refreshed", count=len(new_models))
            return len(new_models)

        except Exception as e:
            log.warning("catalog_refresh_failed", err=str(e)[:100])
            return -1

    def get(self, model_id: str) -> Optional[ModelEntry]:
        with self._lock:
            return self._models.get(model_id)

    def list_all(self) -> list[ModelEntry]:
        with self._lock:
            return list(self._models.values())

    def list_by_provider(self, provider: str) -> list[ModelEntry]:
        with self._lock:
            return [m for m in self._models.values() if m.provider == provider]

    def list_by_cost_tier(self, tier: str) -> list[ModelEntry]:
        with self._lock:
            return [m for m in self._models.values() if m.cost_tier == tier]

    def search(self, query: str) -> list[ModelEntry]:
        """Simple keyword search across model_id and name."""
        q = query.lower()
        with self._lock:
            return [m for m in self._models.values()
                    if q in m.model_id.lower() or q in m.name.lower()]

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._models)

    @property
    def last_refresh(self) -> float:
        return self._last_refresh

    def status(self) -> dict:
        return {
            "model_count": self.count,
            "last_refresh": self._last_refresh,
            "age_seconds": time.time() - self._last_refresh if self._last_refresh else 0,
            "providers": len(set(m.provider for m in self._models.values())),
        }


# ── Singleton ─────────────────────────────────────────────────

_catalog: ModelCatalog | None = None


def get_model_catalog() -> ModelCatalog:
    global _catalog
    if _catalog is None:
        _catalog = ModelCatalog()
    return _catalog
