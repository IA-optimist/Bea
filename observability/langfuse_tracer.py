"""
JARVIS MAX — Langfuse Tracer
Wrapper optionnel pour tracer chaque appel LLM dans Langfuse (self-hosted).

Architecture :
    LangfuseTracer
    ├── Singleton par instance settings (un client par workspace)
    ├── Totalement silencieux si Langfuse non configuré ou indisponible
    ├── Contexte de trace propagé via session_id + role
    └── Flush automatique à la fin de chaque generation

Activation :
    # .env
    LANGFUSE_ENABLED=true
    LANGFUSE_HOST=http://langfuse:3000
    LANGFUSE_PUBLIC_KEY=pk-lf-...
    LANGFUSE_SECRET_KEY=sk-lf-...

Usage dans LLMFactory :
    tracer = get_tracer(settings)
    with tracer.generation(session_id, role, messages, model_name) as gen:
        resp = await llm.ainvoke(messages)
        gen.finish(output=resp.content, input_tokens=..., output_tokens=...)

Garantie de non-blocage :
    - Si Langfuse est down → contextmanager s'exécute sans rien tracer
    - Si SDK absent → même comportement (ImportError capturé au démarrage)
    - Aucune exception ne remonte vers l'appelant
"""
from __future__ import annotations

import time
import contextlib
from typing import Any, Generator
import structlog

log = structlog.get_logger()


# ── Singleton cache ────────────────────────────────────────────────────────────

_TRACER_CACHE: dict[str, "LangfuseTracer"] = {}


def get_tracer(settings) -> "LangfuseTracer":
    """Retourne le tracer Langfuse singleton pour ce workspace."""
    ws = str(getattr(settings, "workspace_dir", "default"))
    if ws not in _TRACER_CACHE:
        _TRACER_CACHE[ws] = LangfuseTracer(settings)
    return _TRACER_CACHE[ws]


# ── Generation context ─────────────────────────────────────────────────────────

class GenerationContext:
    """
    Contexte d'une generation Langfuse.
    Utilisé comme context manager dans safe_invoke.
    """

    __slots__ = ("_gen", "_t0", "_active")

    def __init__(self, gen=None):
        self._gen    = gen
        self._t0     = time.monotonic()
        self._active = gen is not None

    def finish(
        self,
        output: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
        error: str | None = None,
    ) -> None:
        """Clôt la generation avec le résultat (succès ou erreur)."""
        if not self._active or self._gen is None:
            return
        try:
            int((time.monotonic() - self._t0) * 1000)
            kwargs: dict[str, Any] = {
                "end_time": None,  # Langfuse calculera depuis start_time
                "output":   output[:4000] if output else None,
                "level":    "ERROR" if error else "DEFAULT",
                "status_message": error[:200] if error else None,
            }
            if input_tokens or output_tokens:
                kwargs["usage"] = {
                    "input":  input_tokens,
                    "output": output_tokens,
                    "unit":   "TOKENS",
                }
            self._gen.end(**{k: v for k, v in kwargs.items() if v is not None})
        except Exception as exc:
            log.debug("langfuse_gen_end_failed", err=str(exc)[:80])


# ── Tracer principal ───────────────────────────────────────────────────────────

class LangfuseTracer:
    """
    Tracer Langfuse pour JarvisMax.

    Instanciation :
        tracer = LangfuseTracer(settings)

    Les méthodes ne lèvent JAMAIS d'exception — tout est try/except.
    """

    def __init__(self, settings):
        self.s        = settings
        self._client  = None
        self._enabled = False
        self._init()

    def _init(self) -> None:
        """Initialise le client Langfuse si configuré."""
        try:
            enabled    = getattr(self.s, "langfuse_enabled", False)
            host       = getattr(self.s, "langfuse_host", "")
            public_key = getattr(self.s, "langfuse_public_key", "")
            secret_key = getattr(self.s, "langfuse_secret_key", "")

            if not enabled or not host or not public_key or not secret_key:
                log.debug(
                    "langfuse_disabled",
                    reason="LANGFUSE_ENABLED=false ou clés manquantes",
                )
                return

            from langfuse import Langfuse  # type: ignore[import]
            self._client = Langfuse(
                public_key=public_key,
                secret_key=secret_key,
                host=host,
                enabled=True,
                # Flush toutes les 1s pour ne pas accumuler
                flush_interval=1.0,
                # Timeout court pour ne pas bloquer safe_invoke
                timeout=5,
            )
            self._enabled = True
            log.info("langfuse_tracer_ready", host=host)

        except ImportError:
            log.warning(
                "langfuse_not_installed",
                hint="pip install langfuse pour activer le traçage LLM",
            )
        except Exception as exc:
            log.warning("langfuse_init_failed", err=str(exc)[:120])

    @property
    def enabled(self) -> bool:
        return self._enabled and self._client is not None

    @contextlib.contextmanager
    def generation(
        self,
        session_id: str,
        role: str,
        messages: list,
        model: str = "unknown",
        agent_name: str = "",
    ) -> Generator[GenerationContext, None, None]:
        """
        Context manager : crée une trace + generation Langfuse pour un appel LLM.

        Usage :
            with tracer.generation(sid, "fast", messages, "gpt-4o") as gen:
                resp = await llm.ainvoke(messages)
                gen.finish(output=resp.content)
        """
        if not self.enabled:
            yield GenerationContext(gen=None)
            return

        trace = None
        gen   = None
        try:
            # Sérialiser les messages pour Langfuse
            input_repr = self._serialize_messages(messages)

            trace = self._client.trace(
                name=f"jarvis/{role}",
                session_id=session_id or "no-session",
                tags=[role, agent_name or "unknown", "jarvis"],
                metadata={"agent": agent_name, "role": role},
                input=input_repr,
            )

            gen = trace.generation(
                name=f"safe_invoke/{role}",
                model=model,
                model_parameters={"role": role},
                input=input_repr,
            )
            ctx = GenerationContext(gen=gen)

        except Exception as exc:
            log.debug("langfuse_trace_create_failed", err=str(exc)[:80])
            ctx = GenerationContext(gen=None)

        try:
            yield ctx
        finally:
            # Flush non-bloquant
            if self._client and gen:
                try:
                    self._client.flush()
                except Exception as _exc:
                    log.warning("swallowed_exception", action="langfuse_tracer_1", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    def score_trace(
        self,
        trace_id: str,
        name: str,
        value: float,
        comment: str = "",
    ) -> None:
        """Ajoute un score à une trace (ex: qualité de la réponse LLM)."""
        if not self.enabled or not trace_id:
            return
        try:
            self._client.score(
                trace_id=trace_id,
                name=name,
                value=value,
                comment=comment[:200] if comment else None,
            )
        except Exception as exc:
            log.debug("langfuse_score_failed", err=str(exc)[:80])

    def flush(self) -> None:
        """Force le flush du client (utile avant shutdown)."""
        if self._client:
            try:
                self._client.flush()
            except Exception as _exc:
                log.warning("swallowed_exception", action="langfuse_tracer_2", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    @staticmethod
    def _serialize_messages(messages: list) -> list[dict]:
        """Sérialise les LangChain messages en format Langfuse."""
        result = []
        for m in messages:
            try:
                role    = getattr(m, "type", "unknown")
                content = getattr(m, "content", str(m))
                result.append({"role": role, "content": str(content)[:2000]})
            except Exception:
                result.append({"role": "unknown", "content": str(m)[:200]})
        return result
