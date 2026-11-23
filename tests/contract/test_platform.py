"""Platform-layer tests (proposal Sections 10.1-10.6): middleware chain over the MCP client
(scope denial, rate limiting, audit redaction, correlation id), two-tier cache, metrics,
and the FastAPI host's transport security and admin endpoints."""

from __future__ import annotations

import json

import httpx
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from evs_cadsr_mcp.core.audit import MemorySink, redact
from evs_cadsr_mcp.core.auth import Principal, profile_scopes, required_scopes
from evs_cadsr_mcp.core.budget import Budget
from evs_cadsr_mcp.core.config import Settings
from evs_cadsr_mcp.core.context import Invocation
from evs_cadsr_mcp.core.errors import EvsMcpError
from evs_cadsr_mcp.core.metrics import METRICS, Metrics
from evs_cadsr_mcp.core.ratelimit import RateLimiter
from evs_cadsr_mcp.server.app import create_app
from evs_cadsr_mcp.server.mcp_app import build_mcp_server, build_services
from tests.conftest import FakeEvs


# ------------------------------------------------------------------ unit bits
def test_rate_limiter_token_bucket():
    rl = RateLimiter(per_minute=60, burst=2)
    assert rl.allow("a", now=0.0) == (True, 0.0) and rl.allow("a", now=0.0) == (True, 0.0)
    ok, retry = rl.allow("a", now=0.0)
    assert not ok and 0 < retry <= 1.0 and rl.rejected == 1
    assert rl.allow("b", now=0.0)[0]  # independent bucket
    assert rl.allow("a", now=1.0)[0]  # one token refilled after a second at 1/s
    assert RateLimiter(per_minute=0, burst=1).allow("x") == (True, 0.0)  # disabled


def test_audit_redaction_keeps_identifiers_hashes_free_text():
    out = redact({"code": "C3224", "release": "26.10d", "term": "melanoma of the skin", "limit": 5, "exact": True, "fragment": {"content": "x" * 100}})
    assert out["code"] == "C3224" and out["release"] == "26.10d" and out["limit"] == 5 and out["exact"] is True
    assert set(out["term"]) == {"sha256", "len"} and out["term"]["len"] == 20 and "melanoma" not in json.dumps(out)
    assert "sha256" in out["fragment"]


def test_scope_policy():
    assert required_scopes("evs_get_concept") == {"evs:read"}
    assert required_scopes("cadsr_get_data_element") == {"cadsr:read"}
    assert required_scopes("cadsr_match_data_elements") == {"cadsr:read", "cadsr:match"}
    assert required_scopes("map_resolve_cde_concepts") == {"map:read"}
    assert profile_scopes("evs-only") == {"evs:read"} and "map:read" in profile_scopes("unified")


def test_metrics_render_prometheus_text():
    m = Metrics()
    m.describe("x_total", "help")
    m.inc("x_total", {"tool": "t"})
    m.inc("x_total", {"tool": "t"})
    m.observe_ms("lat_ms", 120, {"tool": "t"})
    m.gauge("g", 3)
    text = m.render()
    assert "# HELP x_total help" in text and '# TYPE x_total counter' in text and 'x_total{tool="t"} 2' in text
    assert 'lat_ms_bucket{tool="t",le="250"} 1' in text and 'lat_ms_bucket{tool="t",le="100"} 0' in text and 'lat_ms_count{tool="t"} 1' in text
    assert "g 3" in text


# ------------------------------------------------------------- middleware chain
@pytest.fixture
def limited_settings() -> Settings:
    return Settings(_env_file=None, profile="evs-only", http_max_retries=1, rate_limit_per_minute=60, rate_limit_burst=2, log_level="WARNING")


async def test_rate_limit_and_audit_over_mcp(limited_settings, fake_evs: FakeEvs):
    sink = MemorySink()
    services = build_services(limited_settings, transport=fake_evs.transport())
    mcp, _ = build_mcp_server(limited_settings, services=services, audit_sink=sink)
    try:
        async with Client(mcp) as client:
            await client.call_tool("evs_get_concept", {"code": "C3224"})
            await client.call_tool("evs_search_concepts", {"term": "melanoma", "limit": 3})
            with pytest.raises(ToolError) as ei:
                await client.call_tool("evs_get_concept", {"code": "C3224"})
        body = json.loads(str(ei.value))
        assert body["error"]["code"] == "rate_limited" and body["error"]["retryable"] is True
        assert [r.status for r in sink.records] == ["ok", "ok", "error"] and sink.records[2].errorCode == "rate_limited"
        first, second = sink.records[0], sink.records[1]
        assert first.tool == "evs_get_concept" and first.arguments["code"] == "C3224" and first.outboundRequests == 1
        assert first.release == fake_evs.active and first.servedBy == "live" and first.resultBytes > 100 and first.correlationId
        assert "sha256" in second.arguments["term"] and "melanoma" not in json.dumps(second.arguments)
        assert second.servedBy in ("live", "cache") and second.truncated is False
        snap = METRICS.snapshot()
        assert any(k.startswith("ecm_tool_calls_total") and 'tool="evs_get_concept"' in k for k in snap)
        assert any(k.startswith("ecm_rate_limit_rejections_total") for k in snap)
    finally:
        await services.aclose()


