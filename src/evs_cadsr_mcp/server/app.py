"""FastAPI host: health/readiness plus the MCP Streamable HTTP app mounted at /mcp.

The mounted sub-app's lifespan does not run on its own, so the FastAPI lifespan
delegates to it (proposal Section 5.5).
"""

from __future__ import annotations

import hmac
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .. import __version__
from ..core.config import Settings, get_settings
from ..core.metrics import METRICS
from .mcp_app import Services, build_mcp_server, configure_logging

MAX_BODY_BYTES = 4 * 1024 * 1024


class BodyLimitMiddleware:
    """Cap request bodies by counting bytes as they arrive, so chunked uploads can't bypass the limit."""

    def __init__(self, app, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        declared = dict(scope.get("headers") or []).get(b"content-length")
        if declared is not None:
            try:
                size = int(declared)
            except ValueError:
                return await Response("invalid content-length", status_code=400)(scope, receive, send)
            if size < 0:
                return await Response("invalid content-length", status_code=400)(scope, receive, send)
            if size > self.max_bytes:
                return await Response("request body too large", status_code=413)(scope, receive, send)
        received = 0
        too_large = False
        forwarded_start = False

        async def limited_receive():
            nonlocal received, too_large
            if too_large:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    # Tell the app the client went away; this middleware answers 413 itself.
                    too_large = True
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message):
            nonlocal forwarded_start
            if too_large:
                return
            if message["type"] == "http.response.start":
                forwarded_start = True
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except Exception:
            if not too_large:
                raise
        if too_large and not forwarded_start:
            await Response("request body too large", status_code=413)(scope, receive, send)


def create_app(settings: Settings | None = None, *, services: Services | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.check_http_exposure()
    configure_logging(settings)
    mcp, services = build_mcp_server(settings, services=services)
    # The MCP endpoint path is set on the sub-app; mounting at "/" after the admin routes
    # keeps /healthz and /readyz on FastAPI and serves MCP at settings.mcp_path (default /mcp).
    mcp_asgi = mcp.http_app(path=settings.mcp_path, stateless_http=settings.http_stateless)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with mcp_asgi.lifespan(app):
            try:
                yield
            finally:
                await services.aclose()

    app = FastAPI(title="EVS + caDSR MCP admin plane", version=__version__, lifespan=lifespan)
    app.state.services = services
    app.state.mcp = mcp

    # Transport security (10.4): Host and Origin allow-lists; disallowed values get 421 (DNS-rebinding defence).
    allowed_hosts = list(dict.fromkeys([*settings.trusted_hosts, settings.public_host]))
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)
    allowed_origins = {o.rstrip("/") for o in settings.allowed_origins}
    app.add_middleware(BodyLimitMiddleware)
    admin_token = settings.admin_token.get_secret_value() if settings.admin_token else ""

    def admin_allowed(request: Request) -> bool:
        """Operational detail is for operators: a matching admin token, or a loopback-only listener."""
        if admin_token:
            supplied = request.headers.get("authorization", "")
            return hmac.compare_digest(supplied.encode(), f"Bearer {admin_token}".encode())
        return settings.binds_loopback()

    @app.middleware("http")
    async def origin_guard(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") not in allowed_origins and "*" not in allowed_origins:
            return Response("origin not allowed", status_code=421)
        return await call_next(request)

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok", "version": __version__, "profile": settings.profile}

    @app.get("/readyz")
    async def readyz(request: Request, response: Response) -> dict:
        try:
            active = await services.registry.active_release(settings.default_terminology)
            live = await services.registry.live_releases(settings.default_terminology)
        except Exception as exc:  # noqa: BLE001 - readiness must not raise
            response.status_code = 503
            return {"status": "not_ready", "reason": type(exc).__name__}
        cache_ok = await services.cache.ready()
        # In a Databricks App, readiness also means the workspace issues the app's service principal a token.
        sp_ok = await services.databricks.ready() if services.databricks is not None else None
        ready = cache_ok and sp_ok is not False
        if not ready:
            response.status_code = 503
        METRICS.gauge("ecm_active_release_info", 1, {"terminology": settings.default_terminology, "release": active.version})
        summary = {
            "status": "ready" if ready else "not_ready",
            "sharedCache": "ok" if cache_ok else "unreachable",
            "activeRelease": active.version,
        }
        if sp_ok is not None:
            summary["servicePrincipal"] = "ok" if sp_ok else "unavailable"
        if not admin_allowed(request):
            return summary
        return {
            **summary,
            "auth": settings.auth_mode,
            "profile": settings.profile,
            "terminology": settings.default_terminology,
            "liveReleases": [r.version for r in live],
            "index": None,  # NCIt retrieval index: not in this first pass
            "cadsr": {"enabled": services.cadsr is not None, "credentialed": settings.cadsr_basic_auth() is not None,
                      "aiMatch": services.ai_http is not None},
            "cache": services.cache.stats(),
            "icdoMappings": services.map.icdo_map.status() if services.map is not None else None,
            "databricksApp": settings.databricks_app_name if settings.auth_mode == "databricks" else None,
        }

    if settings.metrics_enabled:

        @app.get("/metrics")
        async def metrics(request: Request) -> Response:
            if not admin_allowed(request):
                return Response("not found", status_code=404)
            return Response(METRICS.render(), media_type="text/plain; version=0.0.4; charset=utf-8")

    app.mount("/", mcp_asgi)
    return app


app = None  # created lazily by `uvicorn evs_cadsr_mcp.server.app:factory --factory`


def factory() -> FastAPI:
    return create_app()
