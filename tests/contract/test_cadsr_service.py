"""Contract tests for the caDSR module (proposal Section 7): 200-with-error mapping, the
ISO 11179 normaliser, derived views with server-side paging, reverse lookup, declared
fan-out with coverage, forms, credential degradation, matching, and caching."""

from __future__ import annotations

import json

import pytest

from evs_cadsr_mcp.cadsr.models import MatchEntity
from evs_cadsr_mcp.core.budget import Budget
from evs_cadsr_mcp.core.context import Invocation
from evs_cadsr_mcp.core.errors import EvsMcpError
from evs_cadsr_mcp.server.mcp_app import Services, build_services
from tests.conftest import FakeCadsr


def inv(max_requests: int = 20) -> Invocation:
    return Invocation(tool="t", budget=Budget(max_requests=max_requests))


# --------------------------------------------------------------- CDE + views
async def test_get_data_element_normalises_iso11179_structure(unified_services: Services, fake_cadsr: FakeCadsr):
    svc = unified_services.cadsr
    env = await svc.get_data_element(inv(), "2192199", "1.0", None)
    de = env.result
    assert de.publicId == "2192199" and de.version == "1.0" and de.longName == "Race Category Text"
    assert de.workflowStatus == "RELEASED" and de.latestVersion is True and de.context == "NCIP"
    assert de.questionText == "Race"  # preferred question text from reference documents
    dec = de.dataElementConcept
    assert dec.objectClass.concepts[0].conceptCode == "C25190" and dec.objectClass.conceptCodes == "C25190"
    assert dec.property.concepts[0].conceptCode == "C17049" and dec.property.concepts[0].evsSource == "NCI_CONCEPT_CODE"
    vd = de.valueDomain
    assert vd.type == "Enumerated" and vd.dataType == "CHARACTER" and vd.maxLength == 100
    assert vd.representationTerm.conceptCodes == "C25372"
    assert vd.permissibleValueCount == 8 and vd.permissibleValues is None  # not inlined by default
    assert de.alternateNames is None and de.referenceDocuments is None  # sections not requested
    # provenance pins the registry item
    p = env.provenance[0]
    assert p.source == "cadsr_nciapi" and p.servedBy == "live" and p.registry.publicId == "2192199" and p.registry.version == "1.0"
    assert p.registry.retrievedAt is not None and "DataElement/2192199" in p.sourceUri
    # request carried Accept: application/json and a correlation id
    req = fake_cadsr.requests[-1]
    assert req.headers["Accept"] == "application/json" and req.headers["X-Correlation-ID"] == env.meta.correlationId


async def test_get_data_element_include_sections_and_cache(unified_services: Services, fake_cadsr: FakeCadsr):
    svc = unified_services.cadsr
    env = await svc.get_data_element(inv(), "2192199", "1.0", ["permissibleValues", "alternateNames", "classificationSchemes", "referenceDocuments"])
    de = env.result
    assert len(de.valueDomain.permissibleValues) == 8 and de.valueDomain.permissibleValues[1].valueMeaning.concepts[0].conceptCode == "C41260"
    assert {a.name for a in de.alternateNames} == {"RACE", "demographic.race"}
    assert de.classificationSchemes[0].items[0].longName == "demographic"
    assert len(de.referenceDocuments) == 2 and de.dataElementConcept is None
    # second view of the same CDE is served from cache: one upstream fetch serves every view
    vd = await svc.get_value_domain(inv(), "2192199", "1.0")
    assert vd.provenance[0].servedBy == "cache" and vd.meta.outboundRequests == 0
    assert fake_cadsr.path_counts["/rad/NCIAPI/1.0/api/DataElement/2192199"] == 1


