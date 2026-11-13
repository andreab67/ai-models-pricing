"""Optional metadata-only native Langfuse traces via the public OTel SDK."""

from __future__ import annotations

import atexit
import base64
import json
import logging
import os
import ssl
import threading
from contextlib import contextmanager

log = logging.getLogger("model-pricing.telemetry")
DEFAULT_HOST = "https://langfuse.andrea-house.com"
EXPORT_TIMEOUT_SECONDS = 2
SHUTDOWN_TIMEOUT_SECONDS = 2
MAX_QUEUE_SIZE = 128
MAX_EXPORT_BATCH_SIZE = 16
_runtime = None
_initialized = False
_lock = threading.Lock()
_warned = False


def _warn() -> None:
    global _warned
    if not _warned:
        _warned = True
        log.warning("optional extraction telemetry unavailable")


def _build_runtime(public: str, secret: str, host: str):
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    ca_file = os.environ.get("LANGFUSE_CA_FILE", "").strip() or None
    if ca_file is not None:
        # Validate before creating threads. Trust is scoped to this exporter.
        ssl.create_default_context(cafile=ca_file)
    authorization = base64.b64encode(f"{public}:{secret}".encode()).decode("ascii")
    exporter = OTLPSpanExporter(
        endpoint=host + "/api/public/otel/v1/traces",
        headers={"Authorization": "Basic " + authorization, "x-langfuse-ingestion-version": "4"},
        certificate_file=ca_file,
        timeout=EXPORT_TIMEOUT_SECONDS,
    )
    provider = TracerProvider(
        resource=Resource.create({"service.name": "model-pricing"}), shutdown_on_exit=False
    )
    provider.add_span_processor(
        BatchSpanProcessor(
            exporter,
            max_queue_size=MAX_QUEUE_SIZE,
            max_export_batch_size=MAX_EXPORT_BATCH_SIZE,
            schedule_delay_millis=1000,
            export_timeout_millis=EXPORT_TIMEOUT_SECONDS * 1000,
        )
    )
    return provider, provider.get_tracer("model-pricing.extraction")


def _get_runtime():
    global _runtime, _initialized
    if _initialized:
        return _runtime
    public = os.environ.get("LANGFUSE_PUBLIC_KEY", "").strip()
    secret = os.environ.get("LANGFUSE_SECRET_KEY", "").strip()
    if not public or not secret:
        return None
    with _lock:
        if not _initialized:
            _initialized = True
            host = (os.environ.get("LANGFUSE_HOST", "").strip() or DEFAULT_HOST).rstrip("/")
            if host != DEFAULT_HOST:
                _warn()
                return None
            try:
                _runtime = _build_runtime(public, secret, host)
            except Exception:  # noqa: BLE001 - optional telemetry cannot replace the application result
                _warn()
                return None
            atexit.register(shutdown)
    return _runtime


def shutdown() -> None:
    """Bound only this provider's drain; never change another atexit callback."""
    global _runtime, _initialized
    with _lock:
        runtime, _runtime = _runtime, None
        _initialized = True
    if runtime is None:
        return

    def drain():
        try:
            runtime[0].shutdown()
        except Exception:  # noqa: BLE001 - optional telemetry cannot replace the application result
            _warn()

    thread = threading.Thread(target=drain, name="pricing-telemetry-shutdown", daemon=True)
    thread.start()
    thread.join(SHUTDOWN_TIMEOUT_SECONDS)
    if thread.is_alive():
        _warn()


@contextmanager
def generation(context, model: str):
    """Record only local template identity/model/timing; no exception text or I/O."""
    runtime = _get_runtime()
    span = None
    if runtime is not None:
        try:
            span = runtime[1].start_span(
                "kilo-pricing-extraction",
                attributes={
                    "langfuse.observation.type": "generation",
                    "langfuse.observation.model.name": model,
                    "langfuse.trace.name": "kilo-pricing-extraction",
                    "langfuse.observation.metadata.purpose": "pricing_extraction",
                    "langfuse.observation.metadata.context_provenance": json.dumps(
                        context.metadata()
                    ),
                },
            )
        except Exception:  # noqa: BLE001 - optional telemetry cannot replace the application result
            _warn()
    try:
        yield
    except BaseException as exc:
        if span is not None:
            try:
                span.set_attribute("langfuse.observation.level", "ERROR")
                span.set_attribute("langfuse.observation.status_message", type(exc).__name__)
            except Exception:  # noqa: BLE001 - optional telemetry cannot replace the application result
                _warn()
        raise
    finally:
        if span is not None:
            try:
                span.end()
            except Exception:  # noqa: BLE001 - optional telemetry cannot replace the application result
                _warn()
