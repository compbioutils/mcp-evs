"""The request middleware chain (proposal 10.1), outermost first:

correlation id -> authentication binding -> scope check -> per-client rate limit ->
audit record + metrics. Release context and cache hints live inside the tool handlers.

Implemented as one FastMCP ``Middleware`` whose ``on_call_tool`` runs the steps in order,
so ordering is explicit and testable. Rejections are returned as tool errors carrying the
JSON error envelope (``permission_denied`` / ``rate_limited``), never as protocol errors.

FastMCP's middleware API (``fastmcp.server.middleware``) is imported defensively: on a
FastMCP without it the chain degrades to no-ops and a warning is logged.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from typing import Any

import structlog

from ..core.audit import AuditRecord, AuditSink, now_iso, redact
from ..core.auth import Principal, current_principal, profile_scopes, required_scopes
from ..core.config import Settings
from ..core.databricks import request_principal
from ..core.errors import EvsMcpError
from ..core.metrics import METRICS
from ..core.ratelimit import RateLimiter
from ..core.toolkit import CORRELATION_ID, LAST_OUTCOME

log = structlog.get_logger(__name__)

try:  # FastMCP >= 2.9
    from fastmcp.exceptions import ToolError
    from fastmcp.server.middleware import Middleware as _Base
except ImportError:  # pragma: no cover
    _Base = object  # type: ignore[assignment,misc]
    ToolError = Exception  # type: ignore[assignment,misc]


def _anonymous_key() -> str:
    """Rate-limit key for callers without a token: their client address over HTTP, one shared bucket on stdio."""
    try:
        from fastmcp.server.dependencies import get_http_request

        request = get_http_request()
    except Exception:  # noqa: BLE001 - no HTTP request in context (stdio, in-memory)
        return "anonymous"
    host = request.client.host if request.client else None
    return f"ip:{host}" if host else "anonymous"


class PlatformMiddleware(_Base):  # type: ignore[misc]
    def __init__(self, settings: Settings, *, audit_sink: AuditSink | None, limiter: RateLimiter) -> None:
        self.settings = settings
        self.audit_sink = audit_sink
        self.limiter = limiter
        self.allowed = profile_scopes(settings.profile)

    # ------------------------------------------------------------- helpers
    def _principal(self) -> Principal:
        """The verified token's principal, or in a Databricks App the caller its proxy authenticated."""
        if self.settings.auth_mode == "databricks":
            return request_principal(self.allowed)
        return current_principal()

    def _correlation_id(self, context: Any) -> str:
        meta = None
        msg = getattr(context, "message", None)
        params = getattr(msg, "params", None) or msg
        for holder in (params, msg):
            m = getattr(holder, "meta", None) or getattr(holder, "_meta", None)
            if isinstance(m, dict):
                meta = m
                break
        if meta:
            for key in ("correlationId", "traceparent", "x-correlation-id"):
                v = meta.get(key)
                if isinstance(v, str) and 8 <= len(v) <= 128:
                    return v.split("-")[1] if key == "traceparent" and v.count("-") >= 2 else v
        return uuid.uuid4().hex

    def _check_scopes(self, tool: str, principal: Principal) -> None:
        if not self.settings.scope_enforcement:
            return
        need = required_scopes(tool) & self.allowed
        missing = sorted(need - principal.scopes)
        if missing:
            METRICS.inc("ecm_scope_denials_total", {"tool": tool})
            raise EvsMcpError("permission_denied", "token lacks the scope(s) required for this tool", details={"missing": missing, "required": sorted(need)})

    def _check_rate(self, principal: Principal) -> None:
        key = principal.client_id or principal.subject or _anonymous_key()
        allowed, retry_after = self.limiter.allow(key)
        if not allowed:
            METRICS.inc("ecm_rate_limit_rejections_total", {"client": hashlib.sha256(key.encode()).hexdigest()[:12]})
            raise EvsMcpError("rate_limited", "per-client rate limit exceeded", details={"retryAfterSeconds": retry_after}, retryable=True)

    def _audit(self, *, tool: str, args: dict | None, principal: Principal, cid: str, started: float, outcome: dict[str, Any] | None, error: EvsMcpError | None) -> None:
        elapsed = int((time.perf_counter() - started) * 1000)
        status = "error" if error or (outcome or {}).get("status") == "error" else "ok"
        code = error.code if error else (outcome or {}).get("errorCode")
        METRICS.inc("ecm_tool_calls_total", {"tool": tool, "profile": self.settings.profile, "status": code or status})
        METRICS.observe_ms("ecm_tool_latency_ms", elapsed, {"tool": tool})
        if outcome:
            if outcome.get("outboundRequests") is not None:
                METRICS.inc("ecm_outbound_requests_total", {"tool": tool}, float(outcome["outboundRequests"]))
            if outcome.get("truncated"):
                METRICS.inc("ecm_truncations_total", {"tool": tool, "bound": str(outcome.get("truncationBound"))})
            if outcome.get("servedBy") == "cache":
                METRICS.inc("ecm_cache_hits_total", {"tier": "local_or_shared"})
        if self.audit_sink is None:
            return
        rec = AuditRecord(
            timestamp=now_iso(), correlationId=cid, tool=tool, status=status, errorCode=code,
            subject=principal.subject, clientId=principal.client_id, scopes=sorted(principal.scopes), arguments=redact(args),
            elapsedMs=elapsed, outboundRequests=(outcome or {}).get("outboundRequests"), resultBytes=(outcome or {}).get("resultBytes"),
            truncated=(outcome or {}).get("truncated"), servedBy=(outcome or {}).get("servedBy"), terminology=(outcome or {}).get("terminology"),
            release=(outcome or {}).get("release"), cadsrIds=(outcome or {}).get("cadsrIds") or [],
        )
        try:
            self.audit_sink.write(rec)
        except Exception as exc:  # noqa: BLE001 - audit failure must not fail the request, but is logged loudly
            log.error("audit.write_failed", error=type(exc).__name__, correlation_id=cid)

    # --------------------------------------------------------------- hook
    async def on_call_tool(self, context: Any, call_next: Any) -> Any:
        msg = getattr(context, "message", None)
        tool = getattr(msg, "name", None) or "?"
        args = getattr(msg, "arguments", None)
        cid = self._correlation_id(context)
        token = CORRELATION_ID.set(cid)
        holder: dict[str, Any] = {}
        otoken = LAST_OUTCOME.set(holder)
        started = time.perf_counter()
        principal = self._principal()
        error: EvsMcpError | None = None
        try:
            try:
                self._check_scopes(tool, principal)
                self._check_rate(principal)
            except EvsMcpError as exc:
                error = exc
                raise ToolError(exc.to_json(cid)) from exc
            return await call_next(context)
        finally:
            self._audit(tool=tool, args=args if isinstance(args, dict) else None, principal=principal, cid=cid, started=started, outcome=holder or None, error=error)
            LAST_OUTCOME.reset(otoken)
            CORRELATION_ID.reset(token)


def build_platform_middleware(settings: Settings, *, audit_sink: AuditSink | None) -> PlatformMiddleware | None:
    if _Base is object:  # pragma: no cover
        log.warning("middleware.unavailable", note="installed FastMCP has no server middleware API; scope/rate/audit chain disabled")
        return None
    limiter = RateLimiter(per_minute=settings.rate_limit_per_minute, burst=settings.rate_limit_burst)
    return PlatformMiddleware(settings, audit_sink=audit_sink, limiter=limiter)