async def test_permissible_values_paged_server_side_with_pinned_cursor(unified_services: Services, fake_cadsr: FakeCadsr):
    svc = unified_services.cadsr
    p1 = await svc.get_permissible_values(inv(), "2192199", "1.0", limit=3, cursor=None)
    assert [pv.value for pv in p1.result] == ["American Indian or Alaska Native", "Asian", "Black or African American"]
    assert p1.page.total == 8 and p1.page.nextCursor
    p2 = await svc.get_permissible_values(inv(), "2192199", "1.0", limit=3, cursor=p1.page.nextCursor)
    assert p2.result[0].value == "Native Hawaiian or other Pacific Islander" and p2.result[0].valueMeaning.concepts[0].conceptCode == "C41219"
    p3 = await svc.get_permissible_values(inv(), "2192199", "1.0", limit=3, cursor=p2.page.nextCursor)
    assert [pv.value for pv in p3.result] == ["Unknown", "Other"] and p3.result[1].endDate == "2020-01-15" and p3.page.nextCursor is None
    assert fake_cadsr.path_counts["/rad/NCIAPI/1.0/api/DataElement/2192199"] == 1  # all three pages from one fetch
    # a cursor minted for another item/version is refused
    with pytest.raises(EvsMcpError) as ei:
        await svc.get_permissible_values(inv(), "2192199", "2.0", limit=3, cursor=p1.page.nextCursor)
    assert ei.value.code in ("cursor_expired", "not_found")


async def test_data_element_concept_view(unified_services: Services):
    env = await unified_services.cadsr.get_data_element_concept(inv(), "2192199", None)
    assert env.result.publicId == "2192198" and env.result.property.longName == "Race" and env.result.conceptualDomain.longName == "Demographic Characteristics"


async def test_200_with_error_body_maps_to_closed_codes(unified_services: Services):
    svc = unified_services.cadsr
    with pytest.raises(EvsMcpError) as ei:
        await svc.get_data_element(inv(), "9999999", None, None)
    assert ei.value.code == "not_found"
    with pytest.raises(EvsMcpError) as ei:
        await svc.get_data_element(inv(), "1", None, None)
    assert ei.value.code == "invalid_request"
    with pytest.raises(EvsMcpError) as ei:
        await svc.get_data_element(inv(), "2192199", "7.0", None)
    assert ei.value.code == "not_found"


async def test_versions_normalise_field_drift(unified_services: Services):
    env = await unified_services.cadsr.get_data_element_versions(inv(), "2192199")
    assert [v.version for v in env.result] == ["2.0", "1.0"]  # newest first, publicID + latesetVersionIndicator tolerated
    assert env.result[0].latestVersion is True and env.result[1].latestVersion is False


async def test_get_data_elements_is_one_call_per_id(unified_services: Services, fake_cadsr: FakeCadsr):
    env = await unified_services.cadsr.get_data_elements(inv(), [{"publicId": "2192199", "version": "1.0"}, {"publicId": "9999999", "version": None}])
    assert [d.publicId for d in env.result.dataElements] == ["2192199"] and env.result.missing == ["9999999"]
    assert env.meta.outboundRequests == 2 and any("one upstream call per id" in w for w in env.warnings)


# ------------------------------------------------------------- reverse lookup
async def test_find_by_concept_paged_and_status_normalised(unified_services: Services):
    svc = unified_services.cadsr
    env = await svc.find_data_elements_by_concept(inv(), "C17049", item_type=None, workflow_status=None, limit=2, cursor=None)
    assert [s.publicId for s in env.result] == ["2003853", "2192199"] and env.page.total == 3 and env.page.nextCursor
    assert env.result[0].workflowStatus == "SUPERSEDED"  # "Superceded" drift normalised
    assert env.result[0].matchedRole is None and any("matchedRole" in w for w in env.warnings)
    nxt = await svc.find_data_elements_by_concept(inv(), "C17049", item_type=None, workflow_status=None, limit=2, cursor=env.page.nextCursor)
    assert [s.publicId for s in nxt.result] == ["6424122"] and nxt.page.nextCursor is None
    by_role = await svc.find_data_elements_by_concept(inv(), "C17049", item_type="Property", workflow_status=None, limit=10, cursor=None)
    assert [s.publicId for s in by_role.result] == ["2192199"] and by_role.result[0].matchedRole == "Property"
    with pytest.raises(EvsMcpError) as ei:
        await svc.find_data_elements_by_concept(inv(), "C99999", item_type=None, workflow_status=None, limit=10, cursor=None)
    assert ei.value.code == "not_found"


