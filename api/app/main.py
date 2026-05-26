"""FastAPI entrypoint."""

from __future__ import annotations

import logging
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


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        import time as _t

        start = _t.perf_counter()
        try:
            response: Response = await call_next(request)
        except Exception:
            REQ_COUNT.labels(request.method, request.url.path, "500").inc()
            raise
        elapsed = _t.perf_counter() - start
        REQ_LATENCY.labels(request.method, request.url.path).observe(elapsed)
        REQ_COUNT.labels(
            request.method, request.url.path, str(response.status_code)
        ).inc()
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
    registry = CollectorRegistry()
    try:
        multiprocess.MultiProcessCollector(registry)
        data = generate_latest(registry)
    except (ValueError, KeyError):
        data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)
