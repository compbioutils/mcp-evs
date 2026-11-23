"""Contract tests: EVS service over the fake transport (release model, batching, paging,
license gate, resilience, fail-closed behaviour)."""

from __future__ import annotations

import pytest

from evs_cadsr_mcp.core.context import Invocation
from evs_cadsr_mcp.core.errors import EvsMcpError
from evs_cadsr_mcp.server.mcp_app import Services
from tests.conftest import FakeEvs


def inv(tool: str = "t", max_requests: int = 10) -> Invocation:
    from evs_cadsr_mcp.core.budget import Budget

    return Invocation(tool=tool, budget=Budget(max_requests=max_requests))


# ------------------------------------------------------------------ release model
async def test_active_release_is_latest_monthly(services: Services, fake_evs: FakeEvs):
    ctx = await services.evs.release_context("ncit", None)
    assert ctx.release == fake_evs.active and ctx.terminology_version == f"ncit_{fake_evs.active}" and ctx.active


async def test_requested_live_release_is_pinned_in_path(services: Services, fake_evs: FakeEvs):
    prev = fake_evs.previous
    ctx = await services.evs.release_context("ncit", prev)
    env = await services.evs.get_concept(inv(), ctx, "C3224", ["summary"])
    assert env.result.release == prev
    assert env.provenance[0].release == prev
    assert f"/concept/ncit_{prev}/C3224" in env.provenance[0].sourceUri
    assert fake_evs.path_counts[f"/concept/ncit_{prev}/C3224"] == 1


async def test_release_not_live_fails_closed(services: Services):
    with pytest.raises(EvsMcpError) as ei:
        await services.evs.release_context("ncit", "25.01d")
    assert ei.value.code == "release_not_available"
    assert ei.value.details["live"] and "details.live" in ei.value.hint


async def test_upstream_version_drift_fails_closed(services: Services, fake_evs: FakeEvs):
    ctx = await services.evs.release_context("ncit", fake_evs.drifting)
    with pytest.raises(EvsMcpError) as ei:
        await services.evs.get_concept(inv(), ctx, "C3224", ["summary"])
    assert ei.value.code == "release_mismatch"


async def test_list_releases_marks_active(services: Services, fake_evs: FakeEvs):
    env = await services.evs.list_releases(inv(), "ncit")
    assert env.result[0].version == fake_evs.active
    assert [r.active for r in env.result].count(True) == 1 and env.result[0].active


# ---------------------------------------------------------------------- content
async def test_get_concept_provenance_and_cache(services: Services, fake_evs: FakeEvs):
    ctx = await services.evs.release_context("ncit", None)
    first = await services.evs.get_concept(inv(), ctx, "C3224", None)
    assert first.provenance[0].servedBy == "live" and first.meta.outboundRequests == 1
    second = await services.evs.get_concept(inv(), ctx, "C3224", None)
    assert second.provenance[0].servedBy == "cache" and second.meta.outboundRequests == 0
    assert second.provenance[0].cachedAt is not None and second.meta.servedBy == "cache"
    assert fake_evs.path_counts[f"/concept/ncit_{fake_evs.active}/C3224"] == 1


async def test_get_concept_not_found(services: Services):
    ctx = await services.evs.release_context("ncit", None)
    with pytest.raises(EvsMcpError) as ei:
        await services.evs.get_concept(inv(), ctx, "C12345", None)
    assert ei.value.code == "not_found"


async def test_batch_uses_list_endpoint_not_fan_out(services: Services, fake_evs: FakeEvs):
    ctx = await services.evs.release_context("ncit", None)
    env = await services.evs.get_concepts(inv(), ctx, ["C3224", "C2926", "C99999", "C3224"], ["minimal"])
    assert [c.code for c in env.result.concepts] == ["C3224", "C2926"]
    assert env.result.missing == ["C99999"]
    assert env.meta.outboundRequests == 1
    assert fake_evs.path_counts[f"/concept/ncit_{fake_evs.active}"] == 1


