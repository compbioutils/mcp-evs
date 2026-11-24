"""Authentication binding and scope policy (proposal 10.1, 10.4).

Remote deployments run as an OAuth 2.1 **resource server**: the identity provider issues
JWTs, this server verifies signature (JWKS or static key), issuer and **audience** (so a
token minted for another server is rejected), and the per-namespace scope policy below is
enforced by the middleware chain. Local stdio runs in trusted-local mode (``auth_mode=none``).

The verifier class moved between FastMCP 2.x minors (``BearerAuthProvider`` ->
``JWTVerifier``); :func:`build_auth_provider` tries both so the setting works across versions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

from .config import Settings

log = structlog.get_logger(__name__)

SCOPE_EVS = "evs:read"
SCOPE_CADSR = "cadsr:read"
SCOPE_CADSR_MATCH = "cadsr:match"
SCOPE_MAP = "map:read"
SCOPE_ADMIN = "admin"

MATCH_TOOLS = {"cadsr_match_data_elements", "cadsr_match_value_meanings", "cadsr_list_match_backends"}


def required_scopes(tool_name: str) -> set[str]:
    """Scopes a caller must hold for a tool. Suggestion tools that may call matchers need
    cadsr:read only; the matcher itself requires cadsr:match."""
    if tool_name in MATCH_TOOLS:
        return {SCOPE_CADSR, SCOPE_CADSR_MATCH}
    if tool_name.startswith("evs_"):
        return {SCOPE_EVS}
    if tool_name.startswith("cadsr_"):
        return {SCOPE_CADSR}
    if tool_name.startswith("map_"):
        return {SCOPE_MAP}
    return set()


def profile_scopes(profile: str) -> set[str]:
    """Scopes that make sense for a deployment profile (the policy intersects with these)."""
    if profile == "evs-only":
        return {SCOPE_EVS}
    if profile == "cadsr-only":
        return {SCOPE_CADSR, SCOPE_CADSR_MATCH, SCOPE_MAP}
    return {SCOPE_EVS, SCOPE_CADSR, SCOPE_CADSR_MATCH, SCOPE_MAP}


@dataclass(frozen=True)
class Principal:
    subject: str | None
    client_id: str | None
    scopes: frozenset[str]

    @classmethod
    def anonymous(cls) -> Principal:
        return cls(subject=None, client_id=None, scopes=frozenset())


def current_principal() -> Principal:
    """Read the verified access token bound to the current request, if any."""
    try:
        from fastmcp.server.dependencies import get_access_token  # type: ignore
    except ImportError:  # pragma: no cover - older FastMCP
        return Principal.anonymous()
    try:
        token: Any = get_access_token()
    except Exception:  # noqa: BLE001 - no request context (stdio / tests)
        return Principal.anonymous()
    if token is None:
        return Principal.anonymous()
    claims = getattr(token, "claims", None) or {}
    return Principal(
        subject=claims.get("sub") if isinstance(claims, dict) else None,
        client_id=getattr(token, "client_id", None),
        scopes=frozenset(getattr(token, "scopes", None) or []),
    )


def build_auth_provider(settings: Settings) -> Any | None:
    """Construct FastMCP's JWT verifier from settings, or None in trusted-local mode."""
    if settings.auth_mode == "none":
        return None
    if not (settings.auth_jwks_uri or settings.auth_public_key):
        raise RuntimeError("ECM_AUTH_MODE=jwt needs ECM_AUTH_JWKS_URI or ECM_AUTH_PUBLIC_KEY")
    if not settings.auth_audience:
        raise RuntimeError("ECM_AUTH_MODE=jwt needs ECM_AUTH_AUDIENCE (this server's resource identifier)")
    if not settings.auth_issuer:
        raise RuntimeError("ECM_AUTH_MODE=jwt needs ECM_AUTH_ISSUER (tokens from other issuers must be rejected)")
    kwargs: dict[str, Any] = {
        "issuer": settings.auth_issuer,
        "audience": settings.auth_audience,
        "required_scopes": list(settings.auth_required_scopes) or None,
    }
    if settings.auth_jwks_uri:
        kwargs["jwks_uri"] = settings.auth_jwks_uri
    else:
        kwargs["public_key"] = settings.auth_public_key
    errors: list[str] = []
    for path, name in (("fastmcp.server.auth.providers.jwt", "JWTVerifier"), ("fastmcp.server.auth", "JWTVerifier"), ("fastmcp.server.auth", "BearerAuthProvider")):
        try:
            module = __import__(path, fromlist=[name])
            cls = getattr(module, name)
        except (ImportError, AttributeError) as exc:
            errors.append(f"{path}.{name}: {type(exc).__name__}")
            continue
        provider = cls(**{k: v for k, v in kwargs.items() if v is not None})
        log.info("auth.provider", cls=f"{path}.{name}", audience=settings.auth_audience, issuer=settings.auth_issuer)
        return provider
    raise RuntimeError("no JWT verifier available in the installed FastMCP: " + "; ".join(errors))
