"""Databricks Apps integration (``ECM_AUTH_MODE=databricks``).

Inbound: the Databricks Apps proxy authenticates every caller (a workspace user or service
principal with CAN USE on the app) before it forwards a request, and adds the caller's identity
as ``X-Forwarded-*`` headers. Those headers are trusted only in this mode, where the proxy is the
sole ingress, and they attribute audit records and rate limits.

Outbound: the app acts as its own service principal (``DATABRICKS_CLIENT_ID`` /
``DATABRICKS_CLIENT_SECRET``) with OAuth M2M tokens from the workspace's ``/oidc/v1/token``. The
user's downscoped ``x-forwarded-access-token`` is never read, logged or forwarded: no tool acts on
a user's behalf, so the default user-authorization scopes are enough.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterable, Mapping

import httpx
import structlog

from .auth import Principal
from .config import Settings, _secret

log = structlog.get_logger(__name__)

TOKEN_PATH = "/oidc/v1/token"
TOKEN_SCOPE = "all-apis"
REFRESH_MARGIN_S = 60.0
MAX_IDENTITY_LEN = 256


class ServicePrincipalError(RuntimeError):
    """The workspace did not issue a token. Carries the HTTP status or error type, never response text."""


class ServicePrincipal:
    """OAuth M2M (client credentials) tokens for the app's service principal, cached until shortly
    before they expire. The client secret and tokens are never logged."""

    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        if settings.auth_mode != "databricks":
            raise ValueError("ServicePrincipal needs ECM_AUTH_MODE=databricks")
        self.client_id = settings.databricks_client_id
        self._client_secret = _secret(settings.databricks_client_secret)
        self.token_url = f"{settings.databricks_host}{TOKEN_PATH}"
        self._http = httpx.AsyncClient(
            transport=transport,
            follow_redirects=False,  # the request carries the client secret
            timeout=httpx.Timeout(settings.http_read_timeout_s, connect=settings.http_connect_timeout_s),
        )
        self._token: str | None = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    def _fresh(self) -> str | None:
        return self._token if self._token and time.monotonic() < self._expires_at - REFRESH_MARGIN_S else None

    async def token(self) -> str:
        """A bearer token for Databricks REST calls made as the app itself."""
        if token := self._fresh():
            return token
        async with self._lock:
            if token := self._fresh():
                return token
            try:
                response = await self._http.post(
                    self.token_url,
                    auth=(self.client_id, self._client_secret),
                    data={"grant_type": "client_credentials", "scope": TOKEN_SCOPE},
                )
            except httpx.HTTPError as exc:
                raise ServicePrincipalError(f"token request failed: {type(exc).__name__}") from None
            if response.status_code != 200:
                raise ServicePrincipalError(f"token endpoint answered HTTP {response.status_code}")
            try:
                body = response.json()
                access = body["access_token"]
                ttl = float(body.get("expires_in", 3600))
            except (ValueError, KeyError, TypeError):
                raise ServicePrincipalError("token endpoint returned no access_token") from None
            if not isinstance(access, str) or not access:
                raise ServicePrincipalError("token endpoint returned no access_token")
            self._token, self._expires_at = access, time.monotonic() + ttl
            log.info("databricks.service_principal_token", client_id=self.client_id, expires_in_s=int(ttl))
            return access

    async def ready(self) -> bool:
        """True when the workspace issues the app a token (readiness)."""
        try:
            await self.token()
        except ServicePrincipalError as exc:
            log.warning("databricks.service_principal_unavailable", client_id=self.client_id, reason=str(exc))
            return False
        return True

    async def aclose(self) -> None:
        await self._http.aclose()


def _identity(headers: Mapping[str, str], name: str) -> str | None:
    value = (headers.get(name) or "").strip()
    if not value or len(value) > MAX_IDENTITY_LEN or not value.isprintable():
        return None
    return value


def forwarded_principal(headers: Mapping[str, str], scopes: Iterable[str]) -> Principal:
    """The caller the Databricks Apps proxy authenticated. CAN USE on the app grants every tool the
    deployment serves, so an identified caller holds the profile's scopes; no identity, no scopes."""
    user = _identity(headers, "x-forwarded-user")
    name = _identity(headers, "x-forwarded-preferred-username") or _identity(headers, "x-forwarded-email")
    if not (user or name):
        return Principal.anonymous()
    return Principal(subject=user or name, client_id=None, scopes=frozenset(scopes))


def request_principal(scopes: Iterable[str]) -> Principal:
    """:func:`forwarded_principal` for the HTTP request behind the current tool call."""
    try:
        from fastmcp.server.dependencies import get_http_request

        request = get_http_request()
    except Exception:  # noqa: BLE001 - no HTTP request in context (stdio, in-memory)
        return Principal.anonymous()
    return forwarded_principal(request.headers, scopes)