# ------------------------------------------------------------------- fan-out
async def test_fan_out_search_reports_coverage(unified_services: Services, fake_cadsr: FakeCadsr):
    svc = unified_services.cadsr
    env = await svc.find_data_elements(inv(), "race", by=["alternateName", "questionText", "context", "classification"], exact=False, context=None, scheme_id=None, scheme_version=None, limit=50, cursor=None)
    r = env.result
    assert set(r.coverage.routesRun) == {"alternateName", "questionText"}
    assert any(s.startswith("context") for s in r.coverage.routesSkipped) and any(s.startswith("classification") for s in r.coverage.routesSkipped)
    ids = {s.publicId: s for s in r.dataElements}
    assert set(ids) == {"2192199", "2003853", "5281240"}
    assert ids["2192199"].matchedVia == "alternateName,questionText"  # de-duplicated across routes
    assert env.page.total == 3 and env.meta.outboundRequests == 2
    assert any("not exhaustive" in w for w in env.warnings)
    # the two routes ran concurrently and never hit a search endpoint
    assert not any("search" in req.url.path.lower() for req in fake_cadsr.requests)


async def test_fan_out_context_route_narrows_locally(unified_services: Services):
    env = await unified_services.cadsr.find_data_elements(inv(), "ethnic", by=["context"], exact=False, context="NCIP", scheme_id=None, scheme_version=None, limit=50, cursor=None)
    assert [s.publicId for s in env.result.dataElements] == ["2192217"] and env.result.coverage.routesRun == ["context"]


# --------------------------------------------------------------------- forms
async def test_form_and_forms_for_cde(unified_services: Services):
    svc = unified_services.cadsr
    f = await svc.get_form(inv(), "3105395", None, include_modules=True)
    assert f.result.longName == "Demographics Form" and f.result.questionCount == 2 and f.result.protocol == "Protocol X"
    q = f.result.modules[0].questions[0]
    assert q.dataElement.publicId == "2192199" and [v.value for v in q.validValues] == ["White", "Asian"]
    assert f.provenance[0].source == "cadsr_formapi" and f.provenance[0].registry.publicId == "3105395"
    header = await svc.get_form(inv(), "3105395", None, include_modules=False)
    assert header.result.modules is None and header.result.questionCount == 2 and header.provenance[0].servedBy == "cache"
    usage = await svc.get_forms_for_data_element(inv(), "2192199", "1.0")
    assert [(u.formPublicId, u.formVersion) for u in usage.result] == [("3105395", "1.0"), ("4000010", "2.0")]
    assert usage.provenance[0].source == "cadsr_legacy" and any("legacy" in w for w in usage.warnings)


# --------------------------------------------------------------- credentials
async def test_credentialed_services_degrade_with_reason(unified_services: Services, fake_cadsr: FakeCadsr):
    svc = unified_services.cadsr
    with pytest.raises(EvsMcpError) as ei:
        await svc.list_contexts(inv())
    assert ei.value.code == "capability_unavailable" and "ECM_CADSR_CREDENTIAL" in ei.value.message
    with pytest.raises(EvsMcpError) as ei:
        await svc.match_data_elements(inv(), [MatchEntity(name="race")], match_limit=5, contexts=None, backend="cde_match")
    assert ei.value.code == "capability_unavailable"
    with pytest.raises(EvsMcpError) as ei:
        await svc.match_data_elements(inv(), [MatchEntity(name="race")], match_limit=5, contexts=None, backend="ai_engine")
    assert ei.value.code == "capability_unavailable" and "ECM_CADSR_AI_MATCH_URL" in ei.value.message
    assert not any(r.url.path.startswith("/rad/NCILovAPI") for r in fake_cadsr.requests)  # no call was attempted
    backends = await svc.list_match_backends(inv())
    assert {b.name: b.available for b in backends.result} == {"cde_match": False, "ai_engine": False, "vm_match": True}


