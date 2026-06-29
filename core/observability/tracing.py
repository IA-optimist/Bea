"""OpenTelemetry tracing shim for Bea.

The dependency is optional. When `opentelemetry-sdk` is installed and
`OTEL_EXPORTER_OTLP_ENDPOINT` or `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` is set,
spans are exported over OTLP/gRPC. Otherwise the tracer is still configured
locally so code can create spans without wrapping everything in conditionals.

Usage:
    from core.observability.tracing import trace_span, tracer
    with trace_span("my_operation", {"attr": "value"}):
        ...
"""
from __future__ import annotations

import contextlib
import functools
import os
from typing import Any, Callable

_OTEL_AVAILABLE = False
try:
    from opentelemetry import trace as _otel_trace
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    _OTEL_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    _otel_trace = None  # type: ignore

try:
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

    _OTLP_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    _OTLP_AVAILABLE = False


_SERVICE_NAME = os.environ.get("OTEL_SERVICE_NAME", "bea-max")
_provider: Any | None = None


def init_tracing(service_name: str | None = None) -> Any | None:
    """Initialize the OpenTelemetry tracer provider.

    Returns the provider if OTel SDK is installed, otherwise None.
    """
    global _provider
    if not _OTEL_AVAILABLE:
        return None

    name = service_name or _SERVICE_NAME
    resource = Resource.create({SERVICE_NAME: name})
    _provider = TracerProvider(resource=resource)
    _otel_trace.set_tracer_provider(_provider)

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or os.environ.get(
        "OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    if endpoint and _OTLP_AVAILABLE:
        try:
            exporter = OTLPSpanExporter(endpoint=endpoint)
            _provider.add_span_processor(BatchSpanProcessor(exporter))
        except Exception as exc:  # pragma: no cover - network/config issue
            import logging

            logging.getLogger(__name__).warning("otel_exporter_init_failed: %s", exc)

    return _provider


def shutdown_tracing() -> None:
    """Flush and shutdown the tracer provider if it exists."""
    global _provider
    if _provider is not None and hasattr(_provider, "shutdown"):
        try:
            _provider.shutdown()
        except Exception:  # pragma: no-except-gate
            pass
    _provider = None


def tracer(name: str = "bea"):
    """Return an OpenTelemetry tracer for ``name``.

    Falls back to a no-op tracer if the OTel SDK is not installed.
    """
    if _OTEL_AVAILABLE:
        return _otel_trace.get_tracer(name)
    return _NoOpTracer()


@contextlib.contextmanager
def trace_span(name: str, attributes: dict[str, Any] | None = None):
    """Start a span around a block of code.

    No-op when OTel is unavailable.
    """
    t = tracer("bea")
    with t.start_as_current_span(name) as span:
        if attributes:
            for key, value in attributes.items():
                span.set_attribute(key, value)
        yield span


def trace_function(name: str | None = None):
    """Decorator to trace a function call."""

    def decorator(func: Callable) -> Callable:
        span_name = name or func.__qualname__

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with trace_span(span_name, {"function": func.__qualname__}):
                return func(*args, **kwargs)

        return wrapper

    return decorator


class _NoOpTracer:
    """Fallback tracer when the OpenTelemetry SDK is absent."""

    class _NoOpSpan:
        def set_attribute(self, *args: Any, **kwargs: Any) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args: Any) -> None:
            pass

    def start_as_current_span(self, name: str):
        return self._NoOpSpan()

    def start_span(self, name: str):
        return self._NoOpSpan()
