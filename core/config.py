"""Minimal config for LLM factory (Phase 5.3 hotfix)."""
from __future__ import annotations

import os

class Settings:
    """Minimal settings class."""
    def __init__(self) -> None:
        self.openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
        self.anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.openai_key = os.getenv("OPENAI_API_KEY", "")
        self.ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")

_settings_instance: Settings | None = None

def get_settings() -> Settings:
    """Get singleton settings."""
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = Settings()
    return _settings_instance
