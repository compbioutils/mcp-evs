"""Resilient async HTTP client over httpx (proposal Sections 7.1, 10.3).

* per-phase timeouts, bounded concurrency per upstream
* retries with capped exponential backoff + jitter on 429, 5xx and connection errors
* ``Retry-After`` honoured up to 60 s
* every attempt (including retries) draws from the caller's :class:`Budget`
* ``X-Correlation-ID`` on every request; license key header injected only when set,
  never logged, never written into provenance
* upstream error text is never echoed to the model
"""

from __future__ import annotations

import asyncio
import json
import random
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
import structlog

from .budget import Budget
from .config import Settings
from .envelopes import utcnow
from .errors import EvsMcpError

log = structlog.get_logger(__name__)

_RETRY_STATUSES = {429, 500, 502, 503, 504}
_MAX_RETRY_AFTER_S = 60.0
_MAX_RESPONSE_BYTES = 10 * 1024 * 1024
# Paths are built from tool arguments; only plain segments may reach the upstream host.
_SAFE_PATH = re.compile(r"^/?(?:[A-Za-z0-9_.~:@+-]+/?)*$")


def _check_path(path: str) -> None:
    segments = [seg for seg in path.split("/") if seg]
    if not _SAFE_PATH.match(path) or any(seg in (".", "..") for seg in segments):
        raise EvsMcpError("invalid_request", "identifier contains characters that are not allowed")


@dataclass
class HttpResult:
    data: Any
    url: str
    status: int
    retrieved_at: datetime
    attempts: int