async def test_batch_fetches_only_uncached_concepts(services: Services, fake_evs: FakeEvs):
    ctx = await services.evs.release_context("ncit", None)
    await services.evs.get_concepts(inv(), ctx, ["C41259", "C41260"], None)
    lists = lambda: [r.url.params["list"] for r in fake_evs.requests if "list" in r.url.params]  # noqa: E731
    before = len(lists())
    env = await services.evs.get_concepts(inv(), ctx, ["C41260", "C141478", "C41259"], None)
    assert lists()[before:] == ["C141478"]  # a differently composed batch reuses the cached concepts
    assert [c.code for c in env.result.concepts] == ["C41260", "C141478", "C41259"]  # request order
    assert any(p.servedBy == "cache" for p in env.provenance) and any(p.servedBy == "live" for p in env.provenance)
    again = await services.evs.get_concepts(inv(), ctx, ["C141478", "C41260"], None)
    assert len(lists()) == before + 1 and again.meta.outboundRequests == 0


async def test_lookup_by_code_then_synonym(services: Services):
    ctx = await services.evs.release_context("ncit", None)
    by_code = await services.evs.lookup_concept(inv(), ctx, "c3224", match="exact", synonym_source=None, term_type=None, include=None, limit=5)
    assert by_code.result[0].matchKind == "code" and by_code.result[0].concept.code == "C3224"
    by_syn = await services.evs.lookup_concept(inv(), ctx, "nsclc", match="normalized", synonym_source=None, term_type=None, include=["minimal"], limit=5)
    assert by_syn.result[0].matchKind == "synonym" and by_syn.result[0].matchedTerm == "NSCLC"
    assert by_syn.result[0].concept.code == "C2926"


async def test_search_paging_cursor_bound_to_release(services: Services, fake_evs: FakeEvs):
    ctx = await services.evs.release_context("ncit", None)
    env = await services.evs.search_concepts(inv(), ctx, "melanoma", search_type="contains", include=None, limit=3, cursor=None, filters={})
    assert [h.concept.code for h in env.result] == ["C3224", "C3510", "C7712"]
    assert env.page.total == 412 and env.page.nextCursor
    other = await services.evs.release_context("ncit", fake_evs.previous)
    with pytest.raises(EvsMcpError) as ei:
        await services.evs.search_concepts(inv(), other, "melanoma", search_type="contains", include=None, limit=3, cursor=env.page.nextCursor, filters={})
    assert ei.value.code == "cursor_expired"


async def test_search_by_filter_alone_sends_no_term(services: Services, fake_evs: FakeEvs):
    ctx = await services.evs.release_context("ncit", None)
    env = await services.evs.search_concepts(
        inv(), ctx, None, search_type="contains", include=None, limit=5, cursor=None, filters={"property": "ICD-O-3_Code", "value": "8140/3"})
    assert [h.concept.code for h in env.result] == ["C2852"]
    sent = [r for r in fake_evs.requests if r.url.path.endswith("/search")][-1].url.params
    assert "term" not in sent and sent["property"] == "ICD-O-3_Code" and sent["value"] == "8140/3"
    blank = await services.evs.search_concepts(
        inv(), ctx, "  ", search_type="contains", include=None, limit=5, cursor=None, filters={"property": "ICD-O-3_Code", "value": "8140/3"})
    assert [h.concept.code for h in blank.result] == ["C2852"]
    with pytest.raises(EvsMcpError) as ei:
        await services.evs.search_concepts(inv(), ctx, None, search_type="contains", include=None, limit=5, cursor=None, filters={"subset": None})
    assert ei.value.code == "invalid_request"


async def test_search_semantic_type_is_sent_as_property(services: Services, fake_evs: FakeEvs):
    # EVS ignores its semanticType parameter; the Semantic_Type property filter is what narrows results.
    ctx = await services.evs.release_context("ncit", None)
    await services.evs.search_concepts(
        inv(), ctx, "melanoma", search_type="contains", include=None, limit=5, cursor=None, filters={"semanticType": "Neoplastic Process"})
    sent = [r for r in fake_evs.requests if r.url.path.endswith("/search")][-1].url.params
    assert "semanticType" not in sent and sent["property"] == "Semantic_Type" and sent["value"] == "Neoplastic Process"
    with pytest.raises(EvsMcpError) as ei:
        await services.evs.search_concepts(
            inv(), ctx, None, search_type="contains", include=None, limit=5, cursor=None,
            filters={"semanticType": "Neoplastic Process", "property": "ICD-O-3_Code", "value": "8140/3"})
    assert ei.value.code == "invalid_request"


