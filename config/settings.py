"""
JARVIS MAX — Configuration centrale
Toutes les variables chargées depuis l'environnement via stdlib os.environ.
Un seul import : from config.settings import get_settings
"""
from __future__ import annotations
import os
import secrets
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

_EPHEMERAL_SECRET_PREFIX = "ephemeral-"


def _default_jarvis_secret() -> str:
    explicit = os.environ.get("JARVIS_SECRET_KEY", "")
    if explicit:
        return explicit
    return f"{_EPHEMERAL_SECRET_PREFIX}{secrets.token_urlsafe(32)}"


def _detect_workspace() -> Path:
    """Détecte le répertoire workspace selon l'environnement.
    Priorité : env WORKSPACE_DIR > JARVIS_ROOT/workspace > chemin relatif au projet > /app/workspace
    """
    if ws := os.getenv("WORKSPACE_DIR"):
        return Path(ws)
    if root := os.getenv("JARVIS_ROOT"):
        return Path(root) / "workspace"
    # Dev local : remonter depuis config/settings.py → racine projet → workspace/
    here = Path(__file__).resolve().parent.parent
    candidate = here / "workspace"
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate


def _b(key: str, default: str = "false") -> bool:
    return os.environ.get(key, default).lower() in ("1", "true", "yes")


def _i(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, str(default)))
    except (ValueError, TypeError):
        return default


