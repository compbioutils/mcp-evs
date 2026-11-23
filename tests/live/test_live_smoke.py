"""Live smoke tests against api-evsrest.nci.nih.gov. Opt in with ``-m live`` and
``ECM_LIVE=1``; they are deselected by default (see pyproject)."""

from __future__ import annotations

import os

import pytest

from evs_cadsr_mcp.core.budget import Budget
from evs_cadsr_mcp.core.config import Settings
from evs_cadsr_mcp.core.context import Invocation
from evs_cadsr_mcp.server.mcp_app import build_services

pytestmark = [pytest.mark.live, pytest.mark.skipif(not os.environ.get("ECM_LIVE"), reason="set ECM_LIVE=1 to run")]


def inv(tool: str) -> Invocation:
    return Invocation(tool=tool, budget=Budget(max_requests=20))


@pytest.fixture
async def live():
    svc = build_services(Settings(_env_file=None, log_level="WARNING"))
    try:
        yield svc
    finally:
        await svc.aclose()


async def test_live_release_and_canonical_concepts(live):
    ctx = await live.evs.release_context("ncit", None)
    assert ctx.release and ctx.terminology_version.startswith("ncit_")
    env = await live.evs.get_concept(inv("evs_get_concept"), ctx, "C3224", ["summary"])
    assert env.result.name == "Melanoma"
    assert env.provenance[0].release == ctx.release
    batch = await live.evs.get_concepts(inv("evs_get_concepts"), ctx, ["C2926", "C3242", "C2852"], ["minimal"])
    assert {c.code for c in batch.result.concepts} == {"C2926", "C3242", "C2852"} and batch.meta.outboundRequests == 1


async def test_live_lookup_search_paths(live):
    ctx = await live.evs.release_context("ncit", None)
    m = await live.evs.lookup_concept(inv("l"), ctx, "NSCLC", match="normalized", synonym_source=None, term_type=None, include=None, limit=5)
    assert any(x.concept.code == "C2926" for x in m.result)
    s = await live.evs.search_concepts(inv("s"), ctx, None, search_type="match", include=None, limit=5, cursor=None, filters={"property": "ICD-O-3_Code", "value": "8140/3"})
    assert any(h.concept.code == "C2852" for h in s.result)
    p = await live.evs.get_paths(inv("p"), ctx, "C3224", "toRoot", None)
    assert p.result and p.result[0].concepts[0].code == "C3224"


async def test_live_subsets_maps_history(live):
    ctx = await live.evs.release_context("ncit", None)
    members = await live.evs.get_subset_members(inv("m"), ctx, "C54459", include=None, limit=5, cursor=None)
    assert members.result
    maps = await live.evs.list_mapsets(inv("ms"))
    assert any(m.code == "NCIt_Maps_To_GDC" for m in maps.result)
    hist = await live.evs.get_concept_history(inv("h"), ctx, "C3224")
    assert hist.result


@pytest.fixture
async def live_unified():
    svc = build_services(Settings(_env_file=None, profile="unified", log_level="WARNING"))
    try:
        yield svc
    finally:
        await svc.aclose()


async def test_live_gdc_race_end_to_end(live_unified):
    """UC-1 against both live upstreams: caDSR 2192199 v1.0 (GDC demographic.race) -> NCIt."""
    env = await live_unified.map.resolve_cde_concepts(inv("map"), "2192199", "1.0", None, include_pvs=True)
    r = env.result
    assert r.longName and r.property and r.valueMeanings
    assert {p.source for p in env.provenance} == {"cadsr_nciapi", "evs_rest"}
    assert all(v.conceptStatusAtRelease in ("active", "retired", "not_found", "unresolved") for v in r.valueMeanings)


async def test_live_icdo_mapping_files_download_and_map(tmp_path):
    from evs_cadsr_mcp.map.icdo_map import IcdoMapStore

    settings = Settings(_env_file=None, log_level="WARNING", icdo_cache_dir=str(tmp_path), icdo_sync_interval_s=86400)
    store = IcdoMapStore.from_settings(settings)
    icdo = await store.get()  # empty cache: downloads from evs.nci.nih.gov on first use
    assert len(icdo.entries) > 1500 and icdo.published is not None
    assert [e.ncit_code for e in icdo.lookup("8140/3")] == ["C2852"]
    assert "C12971" in {e.ncit_code for e in icdo.lookup("C50.9")}  # topography axis
    again = await store.sync()
    assert again.status == "unchanged"  # conditional requests: nothing re-downloaded