@pytest.mark.parametrize("creds", [
    {"cadsr_username": "svc-user", "cadsr_password": "s3cret"},
    {"cadsr_credential": "svc-user:s3cret"},
], ids=["separate-parts", "combined"])
async def test_credentialed_services_work_with_basic_auth(unified_settings, fake_evs, fake_cadsr: FakeCadsr, creds):
    import base64

    s = unified_settings.model_copy(update=creds)
    services = build_services(s, transport=fake_evs.transport(), cadsr_transport=fake_cadsr.transport())
    try:
        ctxs = await services.cadsr.list_contexts(inv())
        assert [c.name for c in ctxs.result] == ["NCIP", "CTEP"]
        lov_req = [r for r in fake_cadsr.requests if r.url.path.startswith("/rad/NCILovAPI")][0]
        assert lov_req.url.path == "/rad/NCILovAPI/1.0/api/getContextNames"
        assert lov_req.headers["Authorization"] == "Basic " + base64.b64encode(b"svc-user:s3cret").decode()
        # credentialed results are not cached across invocations
        again = await services.cadsr.list_contexts(inv())
        assert again.provenance[0].servedBy == "live"
        env = await services.cadsr.match_data_elements(inv(), [MatchEntity(name="race", permissibleValues=["White", "Asian"])], match_limit=5, contexts=["NCIP", "CTEP"], backend="cde_match")
        assert [m.publicId for m in env.result] == ["2192199", "6424122"] and env.result[0].score == 0.97 and env.result[0].backend == "cde_match"
        assert env.result[0].version == "1.0"  # CDE Match says "1"; reported like every other caDSR tool
        assert env.result[0].matchedField.startswith("2. Question Text Exact Match") and env.result[0].raw["context"] == "NCIP"
        # CDE Match's short longName is replaced by NCI API 1.0's; the original stays in raw
        assert env.result[0].longName == "Race Category Text" and env.result[0].raw["longName"] == "RACE_CAT_TXT"
        assert env.provenance[0].source == "cadsr_match"
        # the request follows the published contract: one entity per POST, limits as headers
        [match_req] = [r for r in fake_cadsr.requests if r.url.path.endswith("/cdeMatch")]
        assert json.loads(match_req.content) == {"entity": "race", "pvvmData": [{"name": "White"}, {"name": "Asian"}]}
        assert match_req.headers["matchLimit"] == "5" and match_req.headers["contexts"] == "NCIP,CTEP"
        two = await services.cadsr.match_data_elements(inv(), [MatchEntity(name="race"), MatchEntity(name="ethnicity", userTip="Hispanic or not")], match_limit=2, contexts=None, backend="cde_match")
        bodies = [json.loads(r.content) for r in fake_cadsr.requests if r.url.path.endswith("/cdeMatch")][1:]
        assert bodies == [{"entity": "race"}, {"entity": "ethnicity", "entityUserTip": "Hispanic or not"}]
        assert {m.entity for m in two.result} == {"race"}  # the fake answers every POST for "race"
        # candidates were resolved against NCI API 1.0 before being cited
        assert fake_cadsr.path_counts["/rad/NCIAPI/1.0/api/DataElement/2192199"] >= 1
        # the credential never appears in provenance URIs
        assert all("s3cret" not in (p.sourceUri or "") for p in env.provenance)
    finally:
        await services.aclose()


async def test_vm_match_and_crdc_map(unified_services: Services):
    svc = unified_services.cadsr
    vm = await svc.match_value_meanings(inv(), ["White", "Caucasian", "Martian"], strictness=None, scope=None)
    assert [v.value for v in vm.result] == ["White", "Caucasian", "Martian"]
    assert vm.result[1].candidates[0]["conceptCode"] == "C41261" and vm.result[2].candidates == []
    crdc = await svc.get_crdc_code_map(inv(), None, limit=10, cursor=None)
    assert [e.dataElementPublicId for e in crdc.result] == ["2192199", "2192217"] and crdc.result[0].raw["crdcName"] == "race"
    one = await svc.get_crdc_code_map(inv(), "2192217", limit=10, cursor=None)
    assert len(one.result) == 1 and one.provenance[0].servedBy == "cache"


async def test_registry_status_never_invents_a_release(unified_services: Services):
    env = await unified_services.cadsr.get_registry_status(inv())
    assert env.result.published is False and env.result.exportDate is None and env.warnings


# ---------------------------------------------------------------- resilience
async def test_cadsr_retries_5xx_but_not_200_errors(unified_services: Services, fake_cadsr: FakeCadsr, monkeypatch):
    import evs_cadsr_mcp.core.http_client as hc

    async def no_sleep(_):
        return None

    monkeypatch.setattr(hc.asyncio, "sleep", no_sleep)
    fake_cadsr.fail_next = [503]
    env = await unified_services.cadsr.get_data_element(inv(), "2192199", "1.0", None)
    assert env.meta.outboundRequests == 2
    # a 200-with-error body is final: exactly one request, no retry
    before = fake_cadsr.path_counts["/rad/NCIAPI/1.0/api/DataElement/9999999"]
    with pytest.raises(EvsMcpError):
        await unified_services.cadsr.get_data_element(inv(), "9999999", None, None)
    assert fake_cadsr.path_counts["/rad/NCIAPI/1.0/api/DataElement/9999999"] == before + 1


async def test_evs_only_profile_has_no_cadsr(services: Services):
    assert services.cadsr is None and services.cadsr_http is None
