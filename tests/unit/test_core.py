"""Pure-core tests: cursor, budget, cache key, error envelope. No pydantic-free path here;
these need the project's dependencies installed (see README)."""

from __future__ import annotations

import json

import pytest

from evs_cadsr_mcp.core.budget import Budget
from evs_cadsr_mcp.core.cache import cache_key
from evs_cadsr_mcp.core.cursor import decode_cursor, encode_cursor
from evs_cadsr_mcp.core.errors import DEFAULT_HINTS, EvsMcpError


def test_cursor_roundtrip_and_release_binding():
    c = encode_cursor(release="26.10d", offset=40, extra={"k": 1})
    assert decode_cursor(c, release="26.10d") == (40, {"k": 1})
    with pytest.raises(EvsMcpError) as ei:
        decode_cursor(c, release="26.09d")
    assert ei.value.code == "cursor_expired"
    with pytest.raises(EvsMcpError) as ei:
        decode_cursor("not-a-cursor!!", release="26.10d")
    assert ei.value.code == "invalid_request"


def test_budget_counts_retries_and_fails_closed():
    b = Budget(max_requests=2)
    b.take()
    b.take(retry=True)
    assert b.used == 2 and b.retries == 1 and b.remaining == 0
    with pytest.raises(EvsMcpError) as ei:
        b.take()
    assert ei.value.code == "bound_exceeded"
    assert ei.value.details["bound"] == "maxRequests"


def test_cache_key_embeds_release_and_is_order_independent():
    a = cache_key("/concept", "26.10d", include="summary", code="C3224")
    b = cache_key("/concept", "26.10d", code="C3224", include="summary")
    c = cache_key("/concept", "26.09d", code="C3224", include="summary")
    assert a == b and a != c and "26.10d" in a


def test_error_envelope_is_json_with_closed_code():
    err = EvsMcpError("release_not_available", "nope", details={"live": ["26.10d"]})
    body = json.loads(err.to_json("cid-1"))
    assert body == {
        "error": {
            "code": "release_not_available",
            "message": "nope",
            "details": {"live": ["26.10d"]},
            "retryable": False,
            "hint": DEFAULT_HINTS["release_not_available"],
            "correlationId": "cid-1",
        }
    }
    assert EvsMcpError("timeout", "x").retryable is True
    assert EvsMcpError("timeout", "x", hint="narrow it").hint == "narrow it"


def test_every_error_code_has_a_default_hint():
    from typing import get_args

    from evs_cadsr_mcp.core.errors import ErrorCode

    assert set(get_args(ErrorCode)) == set(DEFAULT_HINTS)


def test_cadsr_credentials_from_separate_parts_or_combined(monkeypatch):
    from pydantic import ValidationError

    from evs_cadsr_mcp.core.config import Settings

    for var in ("ECM_CADSR_USERNAME", "ECM_CADSR_PASSWORD", "ECM_CADSR_CREDENTIAL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ECM_CADSR_USERNAME", "svc-user")
    monkeypatch.setenv("ECM_CADSR_PASSWORD", "pa:ss")
    s = Settings(_env_file=None)
    assert s.cadsr_basic_auth() == ("svc-user", "pa:ss")
    assert "pa:ss" not in repr(s) and "pa:ss" not in str(s.model_dump())

    monkeypatch.delenv("ECM_CADSR_PASSWORD")
    with pytest.raises(ValidationError, match="set both ECM_CADSR_USERNAME and ECM_CADSR_PASSWORD"):
        Settings(_env_file=None)
    monkeypatch.setenv("ECM_CADSR_PASSWORD", "pa:ss")
    monkeypatch.setenv("ECM_CADSR_CREDENTIAL", "other:pw")
    with pytest.raises(ValidationError, match="not both"):
        Settings(_env_file=None)

    monkeypatch.delenv("ECM_CADSR_USERNAME")
    monkeypatch.delenv("ECM_CADSR_PASSWORD")
    combined = Settings(_env_file=None)
    assert combined.cadsr_basic_auth() == ("other", "pw") and "other:pw" not in repr(combined)
    monkeypatch.setenv("ECM_CADSR_CREDENTIAL", "no-colon")
    with pytest.raises(ValidationError, match="user:password"):
        Settings(_env_file=None)
    monkeypatch.delenv("ECM_CADSR_CREDENTIAL")
    assert Settings(_env_file=None).cadsr_basic_auth() is None


# ------------------------------------------------------------------ outbound hardening
CID = "cid-12345678"

def _redirecting_client():
    import httpx

    from evs_cadsr_mcp.core.config import Settings
    from evs_cadsr_mcp.core.http_client import ResilientClient

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "evs.test":
            return httpx.Response(302, headers={"Location": "https://elsewhere.test/x"})
        return httpx.Response(200, json={"ok": True})

    settings = Settings(_env_file=None, http_max_retries=0)
    transport = httpx.MockTransport(handler)
    client = ResilientClient(settings, base_url="https://evs.test/api", transport=transport)
    return client, seen


