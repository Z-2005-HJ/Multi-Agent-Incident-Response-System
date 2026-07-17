from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.routes import router
from app.job_queue import RedisJobQueue
from app.observability import prometheus_metrics_response, record_http_request
from app.rate_limit import RateLimiter
from app.runtime import get_runtime_settings
from app.security import ensure_runtime_settings_are_safe
from app.storage import IncidentStore


settings = get_runtime_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_runtime_settings_are_safe(settings)
    app.state.incident_store = IncidentStore(settings.database_url)
    app.state.job_queue = RedisJobQueue(settings.redis_url)
    app.state.rate_limiter = RateLimiter(settings.redis_url)
    await app.state.incident_store.initialize()
    await app.state.job_queue.initialize()
    await app.state.rate_limiter.initialize()
    try:
        yield
    finally:
        await app.state.rate_limiter.close()
        await app.state.job_queue.close()
        await app.state.incident_store.dispose()


app = FastAPI(
    title="Multi-Agent Incident Response System",
    version="0.1.0",
    description="MVP backend for multi-agent incident analysis and reporting.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
if settings.allowed_hosts:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
app.include_router(router)


def _request_path(request: Request) -> str:
    route = request.scope.get("route")
    if route is not None and getattr(route, "path", None):
        return str(route.path)
    return request.url.path


@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    started_at = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        record_http_request(
            method=request.method,
            path=_request_path(request),
            status_code=500,
            duration_seconds=time.perf_counter() - started_at,
        )
        raise

    record_http_request(
        method=request.method,
        path=_request_path(request),
        status_code=response.status_code,
        duration_seconds=time.perf_counter() - started_at,
    )
    return response


def _client_identifier(request: Request) -> str:
    if settings.trust_proxy_headers:
        forwarded_for = request.headers.get("x-forwarded-for", "")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if not settings.rate_limit_enabled or request.url.path in {"/health", "/ready", "/metrics"}:
        return await call_next(request)
    allowed, retry_after = await request.app.state.rate_limiter.hit(
        scope="http",
        subject=_client_identifier(request),
        limit=settings.rate_limit_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )
    if not allowed:
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": str(retry_after)},
            content={"detail": "Rate limit exceeded. Please retry later."},
        )
    return await call_next(request)


@app.middleware("http")
async def request_body_limit_middleware(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH"}:
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > settings.max_request_body_bytes:
                    return JSONResponse(
                        status_code=413,
                        content={"detail": "Request body exceeds the configured limit."},
                    )
            except ValueError:
                pass
        else:
            body = await request.body()
            if len(body) > settings.max_request_body_bytes:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Request body exceeds the configured limit."},
                )
    return await call_next(request)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.get("/metrics", include_in_schema=False)
def metrics():
    return prometheus_metrics_response()