@dataclass
class Settings:

    # ── Identité ──────────────────────────────────────────────
    jarvis_name:       str = field(default_factory=lambda: os.environ.get("JARVIS_NAME", "JarvisMax"))
    jarvis_version:    str = field(default_factory=lambda: os.environ.get("JARVIS_VERSION", "1.0.0"))
    jarvis_secret_key: str = field(default_factory=_default_jarvis_secret)
    jarvis_admin_password: str = field(default_factory=lambda: os.environ.get("JARVIS_ADMIN_PASSWORD", ""))
    jarvis_api_token: str = field(default_factory=lambda: os.environ.get("JARVIS_API_TOKEN", ""))
    qdrant_api_key: str = field(default_factory=lambda: os.environ.get("QDRANT_API_KEY", ""))

    # ── Chemins ───────────────────────────────────────────────
    workspace_dir: Path = field(default_factory=_detect_workspace)
    logs_dir:      Path = field(default_factory=lambda: _detect_workspace().parent / "logs")
    jarvis_root:   Path = field(default_factory=lambda: _detect_workspace().parent)

    @property
    def projects_dir(self) -> Path: return self.workspace_dir / "projects"
    @property
    def reports_dir(self) -> Path:  return self.workspace_dir / "reports"
    @property
    def missions_dir(self) -> Path: return self.workspace_dir / "missions"
    @property
    def patches_dir(self) -> Path:  return self.workspace_dir / "patches"
    @property
    def backups_dir(self) -> Path:  return self.workspace_dir / ".backups"

    # ── OpenAI ────────────────────────────────────────────────
    openai_api_key:    str = field(default_factory=lambda: os.environ.get("OPENAI_API_KEY", ""))
    openai_model:      str = field(default_factory=lambda: os.environ.get("OPENAI_MODEL", "gpt-4o"))
    openai_model_fast: str = field(default_factory=lambda: os.environ.get("OPENAI_MODEL_FAST", "gpt-4o-mini"))

    # ── Anthropic ─────────────────────────────────────────────
    anthropic_api_key: str = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", ""))
    anthropic_model:   str = field(default_factory=lambda: os.environ.get("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022"))

    # Escalade cloud (optionnel)
    escalation_enabled:  bool = field(default_factory=lambda: _b("ESCALATION_ENABLED"))
    escalation_provider: str  = field(default_factory=lambda: os.environ.get("ESCALATION_PROVIDER", "claude"))

    # ── Google ────────────────────────────────────────────────
    google_api_key: str = field(default_factory=lambda: os.environ.get("GOOGLE_API_KEY", ""))

    # ── OpenRouter (multi-model cloud gateway) ─────────────────────────────────
    openrouter_api_key:     str = field(default_factory=lambda: os.environ.get("OPENROUTER_API_KEY", ""))
    openrouter_base_url:    str = field(default_factory=lambda: os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"))
    openrouter_model_fast:  str = field(default_factory=lambda: os.environ.get("OPENROUTER_MODEL_FAST", "mistralai/mistral-7b-instruct"))
    openrouter_model_standard: str = field(default_factory=lambda: os.environ.get("OPENROUTER_MODEL_STANDARD", "anthropic/claude-3.5-haiku"))
    openrouter_model_strong:   str = field(default_factory=lambda: os.environ.get("OPENROUTER_MODEL_STRONG", "anthropic/claude-sonnet-4"))

    # ── Role-based model strategy (OpenRouter) ─────────────────────────────────
    orchestrator_model:     str = field(default_factory=lambda: os.environ.get("ORCHESTRATOR_MODEL", "anthropic/claude-sonnet-4.5"))
    architect_model:        str = field(default_factory=lambda: os.environ.get("ARCHITECT_MODEL", "anthropic/claude-sonnet-4.5"))
    coder_model:            str = field(default_factory=lambda: os.environ.get("CODER_MODEL", "anthropic/claude-sonnet-4.5"))
    self_improvement_model: str = field(default_factory=lambda: os.environ.get("SELF_IMPROVEMENT_MODEL", "anthropic/claude-sonnet-4.5"))
    fast_model:             str = field(default_factory=lambda: os.environ.get("FAST_MODEL", "openai/gpt-4o-mini"))
    fallback_model:         str = field(default_factory=lambda: os.environ.get("FALLBACK_MODEL", "openai/gpt-4o-mini"))
    vision_model_or:        str = field(default_factory=lambda: os.environ.get("VISION_MODEL", "openai/gpt-4o-mini"))
    experimental_agent_model: str = field(default_factory=lambda: os.environ.get("EXPERIMENTAL_AGENT_MODEL", ""))

    google_model:   str = field(default_factory=lambda: os.environ.get("GOOGLE_MODEL", "gemini-1.5-pro"))

    # ── Stratégie LLM ─────────────────────────────────────────
    model_strategy: str = field(default_factory=lambda: os.environ.get("MODEL_STRATEGY", "openai"))
    model_fallback: str = field(default_factory=lambda: os.environ.get("MODEL_FALLBACK", "ollama"))

    # NOTE: openrouter_api_key is defined once above (line 83). Do NOT re-declare it here.
    # Role-based model selection is handled by LLMFactory.ROLE_TO_OPENROUTER_MODEL
    # (core/llm_factory.py), not by individual settings fields.

    # ── Ollama ────────────────────────────────────────────────
    ollama_host:              str = field(default_factory=lambda: os.environ.get("OLLAMA_HOST", "http://ollama:11434"))
    ollama_model_main:        str = field(default_factory=lambda: os.environ.get("OLLAMA_MODEL_MAIN", "mistral:7b"))
    ollama_model_code:        str = field(default_factory=lambda: os.environ.get("OLLAMA_MODEL_CODE", "deepseek-coder-v2:16b"))
    ollama_model_fast:        str = field(default_factory=lambda: os.environ.get("OLLAMA_MODEL_FAST", "mistral:7b"))
    ollama_model_vision:      str = field(default_factory=lambda: os.environ.get("OLLAMA_MODEL_VISION", "llava:7b"))
    ollama_model_uncensored:  str = field(default_factory=lambda: os.environ.get("OLLAMA_MODEL_UNCENSORED", "dolphin-mixtral"))
    uncensored_mode:          bool = field(default_factory=lambda: _b("UNCENSORED_MODE", "false"))

    # ── PostgreSQL ────────────────────────────────────────────
    postgres_host:     str = field(default_factory=lambda: os.environ.get("POSTGRES_HOST", "postgres"))
    postgres_user:     str = field(default_factory=lambda: os.environ.get("POSTGRES_USER", "jarvis"))
    postgres_password: str = field(default_factory=lambda: os.environ.get("POSTGRES_PASSWORD", ""))
    postgres_db:       str = field(default_factory=lambda: os.environ.get("POSTGRES_DB", "jarvis"))

    @property
    def database_url(self) -> str | None:
        """Database URL for asyncpg (raw postgresql:// without +asyncpg).

        Returns None if no postgres host is configured (triggers SQLite fallback).
        Modules should use: dsn = settings.database_url or settings.pg_dsn
        asyncpg needs the raw format, SQLAlchemy needs +asyncpg.
        """
        env_url = os.environ.get("DATABASE_URL")
        if env_url:
            # Strip +asyncpg if present (asyncpg wants raw postgresql://)
            return env_url.replace("postgresql+asyncpg://", "postgresql://")
        if self.postgres_host and self.postgres_password:
            return (
                f"postgresql://{self.postgres_user}:{self.postgres_password}"
                f"@{self.postgres_host}/{self.postgres_db}"
            )
        return None

    @property
    def pg_dsn(self) -> str:
        """SQLAlchemy-compatible DSN (with +asyncpg driver prefix)."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}/{self.postgres_db}"
        )

    @property
    def pg_dsn_sync(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}/{self.postgres_db}"
        )

    # ── Redis ─────────────────────────────────────────────────
    redis_host:     str = field(default_factory=lambda: os.environ.get("REDIS_HOST", "redis"))
    redis_password: str = field(default_factory=lambda: os.environ.get("REDIS_PASSWORD", ""))

    @property
    def redis_url(self) -> str:
        return f"redis://:{self.redis_password}@{self.redis_host}:6379/0"

    # ── Qdrant ────────────────────────────────────────────────
    qdrant_host:    str = field(default_factory=lambda: os.environ.get("QDRANT_HOST", "qdrant"))
    qdrant_port:    int = field(default_factory=lambda: _i("QDRANT_PORT", 6333))
    # API key Qdrant — fortement recommandé en production.
    # Défini via QDRANT_API_KEY dans .env (doit correspondre à QDRANT__SERVICE__API_KEY dans docker-compose).
    qdrant_api_key: str = field(default_factory=lambda: os.environ.get("QDRANT_API_KEY", ""))

    # ── n8n ───────────────────────────────────────────────────
    n8n_host:                str = field(default_factory=lambda: os.environ.get("N8N_HOST", "http://n8n:5678"))
    n8n_basic_auth_user:     str = field(default_factory=lambda: os.environ.get("N8N_BASIC_AUTH_USER", "admin"))
    n8n_basic_auth_password: str = field(default_factory=lambda: os.environ.get("N8N_BASIC_AUTH_PASSWORD", ""))

    # ── MCP Server (expose Jarvis tools via MCP protocol) ────────────────────
    # MCP_SERVER_ENABLED=true  → démarrer le serveur FastMCP sur MCP_SERVER_PORT
    # Dépendance : pip install mcp>=1.0.0
    mcp_server_enabled: bool = field(default_factory=lambda: _b("MCP_SERVER_ENABLED"))
    mcp_server_host:    str  = field(default_factory=lambda: os.environ.get("MCP_SERVER_HOST", "0.0.0.0"))
    mcp_server_port:    int  = field(default_factory=lambda: _i("MCP_SERVER_PORT", 8765))

    # ── Qdrant MCP sidecar ────────────────────────────────────────────────────
    # QDRANT_MCP_ENABLED=true  → enregistrer le sidecar qdrant-mcp dans MCPRegistry
    # QDRANT_MCP_URL           → endpoint du sidecar (ex: http://qdrant-mcp:8000)
    qdrant_mcp_enabled: bool = field(default_factory=lambda: _b("QDRANT_MCP_ENABLED"))
    qdrant_mcp_url:     str  = field(default_factory=lambda: os.environ.get("QDRANT_MCP_URL", "http://qdrant-mcp:8000"))

    # ── Composio connector ────────────────────────────────────────────────────
    # COMPOSIO_ENABLED=true    → activer le connecteur Composio (250+ intégrations)
    # COMPOSIO_API_KEY         → clé API Composio (https://app.composio.dev)
    composio_enabled: bool = field(default_factory=lambda: _b("COMPOSIO_ENABLED"))
    composio_api_key: str  = field(default_factory=lambda: os.environ.get("COMPOSIO_API_KEY", ""))

    # ── GitHub MCP sidecar ────────────────────────────────────────────────────
    # GITHUB_MCP_ENABLED=true  → enregistrer le sidecar github-mcp dans MCPRegistry
    # GITHUB_MCP_URL           → endpoint du sidecar (ex: http://github-mcp:3000)
    github_mcp_enabled: bool = field(default_factory=lambda: _b("GITHUB_MCP_ENABLED"))
    github_mcp_url:     str  = field(default_factory=lambda: os.environ.get("GITHUB_MCP_URL", "http://github-mcp:3000"))

    # ── Sécurité ──────────────────────────────────────────────
    dry_run:          bool = field(default_factory=lambda: _b("DRY_RUN"))
    max_auto_actions: int  = field(default_factory=lambda: _i("MAX_AUTO_ACTIONS", 25))

    # ── Night Worker ──────────────────────────────────────────
    night_worker_max_cycles:    int = field(default_factory=lambda: _i("NIGHT_WORKER_MAX_CYCLES", 5))
    night_worker_cycle_timeout: int = field(default_factory=lambda: _i("NIGHT_WORKER_CYCLE_TIMEOUT", 300))

    # ── Self-improve ──────────────────────────────────────────
    self_improve_enabled:     bool = field(default_factory=lambda: _b("SELF_IMPROVE_ENABLED", "true"))
    self_improve_max_patches: int  = field(default_factory=lambda: _i("SELF_IMPROVE_MAX_PATCHES", 5))

    # ── Browser ───────────────────────────────────────────────
    browser_headless: bool = field(default_factory=lambda: _b("BROWSER_HEADLESS", "true"))
    browser_timeout:  int  = field(default_factory=lambda: _i("BROWSER_TIMEOUT", 30000))

    # ── Langfuse (observabilité LLM, self-hosted) ─────────────
    langfuse_enabled:    bool = field(default_factory=lambda: _b("LANGFUSE_ENABLED"))
    langfuse_host:       str  = field(default_factory=lambda: os.environ.get("LANGFUSE_HOST", "http://langfuse:3000"))
    langfuse_public_key: str  = field(default_factory=lambda: os.environ.get("LANGFUSE_PUBLIC_KEY", ""))
    langfuse_secret_key: str  = field(default_factory=lambda: os.environ.get("LANGFUSE_SECRET_KEY", ""))

    # ── Mode d'exécution (local | vps) ────────────────────────
    # local : 2 agents max, séquentiel favorisé, pas de Docker obligatoire
    # vps   : 5 agents max, parallélisme contrôlé
    jarvis_mode:      str  = field(default_factory=lambda: os.environ.get("JARVIS_MODE", "local"))
    jarvis_safe_mode: bool = field(default_factory=lambda: _b("JARVIS_SAFE_MODE"))

    # ── ResourceGuard — overrides seuils mémoire (MB libres) ──
    resource_soft_ram_mb: int = field(default_factory=lambda: _i("RESOURCE_SOFT_RAM_MB", 0))
    resource_safe_ram_mb: int = field(default_factory=lambda: _i("RESOURCE_SAFE_RAM_MB", 0))
    resource_hard_ram_mb: int = field(default_factory=lambda: _i("RESOURCE_HARD_RAM_MB", 0))
    resource_max_agents:  int = field(default_factory=lambda: _i("RESOURCE_MAX_AGENTS", 0))

    # ── HuggingFace ───────────────────────────────────────────
    huggingface_api_key:  str = field(default_factory=lambda: os.environ.get("HUGGINGFACE_API_KEY", ""))
    embedding_provider:   str = field(default_factory=lambda: os.environ.get("EMBEDDING_PROVIDER", "local"))

    @property
    def production_mode(self) -> bool:
        """True when JARVIS_PRODUCTION=true/1/yes is set."""
        return _b("JARVIS_PRODUCTION")

    @property
    def has_llm_key(self) -> bool:
        """True if at least one LLM provider is available (cloud key OR local Ollama)."""
        has_cloud = bool(self.openai_api_key or self.anthropic_api_key or self.openrouter_api_key)
        has_ollama = bool(getattr(self, 'ollama_host', ''))
        return has_cloud or has_ollama

    def enforce_llm_key(self) -> None:
        """
        Hard-fail if no LLM key is configured and we are not in DRY_RUN mode.

        Called at startup. Raises RuntimeError immediately — no silent drift.
        In DRY_RUN mode the system stubs LLM responses, so no key is needed.

        Override at startup by setting DRY_RUN=true (dev/test only).
        """
        if self.dry_run:
            return  # DRY_RUN=true: stubs LLM calls, no key needed
        if not self.has_llm_key:
            raise RuntimeError(
                "NO LLM KEY CONFIGURED — Jarvis Max cannot serve any mission.\n"
                "Set at least one of:\n"
                "  OPENAI_API_KEY=sk-...\n"
                "  ANTHROPIC_API_KEY=sk-ant-...\n"
                "  OPENROUTER_API_KEY=sk-or-...\n"
                "Or set DRY_RUN=true to start without a key (stubs LLM responses, dev only)."
            )

    def enforce_production_secrets(self) -> None:
        """
        Hard-fail if running in production mode with insecure defaults.

        Call this ONCE at startup, before accepting any request.
        Raises RuntimeError with a clear human-readable message.
        Controlled by JARVIS_PRODUCTION=true env var — never raises in dev.
        """
        if not self.production_mode:
            return
        errors: list[str] = []
        if (
            not self.jarvis_secret_key
            or self.jarvis_secret_key == "change-me-in-production"
            or self.jarvis_secret_key.startswith(_EPHEMERAL_SECRET_PREFIX)
        ):
            errors.append(
                "JARVIS_SECRET_KEY is not set (or is an ephemeral default). "
                "Set a cryptographically random value in your .env file."
            )
        if not self.jarvis_admin_password:
            errors.append(
                "JARVIS_ADMIN_PASSWORD is not set. "
                "Admin auth falls back to JARVIS_SECRET_KEY — set an explicit admin password."
            )
        if not self.jarvis_api_token:
            errors.append(
                "JARVIS_API_TOKEN is not set. "
                "All API endpoints are unauthenticated in production."
            )
        if errors:
            raise RuntimeError(
                "PRODUCTION STARTUP BLOCKED — insecure configuration detected:\n"
                + "\n".join(f"  • {e}" for e in errors)
                + "\nFix these issues or unset JARVIS_PRODUCTION to run in dev mode."
            )

    def validate_security(self) -> list[str]:
        """Retourne la liste des avertissements de sécurité (secrets non configurés).
        Ne bloque pas le démarrage — log uniquement.
        Pour un hard-fail en production, appeler enforce_production_secrets()."""
        warnings: list[str] = []
        if (
            not self.jarvis_secret_key
            or self.jarvis_secret_key == "change-me-in-production"
            or self.jarvis_secret_key.startswith(_EPHEMERAL_SECRET_PREFIX)
        ):
            warnings.append("JARVIS_SECRET_KEY is not set (ephemeral default in use) — override it in production")
        if not self.jarvis_admin_password:
            warnings.append(
                "JARVIS_ADMIN_PASSWORD is not set — admin login falls back to JARVIS_SECRET_KEY. "
                "Set JARVIS_ADMIN_PASSWORD explicitly for production."
            )
        if not self.jarvis_api_token:
            warnings.append(
                "JARVIS_API_TOKEN is not set — all API endpoints are unauthenticated. "
                "Set JARVIS_API_TOKEN in .env for any non-local deployment."
            )
        if not self.openai_api_key and not self.anthropic_api_key and not self.openrouter_api_key:
            warnings.append("No LLM API key configured (OPENAI_API_KEY / ANTHROPIC_API_KEY / OPENROUTER_API_KEY)")
        if not self.qdrant_api_key:
            warnings.append(
                "QDRANT_API_KEY is not set — Qdrant vector store has no authentication. "
                "Set QDRANT_API_KEY in .env for production deployments."
            )
        return warnings

    def ensure_dirs(self):
        for d in [
            self.workspace_dir, self.logs_dir,
            self.projects_dir, self.reports_dir,
            self.missions_dir, self.patches_dir,
            self.backups_dir,
        ]:
            d.mkdir(parents=True, exist_ok=True)

    def get_llm(self, role: str = "default"):
        from core.llm_factory import LLMFactory
        # Singleton factory pour reutiliser le cache LLM entre appels
        if not hasattr(self, "_llm_factory"):
            object.__setattr__(self, "_llm_factory", LLMFactory(self))
        return self._llm_factory.get(role)


@lru_cache
def get_settings() -> Settings:
    return Settings()