async def test_relationships_filter_and_polarity(services: Services):
    ctx = await services.evs.release_context("ncit", None)
    env = await services.evs.get_relationships(inv(), ctx, "C3224", ["roles", "inverseRoles"], None)
    kinds = {e.kind for e in env.result}
    assert kinds == {"role", "inverseRole"}
    neg = [e for e in env.result if e.polarity == "negative"]
    assert len(neg) == 1 and neg[0].type == "Disease_Excludes_Finding"
    only = await services.evs.get_relationships(inv(), ctx, "C3224", ["roles"], ["Disease_Has_Normal_Cell_Origin"])
    assert [e.code for e in only.result] == ["C12612"]


async def test_hierarchy_paths_descendants(services: Services):
    ctx = await services.evs.release_context("ncit", None)
    kids = await services.evs.get_hierarchy_neighbors(inv(), ctx, "C3224", "children")
    assert [e.code for e in kids.result] == ["C3510", "C7712"] and kids.result[0].kind == "child"
    roots = await services.evs.get_hierarchy_neighbors(inv(), ctx, None, "roots")
    assert roots.result[0].kind == "root"
    paths = await services.evs.get_paths(inv(), ctx, "C3224", "toRoot", None)
    assert len(paths.result) == 2 and paths.result[0].concepts[-1].code == "C7057"
    desc = await services.evs.get_descendants(inv(), ctx, "C3224", max_level=1, limit=4, cursor=None)
    assert len(desc.result) == 4 and desc.page.nextCursor  # page full -> may be more


async def test_subsets_and_members(services: Services):
    ctx = await services.evs.release_context("ncit", None)
    tree = await services.evs.list_subsets(inv(), ctx, None, "minimal")
    assert tree.result[0].children[0].code == "C61410"
    assert tree.provenance[0].sourceUri.split("?")[0].endswith("/subset/ncit")
    one = await services.evs.list_subsets(inv(), ctx, "C177537", "minimal")
    assert one.result[0].code == "C177537" and one.result[0].release == ctx.release
    members = await services.evs.get_subset_members(inv(), ctx, "C177537", include=None, limit=100, cursor=None)
    assert [c.code for c in members.result] == ["C3224", "C2926"] and members.page.nextCursor is None


async def test_subsets_from_another_release_fail_closed(services: Services, fake_evs: FakeEvs):
    ctx = await services.evs.release_context("ncit", fake_evs.previous)
    for code in (None, "C177537"):
        with pytest.raises(EvsMcpError) as ei:
            await services.evs.list_subsets(inv(), ctx, code, "minimal")
        assert ei.value.code == "release_mismatch"
        assert ei.value.details == {"requested": fake_evs.previous, "upstream": fake_evs.active}


# ------------------------------------------------------------------- license gate
async def test_concept_maps_withhold_gated_targets_without_key(services: Services):
    ctx = await services.evs.release_context("ncit", None)
    env = await services.evs.get_concept_maps(inv(), ctx, "C3224", None)
    assert {m.targetTerminology for m in env.result.maps} == {"GDC", "ICD10CM"}
    assert env.result.withheld == ["MedDRA"] and any("license" in w for w in env.warnings)
    gdc = await services.evs.get_concept_maps(inv(), ctx, "C3224", "gdc")
    assert [m.targetCode for m in gdc.result.maps] == ["8720/3"]


async def test_get_concept_include_maps_applies_license_gate(services: Services):
    ctx = await services.evs.release_context("ncit", None)
    env = await services.evs.get_concept(inv(), ctx, "C3224", ["maps"])
    assert {m.targetTerminology for m in env.result.maps} == {"GDC", "ICD10CM"}
    assert env.result.mapsWithheld == ["MedDRA"] and any("license" in w for w in env.warnings)


