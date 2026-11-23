"""Test harness: a fake EVS transport backed by JSON fixtures, and an in-process MCP client.

No network. Fixtures under ``tests/fixtures/evs`` are hand-authored from the documented EVS
shapes until ``scripts/record_fixtures.py`` is run against the live API.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import httpx
import pytest

from evs_cadsr_mcp.core.config import Settings
from evs_cadsr_mcp.server.mcp_app import Services, build_mcp_server, build_services

FIXTURES = Path(__file__).parent / "fixtures" / "evs"


def load(name: str) -> Any:
    doc = json.loads((FIXTURES / name).read_text())
    return doc["data"] if isinstance(doc, dict) and "data" in doc else doc


class FakeEvs:
    """Routes EVS REST paths to fixtures. Records every request for assertions."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.path_counts: Counter[str] = Counter()
        self.fail_next: list[int] = []  # status codes to return before succeeding
        self.misc = load("misc_endpoints.json")
        self.terms_ncit = load("metadata_terminologies_ncit.json")
        self.terms_latest = load("metadata_terminologies_latest.json")
        self.c3224_summary = load("concept_C3224_summary.json")
        self.c3224_rel = load("concept_C3224_relations.json")
        self.search_contains = load("search_melanoma_contains.json")
        self.search_nsclc = load("search_nsclc_match.json")
        self.graph = load("graph_small.json")
        self.catalog = load("ncit_catalog.json")
        # Releases come from the terminologies fixture so recorded fixtures keep working.
        monthly = [t for t in self.terms_ncit if str((t.get("tags") or {}).get("monthly", "")).lower() == "true"] or self.terms_ncit
        self.active = next(t["version"] for t in monthly if t.get("latest"))
        others = [t["version"] for t in monthly if t["version"] != self.active]
        self.previous = others[0] if others else None  # a live, non-active release
        self.drifting = others[1] if len(others) > 1 else None  # upstream answers with the wrong version

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path.removeprefix("/api/v1")
        self.path_counts[path] += 1
        if self.fail_next:
            status = self.fail_next.pop(0)
            headers = {"Retry-After": "0"} if status == 429 else {}
            return httpx.Response(status, json={"error": "injected"}, headers=headers)
        q = dict(request.url.params)
        data = self.route(path, q)
        if data is None:
            return httpx.Response(404, json={"message": "not found"})
        return httpx.Response(200, json=data)

    def route(self, path: str, q: dict[str, str]) -> Any:  # noqa: C901 - a router
        if path == "/metadata/terminologies":
            if q.get("terminology") == "ncit":
                return self.terms_ncit
            if q.get("terminology"):
                return []
            return self.terms_latest
        tv = f"ncit_{self.active}"
        if path.startswith(f"/metadata/{tv}/"):
            kind = path.rsplit("/", 1)[1]
            return [{"code": f"{kind}-1", "name": f"Example {kind}", "terminology": "ncit", "version": self.active}]
        list_release = None
        if path.startswith("/concept/ncit_") and path.count("/") == 2 and "list" in q:
            list_release = path.split("ncit_", 1)[1]
        if list_release and list_release != self.active and list_release == self.previous:
            # batch retrieval at the previous live release: catalog with per-release overrides
            out = []
            for c in q["list"].split(","):
                node = self.catalog["concepts"].get(c)
                if node is None:
                    continue
                d = dict(node)
                d.update(self.catalog["previousReleaseOverrides"].get(c, {}))
                d.update({"terminology": "ncit", "version": list_release})
                out.append(d)
            return out
        if path == f"/concept/{tv}" and "list" in q:
            codes = q["list"].split(",")
            inc = q.get("include", "summary")
            itemised = any(f in inc for f in ("parents", "children", "roles", "inverseRoles", "associations", "inverseAssociations", "properties"))
            out = []
            for c in codes:
                node = self.graph["concepts"].get(c)
                if itemised and node is not None:
                    d = {k: v for k, v in node.items() if k in ("code", "name", "leaf", "active", "conceptStatus")}
                    d.update({"terminology": "ncit", "version": self.active})
                    for flag in ("parents", "children", "roles", "inverseRoles", "associations", "inverseAssociations", "properties"):
                        if flag in inc:
                            d[flag] = node.get(flag, [])
                    out.append(d)
                elif c in self.catalog["concepts"]:
                    d = dict(self.catalog["concepts"][c])
                    d.update({"terminology": "ncit", "version": self.active})
                    if "history" not in inc:
                        d.pop("history", None)
                    out.append(d)
                elif c == "C3224":
                    out.append(self.c3224_summary)
                elif c == "C2926":
                    out.append(self.search_nsclc["concepts"][0])
            return out
        if path == f"/concept/{tv}/search":
            if q.get("property") and q.get("value"):
                hit = self.graph["searchByProperty"].get(f"{q['property']}={q['value']}", {"total": 0, "concepts": []})
                hit = {"total": hit["total"], "concepts": [dict(self.catalog["concepts"].get(c["code"], c), version=self.active) for c in hit["concepts"]]}
                if q.get("subset") == "C177537":  # intersect with the subset fixture
                    members = {m["code"] for m in self.misc_lookup(f"/subset/{tv}/C177537/members")}
                    hit = {"total": None, "concepts": [c for c in hit["concepts"] if c["code"] in members]}
                    hit["total"] = len(hit["concepts"])
                start, size = int(q.get("fromRecord", 0)), int(q.get("pageSize", 10))
                return {"total": hit["total"], "concepts": hit["concepts"][start : start + size]}
            if q.get("type") == "match" and q.get("term", "").lower() == "nsclc":
                return self.search_nsclc
            if q.get("type") == "match":
                term = q.get("term", "").casefold()
                pool = [*self.catalog["concepts"].values(), self.c3224_summary, self.search_nsclc["concepts"][0]]
                hits = [dict(c, version=self.active) for c in pool
                        if term in {c["name"].casefold(), *(s["name"].casefold() for s in c.get("synonyms", []))}]
                return {"total": len(hits), "concepts": hits}
            if q.get("term", "").lower().startswith("melan"):
                return self.search_contains
            return {"total": 0, "concepts": []}
        for part in ("inverseRoles", "inverseAssociations"):
            prefix, suffix = f"/concept/{tv}/", f"/{part}"
            if path.startswith(prefix) and path.endswith(suffix):
                code = path[len(prefix) : -len(suffix)]
                return self.graph[part].get(code)
        if path.startswith(f"/concept/{tv}/associations/"):
            label = path.rsplit("/", 1)[1]
            data = self.graph["associationsByType"].get(label)
            if data is None:
                return None
            start, size = int(q.get("fromRecord", 0)), int(q.get("pageSize", 1000))
            return {"total": data["total"], "associations": data["associations"][start : start + size]}
        if path == f"/concept/{tv}/C3224":
            inc = q.get("include", "summary")
            if any(f in inc for f in ("roles", "associations", "maps", "history", "parents", "children", "disjointWith")):
                merged = dict(self.c3224_summary)
                merged.update(self.c3224_rel)
                return merged
            return self.c3224_summary
        if path == f"/concept/{tv}/C12345":
            return None
        if path.startswith(f"/concept/{tv}/") and path.count("/") == 3 and path.rsplit("/", 1)[1] in self.catalog["concepts"]:
            d = dict(self.catalog["concepts"][path.rsplit("/", 1)[1]])
            d.update({"terminology": "ncit", "version": self.active})
            return d
        if path == f"/history/{tv}/C17649/replacements":
            return [{"code": "C17649", "name": "Other", "action": "retire", "date": "2026-09-29", "replacementCode": "C17998", "replacementName": "Unknown"}]
        if self.previous and path == f"/concept/ncit_{self.previous}/C3224":
            d = dict(self.c3224_summary)
            d["version"] = self.previous
            return d
        if self.drifting and path == f"/concept/ncit_{self.drifting}/C3224":
            # Simulate a rollover bug: upstream reports a different version than the path pins.
            d = dict(self.c3224_summary)
            d["version"] = self.active
            return d
        if path in self.misc:
            return self.misc[path]
        # Hand-authored misc fixture keys are pinned to ncit_26.10d; recorded ones use the live release.
        alt = path.replace(tv, "ncit_26.10d")
        if alt in self.misc:
            return self.misc[alt]
        return None

    def misc_lookup(self, path: str) -> Any:
        return self.misc.get(path) or self.misc.get(path.replace(f"ncit_{self.active}", "ncit_26.10d")) or []