class ResilientClient:
    def __init__(
        self,
        settings: Settings,
        *,
        base_url: str,
        transport: httpx.AsyncBaseTransport | None = None,
        read_timeout_s: float | None = None,
        retry_on_429: bool = True,
    ) -> None:
        self._settings = settings
        self._base_url = base_url.rstrip("/")
        self._retry_statuses = set(_RETRY_STATUSES) if retry_on_429 else set(_RETRY_STATUSES) - {429}
        read = read_timeout_s or settings.http_read_timeout_s
        timeout = httpx.Timeout(
            connect=settings.http_connect_timeout_s,
            read=read,
            write=read,
            pool=settings.http_connect_timeout_s,
        )
        headers = {"Accept": "application/json", "User-Agent": settings.evs_user_agent}
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout,
            headers=headers,
            transport=transport,
            follow_redirects=True,
        )
        self._sem = asyncio.Semaphore(settings.http_max_concurrency)

    @property
    def base_url(self) -> str:
        return self._base_url

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _send_capped(
        self, method: str, path: str, *, params: dict[str, Any] | None, headers: dict[str, str],
        json_body: Any, auth: httpx.Auth | None, follow_redirects: bool,
    ) -> tuple[httpx.Response, bytes | None]:
        """Send a request and read a 200 body in chunks, stopping at the size cap instead of
        buffering an unbounded (or decompressed) body first. Other statuses are not read."""
        request = self._client.build_request(method, path, params=params, headers=headers, json=json_body)
        resp = await self._client.send(request, auth=auth, follow_redirects=follow_redirects, stream=True)
        try:
            if resp.status_code != 200:
                return resp, None
            declared = resp.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > _MAX_RESPONSE_BYTES:
                raise _too_large(int(declared))
            body = bytearray()
            async for chunk in resp.aiter_bytes():
                body.extend(chunk)
                if len(body) > _MAX_RESPONSE_BYTES:
                    raise _too_large(f">{_MAX_RESPONSE_BYTES}")
            return resp, bytes(body)
        finally:
            await resp.aclose()

    def public_url(self, path: str, params: dict[str, Any] | None = None) -> str:
        """The citation URI for a request (never includes license headers)."""
        req = self._client.build_request("GET", path, params=_clean(params))
        return str(req.url)

    async def get_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        budget: Budget,
        correlation_id: str,
        license_key: str | None = None,
        not_found_ok: bool = False,
        auth: tuple[str, str] | None = None,
    ) -> HttpResult:
        return await self.request_json("GET", path, params=params, budget=budget, correlation_id=correlation_id,
                                       license_key=license_key, not_found_ok=not_found_ok, auth=auth)

    async def post_json(
        self,
        path: str,
        *,
        json_body: Any,
        budget: Budget,
        correlation_id: str,
        auth: tuple[str, str] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> HttpResult:
        return await self.request_json("POST", path, params=params, json_body=json_body, budget=budget,
                                       correlation_id=correlation_id, auth=auth, headers=headers)

    async def request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        budget: Budget,
        correlation_id: str,
        license_key: str | None = None,
        not_found_ok: bool = False,
        auth: tuple[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> HttpResult:
        _check_path(path)
        params = _clean(params)
        headers = {**(headers or {}), "X-Correlation-ID": correlation_id}
        if license_key:
            headers["X-EVSRESTAPI-License-Key"] = license_key
        httpx_auth = httpx.BasicAuth(*auth) if auth else None

        attempt = 0
        delay = 0.5
        last_exc: Exception | None = None
        while True:
            budget.take(retry=attempt > 0)
            attempt += 1
            try:
                async with self._sem:
                    # httpx strips Authorization on cross-origin redirects but not the license header, so
                    # requests carrying any secret never follow redirects.
                    resp, body = await self._send_capped(
                        method, path, params=params, headers=headers, json_body=json_body, auth=httpx_auth,
                        follow_redirects=not (license_key or auth),
                    )
            except httpx.TimeoutException as exc:
                last_exc = exc
                log.warning("upstream.timeout", path=path, attempt=attempt)
                if attempt > self._settings.http_max_retries:
                    raise EvsMcpError("timeout", "upstream request timed out", details={"path": path}) from exc
            except httpx.TransportError as exc:
                last_exc = exc
                log.warning("upstream.transport_error", path=path, attempt=attempt, error=type(exc).__name__)
                if attempt > self._settings.http_max_retries:
                    raise EvsMcpError("upstream_unavailable", "upstream connection failed", details={"path": path}) from exc
            else:
                status = resp.status_code
                if status == 200:
                    try:
                        data = json.loads(body or b"")
                    except ValueError as exc:
                        raise EvsMcpError("upstream_unavailable", "upstream returned a non-JSON body") from exc
                    return HttpResult(data=data, url=str(resp.url), status=status, retrieved_at=utcnow(), attempts=attempt)
                if status == 404:
                    if not_found_ok:
                        return HttpResult(data=None, url=str(resp.url), status=status, retrieved_at=utcnow(), attempts=attempt)
                    raise EvsMcpError("not_found", "upstream resource not found", details={"path": path})
                if status in (401, 403):
                    if auth is not None or license_key is not None:
                        raise EvsMcpError("permission_denied", "upstream rejected the configured credentials", details={"path": path, "status": status})
                    raise EvsMcpError(
                        "license_required",
                        "upstream refused the request; this content requires credentials or a license key",
                        details={"path": path, "status": status},
                    )
                if status == 400:
                    raise EvsMcpError("invalid_request", "upstream rejected the request parameters", details={"path": path})
                if status in self._retry_statuses:
                    log.warning("upstream.retryable_status", path=path, status=status, attempt=attempt)
                    if attempt > self._settings.http_max_retries:
                        code = "rate_limited" if status == 429 else "upstream_unavailable"
                        raise EvsMcpError(code, "upstream unavailable after retries", details={"path": path, "status": status})
                    retry_after = _retry_after_seconds(resp)
                    if retry_after is not None:
                        delay = min(retry_after, _MAX_RETRY_AFTER_S)
                else:
                    raise EvsMcpError("upstream_unavailable", "unexpected upstream status", details={"path": path, "status": status})

            # backoff before the next attempt
            jitter = random.uniform(0, delay / 2)
            await asyncio.sleep(min(delay + jitter, _MAX_RETRY_AFTER_S))
            delay = min(delay * 2, 8.0)
        raise EvsMcpError("internal_error", "unreachable") from last_exc  # pragma: no cover


def _too_large(size: int | str) -> EvsMcpError:
    return EvsMcpError(
        "bound_exceeded",
        "upstream response exceeded the size guard; narrow `include` or page size",
        details={"bytes": size, "cap": _MAX_RESPONSE_BYTES},
    )


def _clean(params: dict[str, Any] | None) -> dict[str, Any] | None:
    if not params:
        return None
    out: dict[str, Any] = {}
    for k, v in params.items():
        if v is None or v == "" or v == []:
            continue
        if isinstance(v, bool):
            out[k] = "true" if v else "false"
        elif isinstance(v, (list, tuple)):
            out[k] = ",".join(str(x) for x in v)
        else:
            out[k] = v
    return out or None


def _retry_after_seconds(resp: httpx.Response) -> float | None:
    raw = resp.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None