async def test_mapset_entries_gate_returns_count_only(services: Services, fake_evs: FakeEvs):
    env = await services.evs.get_mapset_entries(inv(), "NCIt_Maps_To_MedDRA", term=None, limit=10, cursor=None)
    assert env.result.licenseRequired and env.result.total == 12345 and env.result.entries == []
    # Only a 1-row probe was issued, and no license header was sent.
    req = [r for r in fake_evs.requests if r.url.path.endswith("/NCIt_Maps_To_MedDRA/maps")][0]
    assert req.url.params["pageSize"] == "1" and "X-EVSRESTAPI-License-Key" not in req.headers
    open_ = await services.evs.get_mapset_entries(inv(), "NCIt_Maps_To_GDC", term=None, limit=10, cursor=None)
    assert not open_.result.licenseRequired and len(open_.result.entries) == 2


async def test_mapset_entries_with_key_sends_header_only_for_gated(settings, fake_evs: FakeEvs):
    from evs_cadsr_mcp.server.mcp_app import build_services

    s = settings.model_copy(update={"license_key": "secret"})
    svc = build_services(s, transport=fake_evs.transport())
    try:
        env = await svc.evs.get_mapset_entries(inv(), "NCIt_Maps_To_MedDRA", term=None, limit=10, cursor=None)
        assert not env.result.licenseRequired and len(env.result.entries) == 1
        maps_req = [r for r in fake_evs.requests if r.url.path.endswith("/NCIt_Maps_To_MedDRA/maps")][0]
        assert maps_req.headers["X-EVSRESTAPI-License-Key"] == "secret"
        assert "secret" not in (env.provenance[-1].sourceUri or "")
        await svc.evs.get_mapset_entries(inv(), "NCIt_Maps_To_GDC", term=None, limit=10, cursor=None)
        gdc_req = [r for r in fake_evs.requests if r.url.path.endswith("/NCIt_Maps_To_GDC/maps")][0]
        assert "X-EVSRESTAPI-License-Key" not in gdc_req.headers
    finally:
        await svc.aclose()


# ----------------------------------------------------------------------- history
async def test_history_falls_back_to_replacements_for_absent_code(services: Services):
    ctx = await services.evs.release_context("ncit", None)
    env = await services.evs.get_concept_history(inv(), ctx, "C12345")
    assert env.result[0].replacementCode == "C3224" and env.warnings


# -------------------------------------------------------------------- resilience
async def test_retries_count_against_budget(services: Services, fake_evs: FakeEvs, monkeypatch):
    import evs_cadsr_mcp.core.http_client as hc

    async def no_sleep(_):
        return None

    monkeypatch.setattr(hc.asyncio, "sleep", no_sleep)
    ctx = await services.evs.release_context("ncit", None)
    fake_evs.fail_next = [503, 429]
    env = await services.evs.get_concept(inv(max_requests=10), ctx, "C3224", ["minimal"])
    assert env.meta.outboundRequests == 3  # two failed attempts + one success


async def test_budget_exhaustion_is_bound_exceeded(services: Services, fake_evs: FakeEvs, monkeypatch):
    import evs_cadsr_mcp.core.http_client as hc

    async def no_sleep(_):
        return None

    monkeypatch.setattr(hc.asyncio, "sleep", no_sleep)
    ctx = await services.evs.release_context("ncit", None)
    fake_evs.fail_next = [503, 503, 503]
    with pytest.raises(EvsMcpError) as ei:
        await services.evs.get_concept(inv(max_requests=2), ctx, "C3224", ["children"])
    assert ei.value.code == "bound_exceeded"


async def test_upstream_unavailable_after_retries(services: Services, fake_evs: FakeEvs, monkeypatch):
    import evs_cadsr_mcp.core.http_client as hc

    async def no_sleep(_):
        return None

    monkeypatch.setattr(hc.asyncio, "sleep", no_sleep)
    ctx = await services.evs.release_context("ncit", None)
    fake_evs.fail_next = [500, 500, 500, 500]
    with pytest.raises(EvsMcpError) as ei:
        await services.evs.get_concept(inv(max_requests=10), ctx, "C3224", ["parents"])
    assert ei.value.code == "upstream_unavailable" and ei.value.retryable
