"""Environment-driven configuration (proposal Section 10.5, prefix ``ECM_``)."""

from __future__ import annotations

import ipaddress
import os
from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Profile = Literal["evs-only", "cadsr-only", "unified"]


class Settings(BaseSettings):
    # validate_by_name lets tests pass the Databricks fields by name; the environment uses their aliases.
    model_config = SettingsConfigDict(env_prefix="ECM_", env_file=".env", extra="ignore",
                                      validate_by_name=True, validate_by_alias=True)

    # Deployment
    profile: Profile = "evs-only"
    public_host: str = "localhost"
    allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost", "http://127.0.0.1"])
    http_host: str = "127.0.0.1"
    # Without ECM_HTTP_PORT, a platform-injected DATABRICKS_APP_PORT or PORT (cloud.gov, Code Engine) is used.
    http_port: int = 8000
    mcp_path: str = "/mcp"
    # Stateless Streamable HTTP: no mcp-session-id, so any replica can serve any request. On by default
    # with ECM_AUTH_MODE=databricks, whose clients (e.g. the Databricks Assistant) don't send a session id.
    http_stateless: bool = False

    # Upstreams
    evs_base_url: str = "https://api-evsrest.nci.nih.gov/api/v1"
    evs_user_agent: str = "evs-cadsr-mcp/0.1 (+https://github.com/compbioutils)"

    # caDSR II (proposal Section 2.1 / 7.1). There is no single "caDSR API v2": the data-element
    # API is NCI API 1.0; Form API and CDE Match are 2.0. Paths are relative to cadsr_base_url.
    cadsr_base_url: str = "https://cadsrapi.cancer.gov"
    cadsr_nciapi_path: str = "/rad/NCIAPI/1.0/api"
    cadsr_formapi_path: str = "/rad/NCIFormAPI.v2_0:NciFormApiRad"
    cadsr_legacy_path: str = "/rad/caDSR.restapi:GetJSON_rad/GetJSON"
    cadsr_lov_path: str = "/rad/NCILovAPI/1.0/api"
    cadsr_cde_match_path: str = "/rad/NCIAPI.v2_0.cdeMatch.api:cdeMatch_rad/cdeMatch"
    cadsr_vm_match_path: str = "/rad/vmMatch/v1/vmMatch"
    cadsr_read_timeout_s: float = 45.0  # a fully expanded CDE takes 6-10 s and 100-400 KB
    # Basic auth for the LOV API and CDE Match 2.0; from the secrets manager in production. Give
    # cadsr_username + cadsr_password, or the combined cadsr_credential "user:password", not both.
    cadsr_username: str | None = None
    cadsr_password: SecretStr | None = None
    cadsr_credential: SecretStr | None = None
    cadsr_ai_match_url: str | None = None  # CDE AI Match API base (per environment, internal upstream only)
    cadsr_ai_match_variant: str | None = None  # allow-listed cde_model_variant
    cadsr_export_listing_url: str | None = None  # optional HTTP listing used by cadsr_get_registry_status
    cadsr_max_batch: int = 20
    cadsr_fanout_cap: int = 200  # max summaries per fan-out route

    # Release model (Section 6.1)
    default_terminology: str = "ncit"
    release_poll_seconds: int = 600
    release_pin: str | None = None  # force a release (e.g. "26.09d") instead of the latest monthly

    # Resilience and budgets (Sections 6.4, 10.3)
    http_connect_timeout_s: float = 5.0
    http_read_timeout_s: float = 30.0
    http_max_retries: int = 3
    http_max_concurrency: int = 8
    budget_max_requests: int = 50
    budget_max_requests_cap: int = 200
    batch_chunk_size: int = 500  # URL length caps the practical ?list= batch near 600

    # Cache (Section 10.2) - in-process tier only in this prototype
    cache_maxsize: int = 4096
    cache_ttl_metadata_s: int = 600
    cache_ttl_content_s: int = 24 * 3600
    cache_ttl_search_s: int = 3600
    cache_ttl_negative_s: int = 300
    cache_ttl_cadsr_s: int = 24 * 3600  # CDE by publicId+version; shared tier would use 30 d

    # Licensing (Sections 6.6, 10.4)
    license_key: str | None = None  # X-EVSRESTAPI-License-Key; never logged, never in provenance
    license_gated_terminologies: list[str] = Field(default_factory=lambda: ["meddra", "mdr"])

    # ICD-O-3.1 map (map_map_icdo_to_ncit): EVS's published mapping files, downloaded into a local
    # cache and re-checked every icdo_sync_interval_s (0 disables all automatic downloads; use
    # `evs-cadsr-mcp icdo sync`). Cache default: $XDG_CACHE_HOME or ~/.cache, /evs-cadsr-mcp/icdo.
    icdo_source_url: str = "https://evs.nci.nih.gov/ftp1/NCI_Thesaurus/Mappings/ICD-O-3_Mappings/"
    icdo_cache_dir: str | None = None
    icdo_sync_interval_s: int = Field(default=86400, ge=0)

    # Response shaping
    default_include: str = "summary"
    max_page_size: int = 1000
    search_max_limit: int = 100

    # Logging
    log_level: str = "INFO"
    log_json: bool = False

    # Security (Section 10.4). Remote deployments run as an OAuth 2.1 resource server ("jwt"), or as a
    # Databricks App ("databricks"), whose proxy authenticates every caller before the request arrives.
    auth_mode: Literal["none", "jwt", "databricks"] = "none"
    auth_jwks_uri: str | None = None  # identity provider JWKS endpoint
    auth_issuer: str | None = None
    auth_audience: str | None = None  # this server's resource identifier; tokens for other servers are rejected
    auth_public_key: str | None = None  # PEM, for deployments without JWKS (tests, static keys)
    auth_required_scopes: list[str] = Field(default_factory=list)  # scopes every caller must hold
    # Per-namespace scopes (evs:read, cadsr:read, cadsr:match, map:read). Defaults to on when auth_mode=jwt.
    scope_enforcement: bool = False
    trusted_hosts: list[str] = Field(default_factory=lambda: ["localhost", "127.0.0.1"])
    # Serving HTTP on a non-loopback address without auth is refused unless this is set explicitly.
    allow_unauthenticated: bool = False
    # Bearer token for /metrics and detailed /readyz. Without it they are served only on a loopback bind.
    admin_token: SecretStr | None = None

    # Databricks Apps (auth_mode=databricks). The platform injects these unprefixed variables; the
    # client id and secret are the OAuth M2M credentials of the app's own service principal.
    databricks_host: str | None = Field(default=None, validation_alias="DATABRICKS_HOST")
    databricks_client_id: str | None = Field(default=None, validation_alias="DATABRICKS_CLIENT_ID")
    databricks_client_secret: SecretStr | None = Field(default=None, validation_alias="DATABRICKS_CLIENT_SECRET")
    databricks_app_name: str | None = Field(default=None, validation_alias="DATABRICKS_APP_NAME")
    databricks_app_url: str | None = Field(default=None, validation_alias="DATABRICKS_APP_URL")

    # Rate limiting (per client id, token bucket)
    rate_limit_per_minute: int = 0  # 0 disables
    rate_limit_burst: int = 20

    # Audit (append-only sink; free-text parameters are hashed)
    audit_sink: str | None = None  # "stdout" | "stderr" | file path | None

    # Shared cache tier (Redis-compatible). None keeps the in-process tier only.
    cache_url: SecretStr | None = None  # may embed the Redis password; use rediss:// off-host
    cache_key_prefix: str = "ecm"

    # Observability
    metrics_enabled: bool = True
    otel_enabled: bool = False  # spans via opentelemetry-sdk when installed and enabled

    @model_validator(mode="after")
    def _check_icdo_source(self) -> Settings:
        if not self.icdo_source_url.startswith("https://"):
            raise ValueError("ECM_ICDO_SOURCE_URL must be an https:// URL")
        return self

    @model_validator(mode="after")
    def _platform_port(self) -> Settings:
        # A platform port sets only the port. The bind address stays ECM_HTTP_HOST (127.0.0.1 by default),
        # so a stray PORT never exposes the server; platforms set ECM_HTTP_HOST=0.0.0.0 plus auth explicitly.
        for name in ("DATABRICKS_APP_PORT", "PORT"):
            platform = os.environ.get(name, "").strip()
            if platform and "http_port" not in self.model_fields_set:
                if not platform.isdigit() or not 0 < int(platform) < 65536:
                    raise ValueError(f"{name} must be a TCP port number, got {platform!r}")
                self.http_port = int(platform)
                break
        return self

    @model_validator(mode="after")
    def _databricks_app(self) -> Settings:
        """Databricks Apps mode fails closed without the app's service principal, then applies the
        platform's requirements: listen on 0.0.0.0, stateless MCP, and the app URL as a trusted origin."""
        if self.auth_mode != "databricks":
            return self
        missing = [name for name, value in (("DATABRICKS_HOST", self.databricks_host),
                                            ("DATABRICKS_CLIENT_ID", self.databricks_client_id),
                                            ("DATABRICKS_CLIENT_SECRET", _secret(self.databricks_client_secret)))
                   if not (value or "").strip()]
        if missing:
            raise ValueError(f"ECM_AUTH_MODE=databricks runs only as a Databricks App, which injects {', '.join(missing)} "
                             "(the app's service principal); use ECM_AUTH_MODE=jwt elsewhere")
        self.databricks_host = _https_origin(self.databricks_host, "DATABRICKS_HOST", default_scheme=True)
        self.databricks_client_id = self.databricks_client_id.strip()
        app_origin = _https_origin(self.databricks_app_url, "DATABRICKS_APP_URL") if self.databricks_app_url else None
        if "http_host" not in self.model_fields_set:
            self.http_host = "0.0.0.0"  # the Databricks Apps proxy reaches the app on 0.0.0.0:DATABRICKS_APP_PORT
        if "http_stateless" not in self.model_fields_set:
            self.http_stateless = True
        if "trusted_hosts" not in self.model_fields_set:
            # The proxy is the only ingress and routes only this app's hostname, and the Host it forwards
            # is not documented; the Origin allow-list below still guards browser requests.
            self.trusted_hosts = ["*"]
        if app_origin and "allowed_origins" not in self.model_fields_set:
            self.allowed_origins = list(dict.fromkeys([*self.allowed_origins, app_origin, self.databricks_host]))
        return self

    @model_validator(mode="after")
    def _check_auth(self) -> Settings:
        if self.auth_mode == "jwt":
            if not (self.auth_issuer or "").strip():
                raise ValueError("ECM_AUTH_MODE=jwt needs ECM_AUTH_ISSUER, so tokens from other issuers are rejected")
            if "scope_enforcement" not in self.model_fields_set:
                self.scope_enforcement = True
        return self

    def binds_loopback(self) -> bool:
        """True when the HTTP listener is reachable only from this machine."""
        host = self.http_host.strip().strip("[]")
        if host == "localhost":
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    def check_http_exposure(self) -> None:
        """Fail closed: refuse an unauthenticated HTTP listener that other machines can reach."""
        if self.auth_mode == "none" and not self.binds_loopback() and not self.allow_unauthenticated:
            raise RuntimeError(
                f"refusing to serve {self.mcp_path} on {self.http_host} without authentication: set ECM_AUTH_MODE=jwt "
                "(with ECM_AUTH_JWKS_URI, ECM_AUTH_ISSUER and ECM_AUTH_AUDIENCE), ECM_AUTH_MODE=databricks inside a "
                "Databricks App, bind to 127.0.0.1, or set ECM_ALLOW_UNAUTHENTICATED=true behind a trusted gateway"
            )

    @model_validator(mode="after")
    def _check_cadsr_credentials(self) -> Settings:
        has_user = bool((self.cadsr_username or "").strip())
        has_password = bool(_secret(self.cadsr_password))
        if has_user != has_password:
            raise ValueError("set both ECM_CADSR_USERNAME and ECM_CADSR_PASSWORD, or neither")
        combined = _secret(self.cadsr_credential)
        if combined and has_user:
            raise ValueError("set either ECM_CADSR_USERNAME/ECM_CADSR_PASSWORD or ECM_CADSR_CREDENTIAL, not both")
        user, sep, _ = combined.partition(":")
        if combined and not (sep and user.strip()):
            raise ValueError("ECM_CADSR_CREDENTIAL must be 'user:password'")
        return self

    def cadsr_basic_auth(self) -> tuple[str, str] | None:
        """The caDSR Basic-auth (user, password) pair, or None when no credential is configured."""
        if (self.cadsr_username or "").strip() and _secret(self.cadsr_password):
            return self.cadsr_username.strip(), _secret(self.cadsr_password)
        user, sep, password = _secret(self.cadsr_credential).partition(":")
        return (user.strip(), password) if sep and user.strip() else None


def _secret(value: SecretStr | str | None) -> str:
    """Plain text of a secret setting (``model_copy`` in tests may hold a plain str)."""
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    return value or ""


def _https_origin(value: str, name: str, *, default_scheme: bool = False) -> str:
    """``https://host[:port]`` from a platform URL; anything with a path, query or credentials is refused,
    because the result is used to build upstream URLs and origin allow-list entries."""
    raw = value.strip().rstrip("/")
    if default_scheme and "://" not in raw:
        raw = f"https://{raw}"
    parts = urlsplit(raw)
    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError(f"{name} has an invalid port: {value!r}") from exc
    if parts.scheme != "https" or not parts.hostname or parts.path or parts.query or parts.fragment or "@" in parts.netloc:
        raise ValueError(f"{name} must be an https:// URL with no path, got {value!r}")
    return f"https://{parts.hostname}" + (f":{port}" if port else "")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