async def test_scope_enforcement_denies_anonymous_and_allows_scoped(fake_evs: FakeEvs, monkeypatch):
    settings = Settings(_env_file=None, profile="evs-only", scope_enforcement=True, log_level="WARNING")
    services = build_services(settings, transport=fake_evs.transport())
    sink = MemorySink()
    mcp, _ = build_mcp_server(settings, services=services, audit_sink=sink)
    try:
        async with Client(mcp) as client:
            with pytest.raises(ToolError) as ei:
                await client.call_tool("evs_get_concept", {"code": "C3224"})
            body = json.loads(str(ei.value))
            assert body["error"]["code"] == "permission_denied" and body["error"]["details"]["missing"] == ["evs:read"]
            assert sink.records[-1].status == "error" and sink.records[-1].errorCode == "permission_denied" and sink.records[-1].outboundRequests is None

            import evs_cadsr_mcp.server.middleware as mw

            monkeypatch.setattr(mw, "current_principal", lambda: Principal(subject="user-1", client_id="agent-7", scopes=frozenset({"evs:read"})))
            res = await client.call_tool("evs_get_concept", {"code": "C3224"})
            assert res.structured_content is not None or res.content
            rec = sink.records[-1]
            assert rec.status == "ok" and rec.subject == "user-1" and rec.clientId == "agent-7" and rec.scopes == ["evs:read"]
            # every invocation gets its own correlation id
            await client.call_tool("evs_get_concept", {"code": "C3224"})
            assert sink.records[-1].correlationId and sink.records[-1].correlationId != rec.correlationId
    finally:
        await services.aclose()


def test_jwt_mode_requires_issuer_and_enforces_scopes_by_default():
    with pytest.raises(ValueError, match="ISSUER"):
        Settings(_env_file=None, auth_mode="jwt", auth_jwks_uri="https://idp.example/jwks", auth_audience="https://mcp.example")
    s = Settings(_env_file=None, auth_mode="jwt", auth_jwks_uri="https://idp.example/jwks", auth_issuer="https://idp.example/")
    assert s.scope_enforcement is True
    assert Settings(_env_file=None, auth_mode="jwt", auth_jwks_uri="https://idp.example/jwks", auth_issuer="https://idp.example/",
                    scope_enforcement=False).scope_enforcement is False


def test_unauthenticated_http_is_refused_off_loopback():
    Settings(_env_file=None, http_host="127.0.0.1").check_http_exposure()
    Settings(_env_file=None, http_host="::1").check_http_exposure()
    with pytest.raises(RuntimeError, match="without authentication"):
        Settings(_env_file=None, http_host="0.0.0.0").check_http_exposure()
    Settings(_env_file=None, http_host="0.0.0.0", allow_unauthenticated=True).check_http_exposure()


async def test_jwt_mode_requires_audience(fake_evs: FakeEvs):
    settings = Settings(_env_file=None, profile="evs-only", auth_mode="jwt", auth_jwks_uri="https://idp.example/jwks",
                        auth_issuer="https://idp.example/", log_level="WARNING")
    services = build_services(settings, transport=fake_evs.transport())
    try:
        with pytest.raises(RuntimeError, match="AUDIENCE"):
            build_mcp_server(settings, services=services)
    finally:
        await services.aclose()


# ------------------------------------------------------------- two-tier cache
async def test_shared_cache_tier_serves_second_instance(fake_evs: FakeEvs):
    settings = Settings(_env_file=None, profile="evs-only", cache_url="memory://", log_level="WARNING")
    a = build_services(settings, transport=fake_evs.transport())
    b = build_services(settings, transport=fake_evs.transport())
    b.cache.shared = a.cache.shared  # same shared tier, separate in-process tiers (two replicas)
    try:
        ctx = await a.evs.release_context("ncit", None)
        first = await a.evs.get_concept(Invocation(tool="t", budget=Budget(max_requests=5)), ctx, "C3224", ["summary"])
        assert first.provenance[0].servedBy == "live"
        ctx_b = await b.evs.release_context("ncit", None)
        second = await b.evs.get_concept(Invocation(tool="t", budget=Budget(max_requests=5)), ctx_b, "C3224", ["summary"])
        assert second.provenance[0].servedBy == "cache" and second.meta.outboundRequests == 0
        assert second.provenance[0].retrievedAt.replace(microsecond=0) == first.provenance[0].retrievedAt.replace(microsecond=0)
        assert fake_evs.path_counts[f"/concept/ncit_{fake_evs.active}/C3224"] == 1
        assert b.cache.stats()["shared"]["hits"] == 1 and await b.cache.ready()
        # negative results stay in the local tier only
        shared_keys_before = len(a.cache.shared._d)
        with pytest.raises(EvsMcpError):
            await a.evs.get_concept(Invocation(tool="t", budget=Budget(max_requests=5)), ctx, "C12345", None)
        assert len(a.cache.shared._d) == shared_keys_before
    finally:
        await a.aclose()
        await b.aclose()


