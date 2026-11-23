"""ICD-O-3.1 mapping download, versioned cache and store (map/icdo_sync.py, map/icdo_map.py)."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import httpx
import pytest

from evs_cadsr_mcp.core.errors import EvsMcpError
from evs_cadsr_mcp.map.icdo_map import MORPHOLOGY_FILE, TOPOGRAPHY_FILE, IcdoMapStore
from evs_cadsr_mcp.map.icdo_sync import ALL_FILES, MAX_FILE_BYTES, IcdoSyncer
from tests.conftest import ICDO_CACHE_FIXTURE

BASE = "https://evs.test/ICD-O-3_Mappings/"
REAL = ICDO_CACHE_FIXTURE / "versions" / "fixture"


class FakeDownloads:
    """EVS download directory: ETag/Last-Modified, conditional GETs, and switchable faults."""

    def __init__(self) -> None:
        self.files = {
            "About.html": b"<html>ICD-O-3.1-NCIt Mapping Files</html>",
            "ICD-O-3.1-NCIt_Axis_Mappings.xls": b"\xd0\xcf\x11\xe0 workbook",
            MORPHOLOGY_FILE: (REAL / MORPHOLOGY_FILE).read_bytes(),
            TOPOGRAPHY_FILE: (REAL / TOPOGRAPHY_FILE).read_bytes(),
        }
        self.status: dict[str, int] = {}
        self.headers: dict[str, dict[str, str]] = {}
        self.requests: list[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        name = request.url.path.rsplit("/", 1)[-1]
        if request.url.host != "evs.test" or name not in self.files:
            return httpx.Response(404)
        if name in self.status:
            return httpx.Response(self.status[name], headers=self.headers.get(name, {}))
        body = self.files[name]
        etag = '"' + hashlib.md5(body).hexdigest() + '"'  # noqa: S324 - mimics the server's ETag
        if request.headers.get("if-none-match") == etag:
            return httpx.Response(304)
        return httpx.Response(200, content=body, headers={"ETag": etag, "Last-Modified": "Sat, 11 Jul 2026 23:29:37 GMT",
                                                          **self.headers.get(name, {})})


def syncer(tmp_path: Path, fake: FakeDownloads) -> IcdoSyncer:
    return IcdoSyncer(tmp_path / "cache", BASE, user_agent="test", transport=fake.transport())


async def test_first_sync_installs_then_unchanged_uses_conditional_requests(tmp_path):
    fake = FakeDownloads()
    s = syncer(tmp_path, fake)
    first = await s.sync()
    assert first.status == "updated" and sorted(first.changed) == sorted(ALL_FILES)
    current = s.current_version_dir()
    assert current is not None and {p.name for p in current.iterdir()} == {*ALL_FILES, "manifest.json"}
    assert s.manifest(current)["files"][MORPHOLOGY_FILE]["lastModified"] == "Sat, 11 Jul 2026 23:29:37 GMT"

    fake.requests.clear()
    again = await s.sync()
    assert again.status == "unchanged" and again.version == current.name
    assert len(fake.requests) == len(ALL_FILES) and all(r.headers.get("if-none-match") for r in fake.requests)
    assert s.state()["lastResult"] == "unchanged"


async def test_changed_file_installs_new_version_and_store_reloads(tmp_path):
    fake = FakeDownloads()
    s = syncer(tmp_path, fake)
    store = IcdoMapStore(s, interval_s=0)
    await s.sync()
    old = await store.get()
    assert not old.lookup("C50.0")
    fake.files[TOPOGRAPHY_FILE] += b"C50.0\t4\tPT\tPreferred term\tNipple\tC0028109\tC12301\tNipple\r\n"
    result = await s.sync()  # e.g. a CLI sync in another process
    assert result.status == "updated" and result.changed == [TOPOGRAPHY_FILE]
    new = await store.get()
    assert new.version != old.version and [e.ncit_code for e in new.lookup("C50.0")] == ["C12301"]


@pytest.mark.parametrize("fault", ["bad_header", "truncated", "redirect", "oversized", "server_error"])
async def test_bad_downloads_keep_the_current_version(tmp_path, fault):
    fake = FakeDownloads()
    s = syncer(tmp_path, fake)
    await s.sync()
    before = s.current_version_dir()
    good = fake.files[MORPHOLOGY_FILE]
    if fault == "bad_header":
        fake.files[MORPHOLOGY_FILE] = b"code,name\r\n8140/3,Adenocarcinoma\r\n"
    elif fault == "truncated":  # parses, but far fewer mappings than before
        fake.files[MORPHOLOGY_FILE] = good.split(b"\r\n")[0] + b"\r\n" + good.split(b"\r\n")[4] + b"\r\n"
        fake.files[TOPOGRAPHY_FILE] = fake.files[TOPOGRAPHY_FILE].split(b"\r\n")[0] + b"\r\n" + fake.files[TOPOGRAPHY_FILE].split(b"\r\n")[3] + b"\r\n"
    elif fault == "redirect":
        fake.status[MORPHOLOGY_FILE] = 302
        fake.headers[MORPHOLOGY_FILE] = {"Location": "https://elsewhere.test/x.txt"}
    elif fault == "oversized":
        fake.headers[MORPHOLOGY_FILE] = {"Content-Length": str(MAX_FILE_BYTES + 1)}
        fake.files[MORPHOLOGY_FILE] = good + b" "
    else:
        fake.status[MORPHOLOGY_FILE] = 503
    result = await s.sync()
    assert result.status == "failed" and result.error and result.version == before.name
    assert s.current_version_dir() == before and s.state()["lastResult"] == "failed"
    assert not [r for r in fake.requests if r.url.host != "evs.test"]  # redirects are never followed
    assert not [p for p in s.versions_dir.iterdir() if p.name.startswith(".staging")]


async def test_reference_file_failure_is_not_fatal(tmp_path):
    fake = FakeDownloads()
    fake.status["About.html"] = 500
    s = syncer(tmp_path, fake)
    result = await s.sync()
    assert result.status == "updated" and "About.html" not in result.changed
    assert not (s.current_version_dir() / "About.html").exists()


async def test_install_from_dir_for_offline_hosts(tmp_path):
    s = IcdoSyncer(tmp_path / "cache", BASE, user_agent="test")
    result = s.install_from_dir(REAL)
    assert result.status == "updated" and s.current_version_dir() is not None
    missing = s.install_from_dir(tmp_path)
    assert missing.status == "failed" and "missing required files" in missing.error


async def test_empty_cache_with_auto_sync_downloads_on_first_use(tmp_path):
    fake = FakeDownloads()
    store = IcdoMapStore(syncer(tmp_path, fake), interval_s=86400)
    icdo = await store.get()
    assert [e.ncit_code for e in icdo.lookup("8140/3")] == ["C2852"] and icdo.published_date == "2026-07-11"


async def test_empty_cache_without_auto_sync_is_unavailable(tmp_path):
    fake = FakeDownloads()
    store = IcdoMapStore(syncer(tmp_path, fake), interval_s=0)
    with pytest.raises(EvsMcpError) as ei:
        await store.get()
    assert ei.value.code == "capability_unavailable" and not fake.requests


async def test_background_task_syncs_then_stops(tmp_path):
    fake = FakeDownloads()
    store = IcdoMapStore(syncer(tmp_path, fake), interval_s=86400)
    store.start()
    for _ in range(100):
        if store.syncer.current_version_dir() is not None:
            break
        await asyncio.sleep(0.01)
    assert store.syncer.current_version_dir() is not None
    await store.stop()
    assert store._task is None


async def test_background_check_waits_until_due(tmp_path):
    fake = FakeDownloads()
    s = syncer(tmp_path, fake)
    await s.sync()
    assert 86000 < s.seconds_until_due(86400) <= 86400  # a fresh check defers the next one by a day


def test_source_url_must_be_https():
    from evs_cadsr_mcp.core.config import Settings

    with pytest.raises(ValueError, match="https"):
        Settings(_env_file=None, icdo_source_url="http://evs.nci.nih.gov/ftp1/")


async def test_server_lifespan_starts_and_stops_the_daily_sync(unified_settings, fake_evs, fake_cadsr, tmp_path):
    from fastmcp import Client

    from evs_cadsr_mcp.server.mcp_app import build_mcp_server, build_services

    s = unified_settings.model_copy(update={"icdo_cache_dir": str(tmp_path), "icdo_sync_interval_s": 86400})
    svc = build_services(s, transport=fake_evs.transport(), cadsr_transport=fake_cadsr.transport())
    calls: list[str] = []
    svc.map.icdo_map.start = lambda: calls.append("start")

    async def stop() -> None:
        calls.append("stop")

    svc.map.icdo_map.stop = stop
    mcp, _ = build_mcp_server(s, services=svc)
    try:
        async with Client(mcp) as client:
            await client.list_tools()
            assert calls == ["start"]
        assert calls == ["start", "stop"]
    finally:
        await svc.aclose()