BAD_PATHS = ["/mapset/../../x/maps", "/mapset/x?y=1#/maps", "/concept/a b", "/mapset/%2e%2e/maps"]


@pytest.mark.parametrize("path", BAD_PATHS)
async def test_outbound_path_rejects_traversal_and_query_injection(path):
    client, seen = _redirecting_client()
    try:
        with pytest.raises(EvsMcpError) as ei:
            await client.get_json(path, budget=Budget(max_requests=3), correlation_id=CID)
        assert ei.value.code == "invalid_request" and not seen
    finally:
        await client.aclose()


async def test_secret_bearing_requests_do_not_follow_redirects():
    client, seen = _redirecting_client()
    try:
        with pytest.raises(EvsMcpError):
            await client.get_json("/mapset/NCIt_Maps_To_MedDRA/maps", budget=Budget(max_requests=3),
                                  correlation_id=CID, license_key="secret")
        assert [r.url.host for r in seen] == ["evs.test"]
        ok = await client.get_json("/mapset/NCIt_Maps_To_GDC/maps", budget=Budget(max_requests=3),
                                   correlation_id=CID)
        assert ok.data == {"ok": True} and seen[-1].url.host == "elsewhere.test"
    finally:
        await client.aclose()


def test_logs_go_to_stderr_not_stdout(capsys):
    import structlog

    from evs_cadsr_mcp.core.config import Settings
    from evs_cadsr_mcp.server.mcp_app import configure_logging

    configure_logging(Settings(_env_file=None, log_level="INFO"))
    structlog.get_logger("t").info("probe.event")
    out = capsys.readouterr()
    assert "probe.event" not in out.out and "probe.event" in out.err


async def test_legacy_cadsr_query_accepts_only_numeric_ids_and_versions():
    from evs_cadsr_mcp.cadsr.client import CadsrClient

    class _Stub:
        def __init__(self):
            from evs_cadsr_mcp.core.config import Settings

            self.queries = []
            self.settings = Settings(_env_file=None)

        async def _get(self, inv, path, *, params, **kw):
            self.queries.append(params["query"])
            return {"Question": []}

    stub = _Stub()
    assert await CadsrClient.forms_for_data_element(stub, None, "2192199", "1") == []
    assert stub.queries == ["Question&DataElement[@publicId=2192199,@version=1.0]"]
    for bad in ("1.0],DataElement[@publicId=*", "x"):
        with pytest.raises(EvsMcpError):
            await CadsrClient.forms_for_data_element(stub, None, "2192199", bad)


async def test_oversized_upstream_body_is_cut_off_while_streaming(monkeypatch):
    import httpx

    from evs_cadsr_mcp.core import http_client
    from evs_cadsr_mcp.core.config import Settings
    from evs_cadsr_mcp.core.http_client import ResilientClient

    monkeypatch.setattr(http_client, "_MAX_RESPONSE_BYTES", 1000)
    pulled: list[int] = []

    async def endless():
        for _ in range(10_000):  # far more than the cap; must stop after the cap is passed
            pulled.append(1)
            yield b"x" * 100

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/declared"):
            return httpx.Response(200, headers={"Content-Length": "5000"}, content=b"{}" + b" " * 4998)
        return httpx.Response(200, content=endless())

    settings = Settings(_env_file=None, http_max_retries=0)
    client = ResilientClient(settings, base_url="https://evs.test/api", transport=httpx.MockTransport(handler))
    try:
        for path in ("/streamed", "/declared"):
            with pytest.raises(EvsMcpError) as ei:
                await client.get_json(path, budget=Budget(max_requests=3), correlation_id=CID)
            assert ei.value.code == "bound_exceeded"
        assert len(pulled) <= 12
    finally:
        await client.aclose()


def test_platform_port_applies_only_without_explicit_port(monkeypatch):
    from evs_cadsr_mcp.core.config import Settings

    monkeypatch.setenv("PORT", "8080")
    s = Settings(_env_file=None)
    assert s.http_port == 8080 and s.http_host == "127.0.0.1"  # PORT never changes the bind address
    monkeypatch.setenv("ECM_HTTP_PORT", "9000")
    assert Settings(_env_file=None).http_port == 9000
    monkeypatch.delenv("ECM_HTTP_PORT")
    monkeypatch.setenv("PORT", "http")
    with pytest.raises(ValueError, match="PORT"):
        Settings(_env_file=None)


def test_registry_metadata_matches_the_package():
    import tomllib
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    server = json.loads((root / "server.json").read_text())
    pkg = server["packages"][0]
    assert pkg["identifier"] == project["name"]
    assert server["version"] == pkg["version"] == project["version"]
    # The MCP Registry verifies PyPI ownership through this marker in the package README.
    assert f"mcp-name: {server['name']}" in (root / "README.md").read_text()