# -------------------------------------------------------------- FastAPI host
async def test_host_admin_endpoints_and_transport_security(fake_evs: FakeEvs):
    settings = Settings(_env_file=None, profile="evs-only", public_host="mcp.example.test", allowed_origins=["https://app.example.test"], log_level="WARNING")
    services = build_services(settings, transport=fake_evs.transport())
    app = create_app(settings, services=services)
    try:
        # Run the app's lifespan as a server would: FastMCP's session manager starts there.
        async with app.router.lifespan_context(app), \
                httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as c:
            r = await c.get("/healthz")
            assert r.status_code == 200 and r.json()["profile"] == "evs-only"
            r = await c.get("/healthz", headers={"Host": "mcp.example.test:8443"})
            assert r.status_code == 200
            r = await c.get("/readyz")
            assert r.status_code == 200 and r.json()["activeRelease"] == fake_evs.active and r.json()["sharedCache"] == "ok"
            r = await c.get("/metrics")
            assert r.status_code == 200 and "ecm_active_release_info" in r.text
            r = await c.get("/healthz", headers={"Host": "evil.example"})
            assert r.status_code == 400  # TrustedHostMiddleware
            r = await c.get("/healthz", headers={"Origin": "https://evil.example"})
            assert r.status_code == 421
            r = await c.get("/healthz", headers={"Origin": "https://app.example.test"})
            assert r.status_code == 200
            r = await c.post("/mcp", content=b"x" * (5 * 1024 * 1024), headers={"Content-Type": "application/json"})
            assert r.status_code == 413

            async def chunks():  # no Content-Length: the limit must hold while streaming
                for _ in range(5):
                    yield b"x" * (1024 * 1024)

            r = await c.post("/mcp", content=chunks(), headers={"Content-Type": "application/json"})
            assert r.status_code == 413
            r = await c.post("/mcp", content=b"{}", headers={"Content-Type": "application/json", "Content-Length": "abc"})
            assert r.status_code == 400
    finally:
        await services.aclose()


async def test_admin_detail_needs_token_off_loopback(fake_evs: FakeEvs):
    settings = Settings(_env_file=None, profile="evs-only", http_host="0.0.0.0", allow_unauthenticated=True,
                        admin_token="ops-secret", log_level="WARNING")
    services = build_services(settings, transport=fake_evs.transport())
    app = create_app(settings, services=services)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as c:
            r = await c.get("/readyz")
            assert r.status_code == 200 and set(r.json()) == {"status", "sharedCache", "activeRelease"}
            assert (await c.get("/metrics")).status_code == 404
            ops = {"Authorization": "Bearer ops-secret"}
            assert "cadsr" in (await c.get("/readyz", headers=ops)).json()
            assert (await c.get("/metrics", headers=ops)).status_code == 200
            assert (await c.get("/metrics", headers={"Authorization": "Bearer wrong"})).status_code == 404
    finally:
        await services.aclose()


async def test_tool_arguments_cannot_steer_upstream_paths(fake_evs: FakeEvs):
    settings = Settings(_env_file=None, profile="evs-only", log_level="WARNING")
    services = build_services(settings, transport=fake_evs.transport())
    mcp, _ = build_mcp_server(settings, services=services)
    try:
        async with Client(mcp) as client:
            before = len(fake_evs.requests)
            for args in ({"mapset": "../../x"}, {"mapset": "x?y=1#"}):
                with pytest.raises(ToolError):
                    await client.call_tool("evs_get_mapset_entries", args)
            with pytest.raises(ToolError):
                await client.call_tool("evs_get_paths", {"code": "C3224", "kind": "toAncestor", "ancestorCode": "../C1"})
            assert len(fake_evs.requests) == before
    finally:
        await services.aclose()


async def test_jwt_verifier_accepts_only_tokens_for_this_server():
    import time

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from joserfc import jwt
    from joserfc.jwk import RSAKey

    from evs_cadsr_mcp.core.auth import build_auth_provider

    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = private.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    signing_key = RSAKey.import_key(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    verifier = build_auth_provider(Settings(_env_file=None, auth_mode="jwt", auth_public_key=public_pem,
                                            auth_issuer="https://idp.test/", auth_audience="https://mcp.test"))

    def token(**claims):
        base = {"iss": "https://idp.test/", "aud": "https://mcp.test", "sub": "u1", "exp": int(time.time()) + 300, "scope": "evs:read"}
        return jwt.encode({"alg": "RS256"}, {**base, **claims}, signing_key)

    ok = await verifier.load_access_token(token())
    assert ok is not None and ok.scopes == ["evs:read"]
    for bad in (token(aud="https://other.test"), token(iss="https://evil.test/"), token(exp=int(time.time()) - 60)):
        assert await verifier.load_access_token(bad) is None
