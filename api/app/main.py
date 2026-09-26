"""FastAPI entrypoint."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
    multiprocess,
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app import __version__
from app.config import get_settings
from app.logging import configure_logging, get_logger
from app.routes import accounts as accounts_routes
from app.routes import compare as compare_routes
from app.routes import health, models_api
from app.services.cache import cache

configure_logging()
log = get_logger(__name__)


class _HealthCheckFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return "/readyz" not in msg and "/healthz" not in msg


logging.getLogger("uvicorn.access").addFilter(_HealthCheckFilter())
_settings = get_settings()

REQ_COUNT = Counter(
    "http_requests_total",
    "HTTP requests",
    ["method", "path", "status"],
)
REQ_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "path"],
)


UNMATCHED_ROUTE = "__unmatched__"


def _route_label(request: Request) -> str:
    """Return the matched route template (e.g. ``/models/{model_id:path}``).

    Labelling by the raw URL path would create a new Prometheus series for
    every model id and every scanner 404, growing memory without bound. The
    router stores the matched route on the ASGI scope, which is shared with
    this middleware, so it is available once ``call_next`` returns.
    """
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else UNMATCHED_ROUTE


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        start = time.perf_counter()
        try:
            response: Response = await call_next(request)
        except Exception:
            REQ_COUNT.labels(request.method, _route_label(request), "500").inc()
            raise
        elapsed = time.perf_counter() - start
        route = _route_label(request)
        REQ_LATENCY.labels(request.method, route).observe(elapsed)
        REQ_COUNT.labels(request.method, route, str(response.status_code)).inc()
        return response


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    log.info("startup", version=__version__, env=_settings.environment)
    yield
    await cache.close()
    log.info("shutdown")


app = FastAPI(
    title="Model Pricing API",
    version=__version__,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)
app.add_middleware(MetricsMiddleware)

app.include_router(health.router)
app.include_router(models_api.router)
app.include_router(compare_routes.router)
app.include_router(compare_routes.kilo_router)
app.include_router(accounts_routes.router)


@app.get("/metrics")
async def metrics() -> Response:
    # Uvicorn runs one worker per pod (scale with replicas), so the default
    # registry is complete. If PROMETHEUS_MULTIPROC_DIR is set for a
    # multi-worker deployment, aggregate across workers instead.
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        data = generate_latest(registry)
    else:
        data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)