@pytest.fixture
def fake_evs() -> FakeEvs:
    return FakeEvs()


CADSR_FIXTURES = Path(__file__).parent / "fixtures" / "cadsr"
ICDO_CACHE_FIXTURE = Path(__file__).parent / "fixtures" / "map" / "icdo-cache"


class FakeCadsr:
    """Routes caDSR paths to fixtures. Emulates HTTP 200 + apiResponse.type=E errors, Basic auth
    on the LOV/CDE Match services, and records requests (headers included) for assertions."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.path_counts: Counter[str] = Counter()
        self.fail_next: list[int] = []
        self.delay_calls = 0
        self.de_2192199 = json.loads((CADSR_FIXTURES / "data_element_2192199_v1.json").read_text())["data"]
        self.misc = json.loads((CADSR_FIXTURES / "misc_endpoints.json").read_text())

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        self.path_counts[path] += 1
        if self.fail_next:
            return httpx.Response(self.fail_next.pop(0), json={"error": "injected"})
        q = dict(request.url.params)
        if path.startswith("/rad/NCILovAPI/") or path.endswith("/cdeMatch"):
            if not request.headers.get("Authorization", "").startswith("Basic "):
                return httpx.Response(401, json={"message": "unauthorized"})
        data = self.route(path, q, request)
        if data is None:
            return httpx.Response(404, json={"message": "not found"})
        return httpx.Response(200, json=data)

    def route(self, path: str, q: dict[str, str], request: httpx.Request) -> Any:
        if path == "/rad/NCIAPI/1.0/api/DataElement/2192199":
            if q.get("version") in (None, "1.0"):
                return self.de_2192199
            return {"apiResponse": {"type": "E", "message": "Data Element not found"}}
        if path == "/rad/NCIAPI/1.0/api/DataElements/Concept":
            key = f"{path}?conceptCode={q.get('conceptCode')}" + (f"&itemTypeFilter={q['itemTypeFilter']}" if q.get("itemTypeFilter") else "")
            return self.misc.get(key)
        if path == "/rad/NCIAPI/1.0/api/DataElements":
            return self.misc.get(f"{path}?publicId={q.get('publicId')}")
        if path in self.misc:
            return self.misc[path]
        return None


@pytest.fixture
def fake_cadsr() -> FakeCadsr:
    return FakeCadsr()


@pytest.fixture
def unified_settings() -> Settings:
    return Settings(_env_file=None, profile="unified", http_max_retries=2, budget_max_requests=10, log_level="WARNING",
                    icdo_cache_dir=str(ICDO_CACHE_FIXTURE), icdo_sync_interval_s=0)


@pytest.fixture
async def unified_services(unified_settings: Settings, fake_evs: FakeEvs, fake_cadsr: FakeCadsr) -> Services:
    svc = build_services(unified_settings, transport=fake_evs.transport(), cadsr_transport=fake_cadsr.transport())
    try:
        yield svc
    finally:
        await svc.aclose()


@pytest.fixture
def unified_mcp(unified_settings: Settings, unified_services: Services):
    server, _ = build_mcp_server(unified_settings, services=unified_services)
    return server


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, profile="evs-only", http_max_retries=2, budget_max_requests=10, log_level="WARNING")


@pytest.fixture
async def services(settings: Settings, fake_evs: FakeEvs) -> Services:
    svc = build_services(settings, transport=fake_evs.transport())
    try:
        yield svc
    finally:
        await svc.aclose()


@pytest.fixture
def mcp(settings: Settings, services: Services):
    server, _ = build_mcp_server(settings, services=services)
    return server
